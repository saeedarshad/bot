"""Waitlist slot-open offers: when a cancellation frees a bookable slot, offer
it to the oldest matching waitlist entries with a short hold, first-confirm-wins.

Follows the outbox discipline: an offer is a row first (WaitlistOffer, idempotent
per freed slot), sent by a claiming dispatcher with quiet-hours deferral and
retry — the Celery task just calls create + send so the first attempt is instant.
Booking on tap goes through engine.book_slot (advisory lock + live re-check), so
two racing taps can never both win; the loser gets the graceful "just filled"
path and returns to the waitlist.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.scheduling.models import Appointment, Waitlist, WaitlistStatus

from .channels import get_channel
from .costs import unit_cost
from .models import (
    Direction,
    Message,
    MessageCategory,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from .reminders import next_send_time

logger = logging.getLogger(__name__)

# How many entries get the offer at once (first to confirm wins) and how long
# each offer is held open before the slot can be re-offered.
OFFER_FANOUT = 3
OFFER_HOLD = timedelta(hours=2)
_MAX_ATTEMPTS = 5

_OFFER_PREFIX = "waitlist_offer_"

# Waitlist offers are utility, not marketing: the patient explicitly asked to be
# notified when a slot opens (decision 2026-07-07). Opt-out is still honored.
OFFER_CATEGORY = MessageCategory.UTILITY

TEMPLATE_NAME = "waitlist_slot_open"
TEMPLATE_LANG = "en_US"


def offer_option_id(offer_id: int) -> str:
    return f"{_OFFER_PREFIX}{offer_id}"


def parse_offer_option_id(reply_option_id: str | None) -> int | None:
    """Inverse of offer_option_id. Returns the offer id, or None if the tapped
    option is not a waitlist offer."""
    if not reply_option_id or not reply_option_id.startswith(_OFFER_PREFIX):
        return None
    tail = reply_option_id[len(_OFFER_PREFIX):]
    return int(tail) if tail.isdigit() else None


def _offer_parts(offer: WaitlistOffer) -> tuple[str, str, str]:
    clinic = offer.clinic
    patient = offer.waitlist.patient
    name = (patient.name or "").strip()
    first = name.split()[0] if name else "there"
    when = offer.slot_starts_at.astimezone(ZoneInfo(clinic.timezone)).strftime(
        "%a, %b %-d at %-I:%M %p"
    )
    return first, clinic.name, when


def build_offer_template(offer: WaitlistOffer) -> dict:
    first, clinic_name, when = _offer_parts(offer)
    return {
        "name": TEMPLATE_NAME,
        "language": TEMPLATE_LANG,
        "body_params": [first, clinic_name, when],
        "buttons": [{"index": 0, "payload": offer_option_id(offer.id)}],
    }


def build_offer_body(offer: WaitlistOffer) -> str:
    """Plain-text fallback, kept in sync with the template wording."""
    first, clinic_name, when = _offer_parts(offer)
    return (
        f"Hi {first}, good news from {clinic_name} — a spot just opened up: {when}. "
        "Reply here to grab it (first come, first served)."
    )


def create_offers(appointment: Appointment) -> int:
    """Queue offers for the slot this now-terminal appointment freed. Idempotent:
    UNIQUE(waitlist, freed_appointment) means re-running for the same freed slot
    can't offer twice, and only still-active entries are matched."""
    from apps.scheduling.engine import freed_slot, freed_slot_available, match_waitlist

    clinic = appointment.clinic
    if not (clinic.reminders_enabled and freed_slot_available(appointment)):
        return 0

    slot = freed_slot(appointment)
    now = timezone.now()
    created = 0
    for entry in match_waitlist(appointment, limit=OFFER_FANOUT):
        _, was_created = WaitlistOffer.objects.get_or_create(
            waitlist=entry,
            freed_appointment=appointment,
            defaults={
                "clinic": clinic,
                "slot_token": slot.token,
                "slot_starts_at": slot.start,
                "scheduled_for": next_send_time(clinic, now),
            },
        )
        if was_created:
            entry.status = WaitlistStatus.OFFERED
            entry.save(update_fields=["status", "updated_at"])
            created += 1
    return created


def send_due_offers(batch_size: int = 50) -> str:
    """Send pending offers whose time has come. Same claiming discipline as the
    reminder dispatcher: row lock via select_for_update(skip_locked), quiet-hours
    deferral, pending-on-failure retry. The hold clock starts at the actual send."""
    now = timezone.now()
    sent = deferred = failed = skipped = 0

    with transaction.atomic():
        rows = list(
            WaitlistOffer.objects.select_for_update(skip_locked=True)
            .filter(status=WaitlistOfferStatus.PENDING, scheduled_for__lte=now)
            .select_related("clinic", "waitlist", "waitlist__patient")[:batch_size]
        )
        for offer in rows:
            patient = offer.waitlist.patient
            if patient.opted_out_at is not None:
                offer.status = WaitlistOfferStatus.EXPIRED
                offer.last_error = "patient_opted_out"
                offer.save(update_fields=["status", "last_error", "updated_at"])
                skipped += 1
                continue
            if offer.slot_starts_at <= now:
                # The slot start passed while the offer waited (quiet hours).
                offer.status = WaitlistOfferStatus.EXPIRED
                offer.last_error = "slot_in_past"
                offer.save(update_fields=["status", "last_error", "updated_at"])
                _reactivate(offer.waitlist)
                skipped += 1
                continue
            open_at = next_send_time(offer.clinic, now)
            if open_at > now:
                offer.scheduled_for = open_at
                offer.save(update_fields=["scheduled_for", "updated_at"])
                deferred += 1
                continue
            if _send_offer(offer):
                sent += 1
            else:
                failed += 1

    return f"sent={sent} deferred={deferred} failed={failed} skipped={skipped}"


def _send_offer(offer: WaitlistOffer) -> bool:
    from apps.conversations.inbound import get_conversation

    patient = offer.waitlist.patient
    channel_name = patient.preferred_channel or "whatsapp"
    body = build_offer_body(offer)
    offer.attempts += 1
    try:
        channel = get_channel(channel_name)
        provider_id = channel.send_template(
            patient.phone_e164, body, template=build_offer_template(offer)
        )
    except Exception as exc:  # noqa: BLE001 — record and let beat retry
        offer.last_error = str(exc)[:2000]
        offer.status = (
            WaitlistOfferStatus.EXPIRED
            if offer.attempts >= _MAX_ATTEMPTS
            else WaitlistOfferStatus.PENDING
        )
        offer.save(update_fields=["attempts", "last_error", "status", "updated_at"])
        if offer.status == WaitlistOfferStatus.EXPIRED:
            _reactivate(offer.waitlist)
        logger.warning("Waitlist offer %s send failed: %s", offer.id, exc)
        return False

    now = timezone.now()
    conversation = get_conversation(offer.clinic, patient, channel_name)
    Message.objects.create(
        clinic=offer.clinic,
        conversation=conversation,
        channel=channel_name,
        direction=Direction.OUT,
        provider_message_id=provider_id,
        to_number=patient.phone_e164,
        body=body,
        message_type="template",
        category=OFFER_CATEGORY,
        cost_amount=unit_cost(channel_name, OFFER_CATEGORY),
    )
    offer.status = WaitlistOfferStatus.SENT
    offer.sent_at = now
    # Hold ends at expiry or when the slot itself starts, whichever is sooner.
    offer.offer_expires_at = min(now + OFFER_HOLD, offer.slot_starts_at)
    offer.provider_message_id = provider_id or ""
    offer.last_error = ""
    offer.save(
        update_fields=[
            "status", "sent_at", "offer_expires_at", "provider_message_id",
            "attempts", "last_error", "updated_at",
        ]
    )
    return True


@dataclass
class OfferOutcome:
    """Result of a patient tapping a waitlist offer, for the reply composer."""

    result: str  # booked | already_booked | filled | expired | not_found
    appointment: Appointment | None = None
    when: str | None = None  # clinic-local label of the offered slot


def accept_offer(clinic, patient, offer_id: int) -> OfferOutcome:
    """Book the offered slot for the tapping patient — first confirm wins.

    Delegates the race to engine.book_slot (advisory lock + live re-check): if the
    slot is already gone, the entry returns to the waitlist and the patient gets
    the graceful "just filled" outcome. Idempotent on a double tap."""
    offer = (
        WaitlistOffer.objects.filter(
            id=offer_id, clinic=clinic, waitlist__patient=patient
        )
        .select_related("waitlist", "clinic")
        .first()
    )
    if offer is None:
        return OfferOutcome(result="not_found")

    when = offer.slot_starts_at.astimezone(ZoneInfo(clinic.timezone)).strftime(
        "%a, %b %-d at %-I:%M %p"
    )
    if offer.status == WaitlistOfferStatus.ACCEPTED:
        # Double tap — re-confirm rather than scaring them with "filled".
        return OfferOutcome(result="already_booked", when=when)
    if (
        offer.status != WaitlistOfferStatus.SENT
        or (offer.offer_expires_at and offer.offer_expires_at <= timezone.now())
        # Entry already fulfilled/withdrawn (e.g. booked via an earlier offer) —
        # a stray tap must not book a second appointment.
        or offer.waitlist.status
        in (WaitlistStatus.BOOKED, WaitlistStatus.CANCELLED)
    ):
        return OfferOutcome(result="expired", when=when)

    from apps.scheduling.engine import book_slot

    booking = book_slot(clinic, patient, offer.slot_token)
    if booking.ok:
        offer.status = WaitlistOfferStatus.ACCEPTED
        offer.save(update_fields=["status", "updated_at"])
        entry = offer.waitlist
        entry.status = WaitlistStatus.BOOKED
        entry.save(update_fields=["status", "updated_at"])
        return OfferOutcome(result="booked", appointment=booking.appointment, when=when)

    # Slot re-checked as gone — someone else confirmed first (or it was taken
    # through another path). Back in line, no harm done.
    offer.status = WaitlistOfferStatus.EXPIRED
    offer.last_error = booking.error or "slot_taken"
    offer.save(update_fields=["status", "last_error", "updated_at"])
    _reactivate(offer.waitlist)
    return OfferOutcome(result="filled", when=when)


def expire_stale_offers() -> str:
    """Beat sweep: close out sent offers whose hold lapsed and pending ones whose
    slot start passed, returning their waitlist entries to active so the next
    freed slot can be offered to them again."""
    now = timezone.now()
    stale = list(
        WaitlistOffer.objects.filter(
            status=WaitlistOfferStatus.SENT, offer_expires_at__lte=now
        ).select_related("waitlist")
    ) + list(
        WaitlistOffer.objects.filter(
            status=WaitlistOfferStatus.PENDING, slot_starts_at__lte=now
        ).select_related("waitlist")
    )
    for offer in stale:
        offer.status = WaitlistOfferStatus.EXPIRED
        offer.save(update_fields=["status", "updated_at"])
        _reactivate(offer.waitlist)
    return f"expired={len(stale)}"


def _reactivate(entry: Waitlist) -> None:
    """Put an entry back in line after its offer died — unless it terminally
    resolved (booked/cancelled) or its desired window is entirely in the past."""
    if entry.status != WaitlistStatus.OFFERED:
        return
    today = timezone.now().astimezone(ZoneInfo(entry.clinic.timezone)).date()
    if entry.date_to and entry.date_to < today:
        entry.status = WaitlistStatus.EXPIRED
    else:
        entry.status = WaitlistStatus.ACTIVE
    entry.save(update_fields=["status", "updated_at"])
