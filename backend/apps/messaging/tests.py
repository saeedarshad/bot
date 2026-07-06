import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import Conversation
from apps.conversations.reply import BotReply, render_options_as_text
from apps.scheduling.models import Appointment, AppointmentStatus, Service

from .channels.whatsapp import WhatsAppChannel
from .models import (
    Direction,
    Message,
    ScheduledMessage,
    ScheduledMessageKind,
    ScheduledMessageStatus,
)
from .reminders import (
    build_interactive,
    next_send_time,
    option_id,
    parse_option_id,
    reconcile_appointment_reminders,
)
from .tasks import dispatch_due_messages


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


NY = ZoneInfo("America/New_York")


class ReminderReconcileTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", timezone="America/New_York"
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15551230000", name="Alex"
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Cleaning", duration_min=30
        )

    def _appt(self, days=3, status=AppointmentStatus.CONFIRMED):
        start = timezone.now() + timedelta(days=days)
        return Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            service=self.service,
            starts_at=start,
            ends_at=start + timedelta(minutes=30),
            status=status,
        )

    def test_booking_creates_confirmation_and_reminders(self):
        appt = self._appt(days=3)
        kinds = set(
            appt.scheduled_messages.values_list("kind", flat=True)
        )
        self.assertEqual(
            kinds,
            {
                ScheduledMessageKind.CONFIRMATION,
                ScheduledMessageKind.REMINDER_24H,
                ScheduledMessageKind.REMINDER_2H,
            },
        )

    def test_reconcile_is_idempotent(self):
        appt = self._appt(days=3)
        reconcile_appointment_reminders(appt)
        reconcile_appointment_reminders(appt)
        self.assertEqual(appt.scheduled_messages.count(), 3)

    def test_near_term_booking_skips_past_reminders(self):
        # <2h out: both 24h and 2h reminder times are already in the past.
        appt = self._appt(days=0)
        appt.starts_at = timezone.now() + timedelta(minutes=30)
        appt.save()
        kinds = set(appt.scheduled_messages.values_list("kind", flat=True))
        self.assertIn(ScheduledMessageKind.CONFIRMATION, kinds)
        self.assertNotIn(ScheduledMessageKind.REMINDER_24H, kinds)
        self.assertNotIn(ScheduledMessageKind.REMINDER_2H, kinds)

    def test_cancelling_appointment_skips_pending_reminders(self):
        appt = self._appt(days=3)
        appt.status = AppointmentStatus.CANCELLED
        appt.save()
        statuses = set(appt.scheduled_messages.values_list("status", flat=True))
        self.assertEqual(statuses, {ScheduledMessageStatus.SKIPPED})

    def test_reminders_disabled_creates_nothing(self):
        self.clinic.reminders_enabled = False
        self.clinic.save()
        appt = self._appt(days=3)
        self.assertEqual(appt.scheduled_messages.count(), 0)


class QuietHoursTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="C", slug="c", timezone="America/New_York",
            quiet_hours_start="08:00", quiet_hours_end="21:00",
        )

    def _utc(self, local_dt):
        return local_dt.replace(tzinfo=NY).astimezone(ZoneInfo("UTC"))

    def test_time_inside_window_is_unchanged(self):
        from datetime import datetime

        noon = self._utc(datetime(2026, 7, 10, 12, 0))
        self.assertEqual(next_send_time(self.clinic, noon), noon)

    def test_before_open_defers_to_window_open(self):
        from datetime import datetime

        early = self._utc(datetime(2026, 7, 10, 6, 0))
        out = next_send_time(self.clinic, early).astimezone(NY)
        self.assertEqual((out.hour, out.minute), (8, 0))
        self.assertEqual(out.date(), early.astimezone(NY).date())

    def test_after_close_defers_to_next_morning(self):
        from datetime import datetime

        late = self._utc(datetime(2026, 7, 10, 22, 30))
        out = next_send_time(self.clinic, late).astimezone(NY)
        self.assertEqual((out.hour, out.minute), (8, 0))
        self.assertEqual(out.date(), (late.astimezone(NY) + timedelta(days=1)).date())


class DispatchTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", timezone="America/New_York",
            quiet_hours_start="00:00", quiet_hours_end="23:59",
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15551230000", name="Alex",
            preferred_channel="whatsapp",
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Cleaning", duration_min=30
        )
        start = timezone.now() + timedelta(days=3)
        self.appt = Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )

    def _due_confirmation(self):
        msg = self.appt.scheduled_messages.get(
            kind=ScheduledMessageKind.CONFIRMATION
        )
        msg.scheduled_for = timezone.now() - timedelta(minutes=1)
        msg.save()
        return msg

    def test_dispatch_sends_due_message_and_logs_it(self):
        msg = self._due_confirmation()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            return_value="wamid.OUT",
        ) as send:
            dispatch_due_messages()
        send.assert_called_once()
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessageStatus.SENT)
        self.assertEqual(msg.provider_message_id, "wamid.OUT")
        self.assertTrue(
            Message.objects.filter(direction=Direction.OUT, body=msg_body(msg)).exists()
        )

    def test_dispatch_is_idempotent_on_second_run(self):
        self._due_confirmation()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            return_value="wamid.OUT",
        ) as send:
            dispatch_due_messages()
            dispatch_due_messages()
        self.assertEqual(send.call_count, 1)

    def test_future_message_is_not_sent(self):
        self.appt.scheduled_messages.update(
            scheduled_for=timezone.now() + timedelta(hours=1)
        )
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text"
        ) as send:
            dispatch_due_messages()
        send.assert_not_called()

    def test_quiet_hours_defers_instead_of_sending(self):
        from datetime import datetime

        self.clinic.quiet_hours_start = "08:00"
        self.clinic.quiet_hours_end = "21:00"
        self.clinic.save()
        # Fixed clock at 03:00 NY — outside the window — with the row due before it.
        clock = datetime(2026, 7, 10, 3, 0, tzinfo=NY).astimezone(ZoneInfo("UTC"))
        msg = self.appt.scheduled_messages.get(kind=ScheduledMessageKind.CONFIRMATION)
        msg.scheduled_for = clock - timedelta(minutes=1)
        msg.save()
        with patch("django.utils.timezone.now", return_value=clock), patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text"
        ) as send:
            dispatch_due_messages()
        send.assert_not_called()
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessageStatus.PENDING)
        self.assertEqual(msg.scheduled_for.astimezone(NY).hour, 8)

    def test_send_failure_keeps_pending_for_retry(self):
        msg = self._due_confirmation()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            side_effect=RuntimeError("network down"),
        ):
            dispatch_due_messages()
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessageStatus.PENDING)
        self.assertEqual(msg.attempts, 1)
        self.assertIn("network down", msg.last_error)

    def test_24h_reminder_dispatches_as_interactive(self):
        msg = self.appt.scheduled_messages.get(kind=ScheduledMessageKind.REMINDER_24H)
        msg.scheduled_for = timezone.now() - timedelta(minutes=1)
        msg.save()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_interactive",
            return_value="wamid.INT",
        ) as send_i, patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_text",
            return_value="wamid.T",
        ) as send_t:
            dispatch_due_messages()
        send_i.assert_called_once()
        # confirmation (also due) still goes out as text
        self.assertTrue(send_t.called)
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessageStatus.SENT)
        out = Message.objects.get(direction=Direction.OUT, message_type="interactive")
        ids = [o["id"] for o in out.interactive["options"]]
        self.assertEqual(ids, [
            f"confirm_appt_{self.appt.id}",
            f"reschedule_appt_{self.appt.id}",
            f"cancel_appt_{self.appt.id}",
        ])


class ReminderOptionTests(TestCase):
    def test_option_id_round_trips(self):
        self.assertEqual(parse_option_id(option_id("confirm", 42)), ("confirm", 42))
        self.assertEqual(parse_option_id(option_id("cancel", 7)), ("cancel", 7))

    def test_parse_ignores_unrelated_ids(self):
        self.assertEqual(parse_option_id("slot_token_abc"), (None, None))
        self.assertEqual(parse_option_id(None), (None, None))

    def test_build_interactive_only_for_24h_reminder(self):
        clinic = Clinic.objects.create(name="C", slug="c-int")
        patient = Patient.objects.create(clinic=clinic, phone_e164="+1", name="A")
        service = Service.objects.create(clinic=clinic, name="S", duration_min=30)
        start = timezone.now() + timedelta(days=2)
        appt = Appointment.objects.create(
            clinic=clinic, patient=patient, service=service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )
        r24 = appt.scheduled_messages.get(kind=ScheduledMessageKind.REMINDER_24H)
        conf = appt.scheduled_messages.get(kind=ScheduledMessageKind.CONFIRMATION)
        self.assertEqual(len(build_interactive(r24)["options"]), 3)
        self.assertIsNone(build_interactive(conf))


def msg_body(msg):
    from .reminders import build_body

    return build_body(msg)
