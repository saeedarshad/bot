from .base import BaseChannel, InboundMessage
from .whatsapp import WhatsAppChannel

REGISTRY = {WhatsAppChannel.name: WhatsAppChannel()}


def get_channel(name: str) -> BaseChannel:
    return REGISTRY[name]


__all__ = ("BaseChannel", "InboundMessage", "WhatsAppChannel", "get_channel", "REGISTRY")
