import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.conversations.inbound import (
    get_conversation,
    handle_inbound,
    resolve_clinic,
    upsert_patient,
)

from .channels import get_channel
from .models import (
    Direction,
    Message,
    MessageCategory,
    ScheduledMessage,
    ScheduledMessageKind,
    ScheduledMessageStatus,
)
from .costs import category_for_kind, unit_cost
from .reminders import build_body, build_template, next_send_time

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5


@shared_task
def process_inbound(channel_name: str, message_data: dict) -> str:
    """Phase 1: route the inbound message to a clinic, run the conversation engine,
    and send the reply. Idempotent — a retried webhook with the same provider id
    is a no-op."""
    provider_id = message_data.get("provider_message_id") or None
    if provider_id and Message.objects.filter(provider_message_id=provider_id).exists():
        logger.info("Duplicate inbound %s ignored", provider_id)
        return "duplicate"

    from_number = message_data.get("from_number", "")
    phone_number_id = message_data.get("to_number", "")  # WhatsApp phone_number_id
    body = message_data.get("body", "")

    clinic = resolve_clinic(phone_number_id)
    if clinic is None:
        logger.warning("No clinic for phone_number_id=%s; dropping message", phone_number_id)
        Message.objects.create(
            channel=channel_name,
            direction=Direction.IN,
            provider_message_id=provider_id,
            from_number=from_number,
            to_number=phone_number_id,
            body=body,
        )
        return "no_clinic"

    patient = upsert_patient(clinic, from_number, channel_name)
    conversation = get_conversation(clinic, patient, channel_name)

    Message.objects.create(
        clinic=clinic,
        conversation=conversation,
        channel=channel_name,
        direction=Direction.IN,
        provider_message_id=provider_id,
        from_number=from_number,
        to_number=phone_number_id,
        body=body,
    )
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at"])

    reply = handle_inbound(
        clinic, patient, conversation, body,
        reply_option_id=message_data.get("reply_option_id"),
    )
    if reply is None:
        return "silent"

    channel = get_channel(channel_name)
    if reply.interactive:
        sent_id = channel.send_interactive(from_number, reply.interactive)
    else:
        sent_id = channel.send_text(from_number, reply.text)

    Message.objects.create(
        clinic=clinic,
        conversation=conversation,
        channel=channel_name,
        direction=Direction.OUT,
        provider_message_id=sent_id,
        from_number=phone_number_id,
        to_number=from_number,
        body=reply.text,
        message_type="interactive" if reply.interactive else "text",
        interactive=reply.interactive,
        category=MessageCategory.SERVICE,
        cost_amount=unit_cost(channel_name, MessageCategory.SERVICE),
    )
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at"])
    return "ok"


@shared_task
def dispatch_due_messages(batch_size: int = 100) -> str:
    """Beat task: send business-initiated messages whose time has come.

    Each row is claimed under a row lock (`select_for_update(skip_locked=True)`)
    so parallel workers never grab the same one — a crashed worker leaves the row
    pending for the next run. Rows due outside TCPA quiet hours are deferred (their
    `scheduled_for` is pushed to the next open window), never dropped.
    """
    now = timezone.now()
    sent = deferred = failed = 0

    with transaction.atomic():
        rows = list(
            ScheduledMessage.objects.select_for_update(skip_locked=True)
            .filter(status=ScheduledMessageStatus.PENDING, scheduled_for__lte=now)
            .select_related("clinic", "appointment", "appointment__patient")[:batch_size]
        )
        for msg in rows:
            open_at = next_send_time(msg.clinic, now)
            if open_at > now:
                msg.scheduled_for = open_at
                msg.save(update_fields=["scheduled_for", "updated_at"])
                deferred += 1
                continue
            if _send_scheduled(msg):
                sent += 1
            else:
                failed += 1

    return f"sent={sent} deferred={deferred} failed={failed}"


@shared_task
def finalize_past_appointments() -> str:
    """Beat task: auto-complete appointments that are fully in the past and queue a
    post-visit thank-you.

    An appointment is finalized only once its whole clinic-local day has ended, so
    staff keep the full day to mark it as a no-show instead. Completing it fires the
    reconcile signal, which skips any still-pending pre-appointment reminders;
    completion never skips the thank-you (see reminders._PRE_APPOINTMENT_KINDS).
    """
    from apps.clinics.models import Clinic
    from apps.scheduling.engine import mark_completed
    from apps.scheduling.models import ACTIVE_STATUSES, Appointment

    now = timezone.now()
    completed = queued = 0

    for clinic in Clinic.objects.filter(is_active=True):
        tz = ZoneInfo(clinic.timezone)
        # Start of *today* in clinic-local time — anything ending before this
        # belonged to a prior day and is safe to finalize.
        today_start = datetime.combine(
            now.astimezone(tz).date(), time.min, tzinfo=tz
        )
        stale = Appointment.objects.filter(
            clinic=clinic,
            status__in=ACTIVE_STATUSES,
            ends_at__lt=today_start,
        ).values_list("id", flat=True)

        for appt_id in list(stale):
            result = mark_completed(clinic, appt_id)
            if not result.ok:
                continue
            completed += 1
            if clinic.reminders_enabled:
                _, created = ScheduledMessage.objects.get_or_create(
                    appointment_id=appt_id,
                    kind=ScheduledMessageKind.THANK_YOU,
                    defaults={"clinic": clinic, "scheduled_for": now},
                )
                if created:
                    queued += 1

    return f"completed={completed} thank_you_queued={queued}"


@shared_task
def send_owner_digests() -> str:
    """Beat task: send each clinic's owner a once-a-day morning digest.

    Runs hourly. A clinic is sent to only when its local clock is in the morning
    window at/after its configured `owner_digest_hour` — the window (up to noon)
    gives a failed 8am send room to retry on later hourly runs the same morning.
    `OwnerDigest`'s UNIQUE(clinic, date) claims the day so it's sent at most once.
    """
    from apps.clinics.models import Clinic

    from .digest import build_owner_digest
    from .models import OwnerDigest

    now = timezone.now()
    sent = 0

    for clinic in Clinic.objects.filter(is_active=True):
        if not (clinic.reminders_enabled and clinic.owner_phone_e164):
            continue
        local = now.astimezone(ZoneInfo(clinic.timezone))
        if not (clinic.owner_digest_hour <= local.hour < 12):
            continue

        log, created = OwnerDigest.objects.get_or_create(
            clinic=clinic, date=local.date()
        )
        if not created:
            continue  # already sent (or claimed) for today

        body = build_owner_digest(clinic, local.date())
        try:
            channel = get_channel("whatsapp")
            provider_id = channel.send_template(clinic.owner_phone_e164, body)
        except Exception as exc:  # noqa: BLE001
            # Release the day so a later run this morning can retry.
            log.delete()
            logger.warning("Owner digest for clinic %s failed: %s", clinic.id, exc)
            continue

        log.body = body
        log.provider_message_id = provider_id or ""
        log.sent_at = now
        log.save(update_fields=["body", "provider_message_id", "sent_at"])
        sent += 1

    return f"digests_sent={sent}"


def _send_scheduled(msg: ScheduledMessage) -> bool:
    """Send one claimed ScheduledMessage. Returns True on success. Runs inside the
    dispatch transaction so status changes commit atomically with the claim."""
    patient = msg.appointment.patient
    channel_name = patient.preferred_channel or "whatsapp"
    body = build_body(msg)
    template = build_template(msg)
    msg.attempts += 1
    try:
        channel = get_channel(channel_name)
        # Reminders are business-initiated (outside the 24h window), so they must
        # go through an approved template. `body` is the plain-text fallback for
        # channels/creds without template support (see channels/base.py).
        provider_id = channel.send_template(
            patient.phone_e164, body, template=template
        )
    except Exception as exc:  # noqa: BLE001 — record and let beat retry
        msg.last_error = str(exc)[:2000]
        msg.status = (
            ScheduledMessageStatus.FAILED
            if msg.attempts >= _MAX_ATTEMPTS
            else ScheduledMessageStatus.PENDING
        )
        msg.save(update_fields=["attempts", "last_error", "status", "updated_at"])
        logger.warning("Reminder %s send failed: %s", msg.id, exc)
        return False

    conversation = get_conversation(msg.clinic, patient, channel_name)
    category = category_for_kind(msg.kind)
    Message.objects.create(
        clinic=msg.clinic,
        conversation=conversation,
        channel=channel_name,
        direction=Direction.OUT,
        provider_message_id=provider_id,
        to_number=patient.phone_e164,
        body=body,
        message_type="template" if template else "text",
        interactive=None,
        category=category,
        cost_amount=unit_cost(channel_name, category),
    )
    msg.status = ScheduledMessageStatus.SENT
    msg.sent_at = timezone.now()
    msg.provider_message_id = provider_id or ""
    msg.last_error = ""
    msg.save(
        update_fields=[
            "status", "sent_at", "provider_message_id", "attempts",
            "last_error", "updated_at",
        ]
    )
    return True
