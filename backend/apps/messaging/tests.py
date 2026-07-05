import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import Conversation
from apps.conversations.reply import BotReply, render_options_as_text

from .channels.whatsapp import WhatsAppChannel
from .models import Direction, Message


def _wa_envelope(message: dict):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "PNID123"},
                            "messages": [message],
                        }
                    }
                ]
            }
        ]
    }


def _wa_payload(text="hello", msg_id="wamid.TEST1", sender="15551230000"):
    return _wa_envelope(
        {"id": msg_id, "from": sender, "type": "text", "text": {"body": text}}
    )


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
class InboundPipelineTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", whatsapp_phone_number_id="PNID123"
        )

    _DEFAULT = "Sure, how can I help?"

    def _post(self, payload, reply=_DEFAULT):
        if isinstance(reply, str):
            reply = BotReply(text=reply)
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            return_value="wamid.OUT",
        ) as send, patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_interactive",
            return_value="wamid.OUTI",
        ) as send_i, patch(
            "apps.messaging.tasks.handle_inbound", return_value=reply
        ) as handler:
            resp = Client().post(
                "/webhooks/whatsapp",
                data=json.dumps(payload),
                content_type="application/json",
            )
        return resp, send, send_i, handler

    def test_inbound_creates_patient_conversation_and_reply(self):
        resp, send, _, _ = self._post(_wa_payload(text="hi there"))
        self.assertEqual(resp.status_code, 200)

        patient = Patient.objects.get(clinic=self.clinic)
        self.assertEqual(patient.phone_e164, "+15551230000")
        self.assertIsNotNone(patient.sms_consent_at)

        conv = Conversation.objects.get(clinic=self.clinic, patient=patient)
        inbound = Message.objects.get(direction=Direction.IN)
        self.assertEqual(inbound.body, "hi there")
        self.assertEqual(inbound.conversation_id, conv.id)

        outbound = Message.objects.get(direction=Direction.OUT)
        self.assertEqual(outbound.body, "Sure, how can I help?")
        send.assert_called_once_with("15551230000", "Sure, how can I help?")

    def test_interactive_reply_uses_interactive_send(self):
        interactive = {
            "body": "Pick a time",
            "options": [{"id": "9:00 AM", "title": "9:00 AM"}],
            "button_label": None,
            "footer": None,
        }
        resp, send, send_i, _ = self._post(
            _wa_payload(), reply=BotReply(text="Pick a time", interactive=interactive)
        )
        self.assertEqual(resp.status_code, 200)
        send.assert_not_called()
        send_i.assert_called_once_with("15551230000", interactive)
        outbound = Message.objects.get(direction=Direction.OUT)
        self.assertEqual(outbound.message_type, "interactive")
        self.assertEqual(outbound.interactive["options"][0]["title"], "9:00 AM")

    def test_silent_reply_sends_nothing(self):
        resp, send, send_i, _ = self._post(_wa_payload(), reply=None)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Message.objects.filter(direction=Direction.OUT).exists())
        send.assert_not_called()
        send_i.assert_not_called()

    def test_duplicate_webhook_is_idempotent(self):
        self._post(_wa_payload(msg_id="wamid.DUP"))
        self._post(_wa_payload(msg_id="wamid.DUP"))
        self.assertEqual(Message.objects.filter(direction=Direction.IN).count(), 1)

    def test_no_clinic_match_drops_message(self):
        Clinic.objects.all().delete()
        Clinic.objects.create(name="A", slug="a", whatsapp_phone_number_id="OTHER1")
        Clinic.objects.create(name="B", slug="b", whatsapp_phone_number_id="OTHER2")
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text"
        ) as send:
            Client().post(
                "/webhooks/whatsapp",
                data=json.dumps(_wa_payload()),
                content_type="application/json",
            )
        self.assertFalse(Message.objects.filter(direction=Direction.OUT).exists())
        send.assert_not_called()


class WhatsAppInteractiveTests(TestCase):
    def setUp(self):
        self.channel = WhatsAppChannel()

    def _opts(self, n):
        return {
            "body": "Choose",
            "options": [{"id": f"t{i}", "title": f"Option {i}"} for i in range(n)],
            "button_label": "Pick",
            "footer": "footer note",
        }

    def test_three_or_fewer_options_render_as_buttons(self):
        payload = self.channel._interactive_payload(self._opts(3))
        inner = payload["interactive"]
        self.assertEqual(inner["type"], "button")
        self.assertEqual(len(inner["action"]["buttons"]), 3)
        self.assertEqual(inner["action"]["buttons"][0]["reply"]["id"], "t0")
        self.assertEqual(inner["footer"]["text"], "footer note")

    def test_more_than_three_options_render_as_list(self):
        payload = self.channel._interactive_payload(self._opts(5))
        inner = payload["interactive"]
        self.assertEqual(inner["type"], "list")
        rows = inner["action"]["sections"][0]["rows"]
        self.assertEqual(len(rows), 5)
        self.assertEqual(inner["action"]["button"], "Pick")

    def test_button_title_truncated_to_limit(self):
        opts = {"body": "b", "options": [{"id": "x", "title": "A" * 40}]}
        payload = self.channel._interactive_payload(opts)
        title = payload["interactive"]["action"]["buttons"][0]["reply"]["title"]
        self.assertEqual(len(title), 20)

    def test_parse_button_tap_uses_title_as_body(self):
        msg = {
            "id": "wamid.TAP",
            "from": "15551230000",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "9:00 AM", "title": "9:00 AM"},
            },
        }
        [parsed] = self.channel.parse_inbound(_wa_envelope(msg))
        self.assertEqual(parsed.body, "9:00 AM")
        self.assertEqual(parsed.reply_option_id, "9:00 AM")
        self.assertEqual(parsed.message_type, "interactive")

    def test_parse_list_tap_uses_title_as_body(self):
        msg = {
            "id": "wamid.TAP2",
            "from": "15551230000",
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "tok123", "title": "Cleaning", "description": "30 min"},
            },
        }
        [parsed] = self.channel.parse_inbound(_wa_envelope(msg))
        self.assertEqual(parsed.body, "Cleaning")
        self.assertEqual(parsed.reply_option_id, "tok123")

    def test_text_fallback_renders_numbered_list(self):
        text = render_options_as_text(self._opts(2))
        self.assertIn("Choose", text)
        self.assertIn("1. Option 0", text)
        self.assertIn("2. Option 1", text)
