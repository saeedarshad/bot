import logging

from celery import shared_task
from django.utils import timezone

from apps.conversations.inbound import (
    get_conversation,
    handle_inbound,
    resolve_clinic,
    upsert_patient,
)

from .channels import get_channel
from .models import Direction, Message

logger = logging.getLogger(__name__)


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

    reply = handle_inbound(clinic, patient, conversation, body)
    if not reply:
        return "silent"

    channel = get_channel(channel_name)
    sent_id = channel.send_text(from_number, reply)

    Message.objects.create(
        clinic=clinic,
        conversation=conversation,
        channel=channel_name,
        direction=Direction.OUT,
        provider_message_id=sent_id,
        from_number=phone_number_id,
        to_number=from_number,
        body=reply,
    )
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at"])
    return "ok"
