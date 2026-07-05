from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    """Normalized inbound message, channel-agnostic. Every adapter parses its
    provider payload down to this shape so the core never sees provider quirks."""

    provider_message_id: str
    from_number: str
    to_number: str
    body: str
    channel: str
    message_type: str = "text"
    raw: dict = field(default_factory=dict)


class BaseChannel:
    """Interface every channel adapter implements. The core talks only to this."""

    name: str = ""
    supports_buttons: bool = False

    def verify_signature(self, request_body: bytes, headers: dict) -> bool:
        raise NotImplementedError

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        raise NotImplementedError

    def send_text(self, to_number: str, text: str) -> str | None:
        """Send a plain-text message. Returns the provider message id, or None."""
        raise NotImplementedError
