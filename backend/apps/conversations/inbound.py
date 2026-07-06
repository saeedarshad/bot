"""Turns a normalized inbound message into a reply: clinic routing, patient
upsert, consent + STOP/HELP enforcement, conversation state, and the bot turn."""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.clinics.models import Clinic, Patient
from apps.scheduling.models import ACTIVE_STATUSES, Appointment

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
        appt = Appointment.objects.filter(
            id=appt_id, clinic=clinic, patient=patient, status__in=ACTIVE_STATUSES
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

    if conversation.bot_paused:
        logger.info("Conversation %s is paused (human handoff); bot silent", conversation.id)
        return None

    if conversation.status == ConversationStatus.ESCALATED:
        conversation.status = ConversationStatus.ACTIVE
        conversation.save(update_fields=["status"])

    ctx = ConvContext(clinic=clinic, patient=patient, conversation=conversation)
    history = build_history(conversation, text)
    return generate_reply(ctx, history, text)
