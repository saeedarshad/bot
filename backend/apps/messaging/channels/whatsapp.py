import hashlib
import hmac
import logging

import requests
from django.conf import settings

from .base import BaseChannel, InboundMessage

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v21.0"


class WhatsAppChannel(BaseChannel):
    name = "whatsapp"
    supports_buttons = True

    def verify_signature(self, request_body: bytes, headers: dict) -> bool:
        """Validate Meta's X-Hub-Signature-256 header (HMAC-SHA256 of the raw body
        keyed with the app secret). If no secret is configured we skip (dev only)."""
        secret = settings.WHATSAPP_APP_SECRET
        if not secret:
            logger.warning("WHATSAPP_APP_SECRET not set; skipping signature check")
            return True

        header = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256")
        if not header or not header.startswith("sha256="):
            return False

        expected = hmac.new(
            secret.encode(), request_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, header.split("sha256=", 1)[1])

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        out: list[InboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                to_number = metadata.get("phone_number_id", "")
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    out.append(
                        InboundMessage(
                            provider_message_id=msg.get("id", ""),
                            from_number=msg.get("from", ""),
                            to_number=to_number,
                            body=msg.get("text", {}).get("body", ""),
                            channel=self.name,
                            raw=msg,
                        )
                    )
        return out

    def send_text(self, to_number: str, text: str) -> str | None:
        token = settings.WHATSAPP_ACCESS_TOKEN
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        if not token or not phone_number_id:
            logger.warning("WhatsApp credentials missing; not sending (dev stub)")
            return None

        resp = requests.post(
            f"{GRAPH_API}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "text",
                "text": {"body": text},
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("messages", [{}])[0].get("id")
