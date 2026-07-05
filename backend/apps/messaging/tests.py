import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import Conversation

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
class InboundPipelineTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", whatsapp_phone_number_id="PNID123"
        )

    def _post(self, payload, reply="Sure, how can I help?"):
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            return_value="wamid.OUT",
        ) as send, patch(
            "apps.messaging.tasks.handle_inbound", return_value=reply
        ) as handler:
            resp = Client().post(
                "/webhooks/whatsapp",
                data=json.dumps(payload),
                content_type="application/json",
            )
        return resp, send, handler

    def test_inbound_creates_patient_conversation_and_reply(self):
        resp, send, _ = self._post(_wa_payload(text="hi there"))
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

    def test_silent_reply_sends_nothing(self):
        resp, send, _ = self._post(_wa_payload(), reply=None)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Message.objects.filter(direction=Direction.OUT).exists())
        send.assert_not_called()

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
