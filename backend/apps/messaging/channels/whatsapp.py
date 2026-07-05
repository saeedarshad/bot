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
                    parsed = self._parse_message(msg, to_number)
                    if parsed is not None:
                        out.append(parsed)
        return out

    def _parse_message(self, msg: dict, to_number: str) -> InboundMessage | None:
        mtype = msg.get("type")
        body = ""
        option_id = None
        if mtype == "text":
            body = msg.get("text", {}).get("body", "")
        elif mtype == "interactive":
            # A tapped button or list row. We feed the visible title back into the
            # engine as the patient's message (the model matches it just like typed
            # text), and keep the id so callers can map it if they want.
            interactive = msg.get("interactive", {})
            reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
            body = reply.get("title", "")
            option_id = reply.get("id")
        else:
            return None  # media, reactions, etc. are out of scope for Phase 1
        return InboundMessage(
            provider_message_id=msg.get("id", ""),
            from_number=msg.get("from", ""),
            to_number=to_number,
            body=body,
            channel=self.name,
            message_type=mtype,
            reply_option_id=option_id,
            raw=msg,
        )

    def send_text(self, to_number: str, text: str) -> str | None:
        token = settings.WHATSAPP_ACCESS_TOKEN
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        if not token or not phone_number_id:
            logger.warning("WhatsApp credentials missing; not sending (dev stub)")
            return None

        return self._post_message(
            to_number, {"type": "text", "text": {"body": text}}
        )

    def send_interactive(self, to_number: str, interactive: dict) -> str | None:
        """Render options as WhatsApp reply buttons (<=3) or a selectable list
        (4-10). Falls back to a numbered text list if credentials are missing."""
        token = settings.WHATSAPP_ACCESS_TOKEN
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        if not token or not phone_number_id:
            from apps.conversations.reply import render_options_as_text

            logger.warning("WhatsApp credentials missing; not sending (dev stub)")
            return self.send_text(to_number, render_options_as_text(interactive))

        return self._post_message(to_number, self._interactive_payload(interactive))

    def _interactive_payload(self, interactive: dict) -> dict:
        body = (interactive.get("body") or "").strip()[:1024] or "Please choose:"
        footer = interactive.get("footer")
        options = interactive.get("options", [])[:10]

        if len(options) <= 3:
            action = {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": opt.get("id", opt["title"])[:256], "title": opt["title"][:20]},
                    }
                    for opt in options
                ]
            }
            inner = {"type": "button", "body": {"text": body}, "action": action}
        else:
            rows = [
                {
                    "id": opt.get("id", opt["title"])[:200],
                    "title": opt["title"][:24],
                    **({"description": opt["description"][:72]} if opt.get("description") else {}),
                }
                for opt in options
            ]
            action = {
                "button": (interactive.get("button_label") or "Choose")[:20],
                "sections": [{"rows": rows}],
            }
            inner = {"type": "list", "body": {"text": body}, "action": action}

        if footer:
            inner["footer"] = {"text": footer[:60]}
        return {"type": "interactive", "interactive": inner}

    def _post_message(self, to_number: str, message: dict) -> str | None:
        token = settings.WHATSAPP_ACCESS_TOKEN
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        resp = requests.post(
            f"{GRAPH_API}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "to": to_number, **message},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("messages", [{}])[0].get("id")
