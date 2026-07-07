"""Turns a normalized inbound message into a reply: clinic routing, patient
upsert, consent + STOP/HELP enforcement, conversation state, and the bot turn."""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.clinics.models import Clinic, Patient
from apps.scheduling.models import ACTIVE_STATUSES, Appointment, AppointmentStatus

from .engine import generate_reply
from .models import Conversation, ConversationStatus
from .reply import BotReply
from .tools import ConvContext

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20
_STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCELALL", "QUIT", "END"}
_START_WORDS = {"START", "UNSTOP", "YES"}
_HELP_WORDS = {"HELP", "INFO"}
# Single-letter replies to a 24h reminder over a plain-text channel (no buttons).
_REMINDER_LETTERS = {"C": "confirm", "R": "reschedule", "X": "cancel"}


def resolve_clinic(phone_number_id: str) -> Clinic | None:
    if phone_number_id:
        clinic = Clinic.objects.filter(
            whatsapp_phone_number_id=phone_number_id, is_active=True
        ).first()
        if clinic:
            return clinic
    # Demo fallback: single-clinic deployments route everything to the one clinic.
    active = Clinic.objects.filter(is_active=True)
    if active.count() == 1:
        return active.first()
    return None


def _normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    if raw and not raw.startswith("+"):
        return "+" + raw
    return raw


def upsert_patient(clinic: Clinic, from_number: str, channel: str) -> Patient:
    phone = _normalize_phone(from_number)
    patient, created = Patient.objects.get_or_create(
        clinic=clinic,
        phone_e164=phone,
        defaults={
            "preferred_channel": channel,
            # Inbound text = consent to reply on this channel (TCPA: replies only).
            "sms_consent_at": timezone.now(),
            "sms_consent_source": f"inbound_{channel}",
            "sms_consent_text": "Patient initiated contact.",
        },
    )
    patient.last_seen_at = timezone.now()
    patient.save(update_fields=["last_seen_at"])
    return patient


def get_conversation(clinic: Clinic, patient: Patient, channel: str) -> Conversation:
    conv = (
        Conversation.objects.filter(clinic=clinic, patient=patient, channel=channel)
        .order_by("-last_message_at")
        .first()
    )
    if conv is None:
        conv = Conversation.objects.create(clinic=clinic, patient=patient, channel=channel)
    return conv


def build_history(conversation: Conversation, current_text: str) -> list[dict]:
    from apps.messaging.models import Direction

    rows = list(
        conversation.messages.order_by("-created_at")[:HISTORY_LIMIT][::-1]
    )
    history: list[dict] = []
    for m in rows:
        role = "user" if m.direction == Direction.IN else "assistant"
        if m.body:
            history.append({"role": role, "content": m.body})
    # Ensure the current inbound text is the final user turn.
    if not (history and history[-1]["role"] == "user" and history[-1]["content"] == current_text):
        history.append({"role": "user", "content": current_text})
    return history


def _keyword_reply(patient: Patient, text: str) -> str | None:
    """Channel-layer STOP/HELP enforcement — runs before any bot logic so no code
    path can message an opted-out patient."""
    word = "".join(text.upper().split())
    if word in _STOP_WORDS:
        if patient.opted_out_at is None:
            patient.opted_out_at = timezone.now()
            patient.save(update_fields=["opted_out_at"])
        return "You've been unsubscribed and won't receive further messages. Reply START to opt back in."
    if word in _START_WORDS and patient.opted_out_at is not None:
        patient.opted_out_at = None
        patient.save(update_fields=["opted_out_at"])
        return "You're opted back in. How can I help you today?"
    if word in _HELP_WORDS:
        return "This is an automated clinic assistant. Text us to ask a question or book an appointment. Reply STOP to opt out."
    return None


def _next_active_appointment(clinic: Clinic, patient: Patient) -> Appointment | None:
    return (
        Appointment.objects.filter(
            clinic=clinic,
            patient=patient,
            status__in=ACTIVE_STATUSES,
            starts_at__gte=timezone.now(),
        )
        .order_by("starts_at")
        .first()
    )


def _reminder_action(
    clinic: Clinic, patient: Patient, text: str, reply_option_id: str | None
) -> tuple[str | None, Appointment | None]:
    """Map a 24h-reminder response to (action, appointment). Handles both a tapped
    button (id `confirm_appt_{id}`) and a bare `C`/`R`/`X` text reply — the latter
    is only treated as a reminder action when the patient has an upcoming
    appointment, so it can't hijack an unrelated single-character message."""
    from apps.messaging.reminders import parse_option_id

    action, appt_id = parse_option_id(reply_option_id)
    if action:
        # A rebook tap (no-show recovery button) references the MISSED appointment,
        # which is terminal — every other action requires an active one.
        wanted = (
            (AppointmentStatus.NO_SHOW,) if action == "rebook" else ACTIVE_STATUSES
        )
        appt = Appointment.objects.filter(
            id=appt_id, clinic=clinic, patient=patient, status__in=wanted
        ).first()
        return (action, appt) if appt else (None, None)

    word = text.strip().upper()
    if word in _REMINDER_LETTERS:
        appt = _next_active_appointment(clinic, patient)
        if appt is not None:
            return _REMINDER_LETTERS[word], appt
    return None, None


def _confirm_ack(clinic: Clinic, patient: Patient, appt: Appointment) -> BotReply:
    tz = ZoneInfo(clinic.timezone)
    when = appt.starts_at.astimezone(tz).strftime("%a, %b %-d at %-I:%M %p")
    first = (patient.name or "").strip().split()[0] if patient.name else ""
    hi = f"Thanks {first}, " if first else "Thanks, "
    return BotReply(text=f"{hi}you're confirmed for {when}. See you then!")


def _waitlist_offer_reply(clinic: Clinic, patient: Patient, offer_id: int) -> BotReply:
    """Deterministic handling of a waitlist slot-open tap: the engine books (or
    reports the race lost) — no LLM in the loop, so the marquee cancel→offer→book
    path works even if the model is down. Runs even when a human owns the
    conversation: the hold is short and silence would cost the patient the slot."""
    from apps.messaging.waitlist import accept_offer

    outcome = accept_offer(clinic, patient, offer_id)
    first = (patient.name or "").strip().split()[0] if patient.name else ""
    hi = f"{first}, you" if first else "You"
    if outcome.result == "booked":
        return BotReply(
            text=f"{hi} got it! You're booked for {outcome.when}. See you then!"
        )
    if outcome.result == "already_booked":
        return BotReply(text=f"{hi}'re all set — {outcome.when} is yours. See you then!")
    if outcome.result == "filled":
        return BotReply(
            text="So sorry — that spot was just taken. You're still on our "
            "waitlist and we'll text you the moment another time opens up."
        )
    # expired / not_found
    return BotReply(
        text="That offer has expired, sorry! You're still on our waitlist — "
        "reply here anytime to see current openings."
    )


def handle_inbound(
    clinic: Clinic,
    patient: Patient,
    conversation: Conversation,
    text: str,
    reply_option_id: str | None = None,
) -> BotReply | None:
    """Return the bot's reply, or None if the bot should stay silent."""
    keyword = _keyword_reply(patient, text)
    if keyword is not None:
        return BotReply(text=keyword)

    from apps.messaging.waitlist import parse_offer_option_id

    offer_id = parse_offer_option_id(reply_option_id)
    if offer_id is not None:
        return _waitlist_offer_reply(clinic, patient, offer_id)

    action, appt = _reminder_action(clinic, patient, text, reply_option_id)
    if action == "confirm":
        # Pure acknowledgement — record it and reply even if a human has the
        # conversation, since it changes no calendar state.
        from apps.scheduling.engine import confirm_appointment

        confirm_appointment(clinic, patient, appt.id)
        return _confirm_ack(clinic, patient, appt)
    if action == "reschedule":
        text = f"I'd like to reschedule my upcoming appointment (id {appt.id})."
    elif action == "cancel":
        text = f"I'd like to cancel my upcoming appointment (id {appt.id})."
    elif action == "rebook":
        # Recovery offer tap: this is a NEW booking for the missed service, not a
        # reschedule (the no-show appointment is terminal). Attribution to the
        # no-show happens deterministically when the booking lands (messaging).
        # Carry the service id so the model queries availability for the right
        # service instead of guessing an id (tools re-validate it regardless).
        text = (
            f"I missed my {appt.service.name} appointment (service id "
            f"{appt.service_id}) and I'd like to book a new time."
        )

    if conversation.bot_paused:
        logger.info("Conversation %s is paused (human handoff); bot silent", conversation.id)
        return None

    if conversation.status == ConversationStatus.ESCALATED:
        conversation.status = ConversationStatus.ACTIVE
        conversation.save(update_fields=["status"])

    ctx = ConvContext(clinic=clinic, patient=patient, conversation=conversation)
    history = build_history(conversation, text)
    return generate_reply(ctx, history, text)
