import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from .models import Direction, Message


def _wa_payload(text="hello", msg_id="wamid.TEST1", sender="15551230000"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "PNID123"},
                            "messages": [
                                {
                                    "id": msg_id,
                                    "from": sender,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


@override_settings(WHATSAPP_VERIFY_TOKEN="verify-me", WHATSAPP_APP_SECRET="")
class WebhookVerificationTests(TestCase):
    def test_get_handshake_ok(self):
        resp = self.client.get(
            "/webhooks/whatsapp",
            {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"42")

    def test_get_handshake_wrong_token(self):
        resp = self.client.get(
            "/webhooks/whatsapp",
            {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
        )
        self.assertEqual(resp.status_code, 403)


@override_settings(WHATSAPP_APP_SECRET="s3cr3t")
class SignatureTests(TestCase):
    def test_bad_signature_rejected(self):
        body = json.dumps(_wa_payload()).encode()
        resp = self.client.post(
            "/webhooks/whatsapp",
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
        )
        self.assertEqual(resp.status_code, 403)

    def test_valid_signature_accepted(self):
        body = json.dumps(_wa_payload()).encode()
        sig = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            return_value="wamid.OUT",
        ):
            resp = self.client.post(
                "/webhooks/whatsapp",
                data=body,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=f"sha256={sig}",
            )
        self.assertEqual(resp.status_code, 200)


@override_settings(WHATSAPP_APP_SECRET="")
class EchoRoundTripTests(TestCase):
    def _post(self, payload):
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            return_value="wamid.OUT",
        ) as send:
            resp = Client().post(
                "/webhooks/whatsapp",
                data=json.dumps(payload),
                content_type="application/json",
            )
        return resp, send

    def test_echo_creates_in_and_out_messages(self):
        resp, send = self._post(_wa_payload(text="hi there"))
        self.assertEqual(resp.status_code, 200)

        inbound = Message.objects.get(direction=Direction.IN)
        self.assertEqual(inbound.body, "hi there")
        self.assertEqual(inbound.from_number, "15551230000")

        outbound = Message.objects.get(direction=Direction.OUT)
        self.assertEqual(outbound.body, "Received: hi there")
        send.assert_called_once_with("15551230000", "Received: hi there")

    def test_duplicate_webhook_is_idempotent(self):
        self._post(_wa_payload(msg_id="wamid.DUP"))
        self._post(_wa_payload(msg_id="wamid.DUP"))
        self.assertEqual(Message.objects.filter(direction=Direction.IN).count(), 1)
