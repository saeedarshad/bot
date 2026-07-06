import logging

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
    ScheduledMessage,
    ScheduledMessageStatus,
)
from .reminders import build_body, build_interactive, next_send_time

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


def _send_scheduled(msg: ScheduledMessage) -> bool:
    """Send one claimed ScheduledMessage. Returns True on success. Runs inside the
    dispatch transaction so status changes commit atomically with the claim."""
    patient = msg.appointment.patient
    channel_name = patient.preferred_channel or "whatsapp"
    body = build_body(msg)
    interactive = build_interactive(msg)
    msg.attempts += 1
    try:
        channel = get_channel(channel_name)
        if interactive and channel.supports_buttons:
            provider_id = channel.send_interactive(patient.phone_e164, interactive)
        else:
            provider_id = channel.send_template(patient.phone_e164, body)
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
    Message.objects.create(
        clinic=msg.clinic,
        conversation=conversation,
        channel=channel_name,
        direction=Direction.OUT,
        provider_message_id=provider_id,
        to_number=patient.phone_e164,
        body=body,
        message_type="interactive" if (interactive and channel.supports_buttons) else "text",
        interactive=interactive if channel.supports_buttons else None,
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
