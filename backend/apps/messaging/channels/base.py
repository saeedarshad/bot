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
    # For taps on interactive messages: the id of the chosen option (echoes the
    # option we sent). Plain text messages leave this None.
    reply_option_id: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class StatusUpdate:
    """A delivery-status callback for a previously-sent outbound message. Providers
    report the message's lifecycle (sent/delivered/read) and any failure out of
    band, keyed by the provider message id we recorded at send time."""

    provider_message_id: str
    status: str  # sent | delivered | read | failed
    error: str = ""


class BaseChannel:
    """Interface every channel adapter implements. The core talks only to this."""

    name: str = ""
    supports_buttons: bool = False

    def verify_signature(self, request_body: bytes, headers: dict) -> bool:
        raise NotImplementedError

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        raise NotImplementedError

    def parse_statuses(self, payload: dict) -> list[StatusUpdate]:
        """Extract delivery-status callbacks from a provider webhook. Channels
        without delivery receipts return an empty list."""
        return []

    def send_text(self, to_number: str, text: str) -> str | None:
        """Send a plain-text message. Returns the provider message id, or None."""
        raise NotImplementedError

    def send_interactive(self, to_number: str, interactive: dict) -> str | None:
        """Send tappable options. Channels that can't render them fall back to a
        numbered text list so every channel still works over plain text."""
        from apps.conversations.reply import render_options_as_text

        return self.send_text(to_number, render_options_as_text(interactive))

    def send_template(
        self, to_number: str, fallback_text: str, template: dict | None = None
    ) -> str | None:
        """Send a business-initiated (outside-24h-window) message. Real WhatsApp
        requires a Meta-approved template (`template` spec from
        reminders.build_template); channels without template support — and any
        send with no spec — fall back to plain text so every channel still works."""
        return self.send_text(to_number, fallback_text)
