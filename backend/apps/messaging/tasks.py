import logging

from celery import shared_task

from .channels import get_channel
from .models import Direction, Message

logger = logging.getLogger(__name__)


@shared_task
def process_inbound(channel_name: str, message_data: dict) -> str:
    """Phase 0 behavior: log the inbound message and echo it back.
    Idempotent — a retried webhook with the same provider id is a no-op."""
    provider_id = message_data.get("provider_message_id") or None

    if provider_id and Message.objects.filter(provider_message_id=provider_id).exists():
        logger.info("Duplicate inbound %s ignored", provider_id)
        return "duplicate"

    Message.objects.create(
        channel=channel_name,
        direction=Direction.IN,
        provider_message_id=provider_id,
        from_number=message_data.get("from_number", ""),
        to_number=message_data.get("to_number", ""),
        body=message_data.get("body", ""),
    )

    reply = f"Received: {message_data.get('body', '')}"
    channel = get_channel(channel_name)
    sent_id = channel.send_text(message_data.get("from_number", ""), reply)

    Message.objects.create(
        channel=channel_name,
        direction=Direction.OUT,
        provider_message_id=sent_id,
        from_number=message_data.get("to_number", ""),
        to_number=message_data.get("from_number", ""),
        body=reply,
    )
    return "ok"
