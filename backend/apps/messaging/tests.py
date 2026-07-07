import hashlib
import hmac
import json
from datetime import datetime, timedelta
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
    build_template,
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

    def test_parse_template_button_tap_uses_payload(self):
        # A tap on a template quick-reply button: the routing id travels in
        # `payload`, the visible label in `text`, and the type is "button".
        msg = {
            "id": "wamid.BTN",
            "from": "15551230000",
            "type": "button",
            "button": {"text": "Confirm", "payload": "confirm_appt_42"},
        }
        [parsed] = self.channel.parse_inbound(_wa_envelope(msg))
        self.assertEqual(parsed.body, "Confirm")
        self.assertEqual(parsed.reply_option_id, "confirm_appt_42")
        self.assertEqual(parsed.message_type, "button")

    def test_template_payload_maps_body_params_in_order(self):
        spec = {
            "name": "appointment_confirmation",
            "language": "en_US",
            "body_params": ["Alex", "Bright Smiles", "Tue, Jul 7 at 12:15 PM"],
        }
        payload = self.channel._template_payload(spec)
        self.assertEqual(payload["type"], "template")
        tpl = payload["template"]
        self.assertEqual(tpl["name"], "appointment_confirmation")
        self.assertEqual(tpl["language"], {"code": "en_US"})
        body = tpl["components"][0]
        self.assertEqual(body["type"], "body")
        self.assertEqual(
            [p["text"] for p in body["parameters"]],
            ["Alex", "Bright Smiles", "Tue, Jul 7 at 12:15 PM"],
        )

    def test_template_payload_adds_button_components(self):
        spec = {
            "name": "appointment_reminder_24h",
            "language": "en_US",
            "body_params": ["Alex", "Bright Smiles", "tomorrow"],
            "buttons": [
                {"index": 0, "payload": "confirm_appt_5"},
                {"index": 1, "payload": "reschedule_appt_5"},
                {"index": 2, "payload": "cancel_appt_5"},
            ],
        }
        payload = self.channel._template_payload(spec)
        buttons = [c for c in payload["template"]["components"] if c["type"] == "button"]
        self.assertEqual(len(buttons), 3)
        self.assertEqual(buttons[0]["sub_type"], "quick_reply")
        self.assertEqual(buttons[0]["index"], "0")
        self.assertEqual(buttons[0]["parameters"][0]["payload"], "confirm_appt_5")

    def test_send_template_falls_back_to_text_without_spec(self):
        with patch.object(self.channel, "send_text", return_value="wamid.FB") as send:
            out = self.channel.send_template("15551230000", "plain body", template=None)
        self.assertEqual(out, "wamid.FB")
        send.assert_called_once_with("15551230000", "plain body")

    @override_settings(WHATSAPP_ACCESS_TOKEN="", WHATSAPP_PHONE_NUMBER_ID="")
    def test_send_template_falls_back_when_credentials_missing(self):
        spec = {"name": "appointment_confirmation", "language": "en_US", "body_params": ["A"]}
        with patch.object(self.channel, "send_text", return_value="wamid.FB") as send:
            self.channel.send_template("15551230000", "plain body", template=spec)
        send.assert_called_once_with("15551230000", "plain body")

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

    def test_defer_across_spring_forward_lands_at_window_open(self):
        # Spring-forward night (2026-03-08, 02:00->03:00). A message due at 05:00
        # local still defers to the unambiguous 08:00 open in the new offset (EDT).
        early = self._utc(datetime(2026, 3, 8, 5, 0))
        out = next_send_time(self.clinic, early).astimezone(NY)
        self.assertEqual((out.hour, out.minute), (8, 0))
        self.assertEqual(out.utcoffset(), timedelta(hours=-4))  # EDT after the jump

    def test_defer_across_fall_back_lands_at_window_open(self):
        # Fall-back night (2026-11-01, 02:00->01:00). Defer at 06:00 local -> 08:00.
        early = self._utc(datetime(2026, 11, 1, 6, 0))
        out = next_send_time(self.clinic, early).astimezone(NY)
        self.assertEqual((out.hour, out.minute), (8, 0))
        self.assertEqual(out.utcoffset(), timedelta(hours=-5))  # EST after the jump


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
            "apps.messaging.channels.whatsapp.WhatsAppChannel._post_message",
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
            "apps.messaging.channels.whatsapp.WhatsAppChannel._post_message",
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
            "apps.messaging.channels.whatsapp.WhatsAppChannel._post_message",
            side_effect=RuntimeError("network down"),
        ):
            dispatch_due_messages()
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessageStatus.PENDING)
        self.assertEqual(msg.attempts, 1)
        self.assertIn("network down", msg.last_error)

    def test_24h_reminder_dispatches_with_button_template(self):
        # Only the 24h reminder is due (confirmation pushed out) so the single
        # send's provider id can't collide on the unique Message constraint.
        self.appt.scheduled_messages.update(
            scheduled_for=timezone.now() + timedelta(hours=1)
        )
        msg = self.appt.scheduled_messages.get(kind=ScheduledMessageKind.REMINDER_24H)
        msg.scheduled_for = timezone.now() - timedelta(minutes=1)
        msg.save()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_template",
            return_value="wamid.TPL",
        ) as send_tpl:
            dispatch_due_messages()
        # The 24h reminder goes out as its approved template with the three
        # quick-reply button payloads that carry the appointment id.
        template = None
        for call in send_tpl.call_args_list:
            spec = call.kwargs.get("template")
            if spec and spec["name"] == "appointment_reminder_24h":
                template = spec
        self.assertIsNotNone(template)
        payloads = [b["payload"] for b in template["buttons"]]
        self.assertEqual(payloads, [
            f"confirm_appt_{self.appt.id}",
            f"reschedule_appt_{self.appt.id}",
            f"cancel_appt_{self.appt.id}",
        ])
        msg.refresh_from_db()
        self.assertEqual(msg.status, ScheduledMessageStatus.SENT)


class ReminderOptionTests(TestCase):
    def test_option_id_round_trips(self):
        self.assertEqual(parse_option_id(option_id("confirm", 42)), ("confirm", 42))
        self.assertEqual(parse_option_id(option_id("cancel", 7)), ("cancel", 7))

    def test_parse_ignores_unrelated_ids(self):
        self.assertEqual(parse_option_id("slot_token_abc"), (None, None))
        self.assertEqual(parse_option_id(None), (None, None))

    def _appt(self, name="Alex Kim"):
        clinic = Clinic.objects.create(name="Bright Smiles", slug="c-tpl")
        patient = Patient.objects.create(clinic=clinic, phone_e164="+1", name=name)
        service = Service.objects.create(clinic=clinic, name="S", duration_min=30)
        start = timezone.now() + timedelta(days=2)
        return Appointment.objects.create(
            clinic=clinic, patient=patient, service=service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )

    def test_build_template_confirmation_params(self):
        appt = self._appt()
        conf = appt.scheduled_messages.get(kind=ScheduledMessageKind.CONFIRMATION)
        spec = build_template(conf)
        self.assertEqual(spec["name"], "appointment_confirmation")
        self.assertEqual(spec["language"], "en_US")
        # first name, clinic, when — three body params, no buttons.
        self.assertEqual(spec["body_params"][0], "Alex")
        self.assertEqual(spec["body_params"][1], "Bright Smiles")
        self.assertEqual(len(spec["body_params"]), 3)
        self.assertNotIn("buttons", spec)

    def test_build_template_24h_has_button_payloads(self):
        appt = self._appt()
        r24 = appt.scheduled_messages.get(kind=ScheduledMessageKind.REMINDER_24H)
        spec = build_template(r24)
        self.assertEqual(spec["name"], "appointment_reminder_24h")
        self.assertEqual(
            [b["payload"] for b in spec["buttons"]],
            [f"confirm_appt_{appt.id}", f"reschedule_appt_{appt.id}", f"cancel_appt_{appt.id}"],
        )

    def test_build_template_thank_you_two_params(self):
        appt = self._appt()
        ty = ScheduledMessage.objects.create(
            appointment=appt, clinic=appt.clinic,
            kind=ScheduledMessageKind.THANK_YOU, scheduled_for=timezone.now(),
        )
        spec = build_template(ty)
        self.assertEqual(spec["name"], "appointment_thank_you")
        self.assertEqual(len(spec["body_params"]), 2)

    def test_build_template_blank_name_falls_back_to_there(self):
        appt = self._appt(name="")
        conf = appt.scheduled_messages.get(kind=ScheduledMessageKind.CONFIRMATION)
        # Meta rejects empty params, so a nameless patient becomes "there".
        self.assertEqual(build_template(conf)["body_params"][0], "there")


class FinalizePastAppointmentsTests(TestCase):
    """finalize_past_appointments auto-completes fully-past appointments and queues
    a post-visit thank-you, leaving today's appointments alone."""

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

    # A fixed clinic-local clock so the "which day" boundary is deterministic.
    CLOCK = datetime(2026, 7, 10, 15, 0, tzinfo=NY)

    def _appt_ending(self, ends_ny, status=AppointmentStatus.CONFIRMED):
        starts = ends_ny - timedelta(minutes=30)
        return Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=starts.astimezone(ZoneInfo("UTC")),
            ends_at=ends_ny.astimezone(ZoneInfo("UTC")),
            status=status,
        )

    def _run(self):
        from .tasks import finalize_past_appointments

        with patch("django.utils.timezone.now", return_value=self.CLOCK.astimezone(ZoneInfo("UTC"))):
            return finalize_past_appointments()

    def test_prior_day_appointment_is_completed_and_thanked(self):
        appt = self._appt_ending(datetime(2026, 7, 9, 12, 0, tzinfo=NY))
        self._run()
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.COMPLETED)
        self.assertTrue(
            appt.scheduled_messages.filter(
                kind=ScheduledMessageKind.THANK_YOU,
                status=ScheduledMessageStatus.PENDING,
            ).exists()
        )

    def test_todays_appointment_is_left_alone(self):
        # Ended earlier today — staff keep the rest of the day to mark no-show.
        appt = self._appt_ending(datetime(2026, 7, 10, 9, 0, tzinfo=NY))
        self._run()
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)
        self.assertFalse(
            appt.scheduled_messages.filter(kind=ScheduledMessageKind.THANK_YOU).exists()
        )

    def test_terminal_appointment_is_not_re_thanked(self):
        appt = self._appt_ending(
            datetime(2026, 7, 9, 12, 0, tzinfo=NY), status=AppointmentStatus.CANCELLED
        )
        self._run()
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)
        self.assertFalse(
            appt.scheduled_messages.filter(kind=ScheduledMessageKind.THANK_YOU).exists()
        )

    def test_thank_you_survives_later_reconcile(self):
        # Completing drops the appt out of ACTIVE_STATUSES; a reconcile must not
        # skip the thank-you the way it skips pre-appointment reminders.
        appt = self._appt_ending(datetime(2026, 7, 9, 12, 0, tzinfo=NY))
        self._run()
        reconcile_appointment_reminders(appt)
        ty = appt.scheduled_messages.get(kind=ScheduledMessageKind.THANK_YOU)
        self.assertEqual(ty.status, ScheduledMessageStatus.PENDING)

    def test_reminders_disabled_completes_without_thank_you(self):
        self.clinic.reminders_enabled = False
        self.clinic.save()
        appt = self._appt_ending(datetime(2026, 7, 9, 12, 0, tzinfo=NY))
        self._run()
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.COMPLETED)
        self.assertFalse(
            appt.scheduled_messages.filter(kind=ScheduledMessageKind.THANK_YOU).exists()
        )

    def test_second_run_is_idempotent(self):
        appt = self._appt_ending(datetime(2026, 7, 9, 12, 0, tzinfo=NY))
        self._run()
        self._run()
        self.assertEqual(
            appt.scheduled_messages.filter(kind=ScheduledMessageKind.THANK_YOU).count(),
            1,
        )


class OwnerDigestTests(TestCase):
    """send_owner_digests sends the clinic owner one morning summary per day."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", timezone="America/New_York",
            owner_phone_e164="+15559990000", owner_digest_hour=8,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15551230000", name="Alex Kim"
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Cleaning", duration_min=30
        )

    # 8:30 AM NY — inside the morning send window.
    MORNING = datetime(2026, 7, 10, 8, 30, tzinfo=NY)

    def _appt_today(self, hour=10, minute=0, confirmed=False):
        start = datetime(2026, 7, 10, hour, minute, tzinfo=NY).astimezone(ZoneInfo("UTC"))
        appt = Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
            patient_confirmed_at=timezone.now() if confirmed else None,
        )
        return appt

    def _run(self, clock=None):
        from .tasks import send_owner_digests

        clock = (clock or self.MORNING).astimezone(ZoneInfo("UTC"))
        with patch("django.utils.timezone.now", return_value=clock), patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_template",
            return_value="wamid.DIG",
        ) as send:
            send_owner_digests()
        return send

    def test_digest_sent_once_in_morning_window(self):
        self._appt_today(hour=10)
        send = self._run()
        send.assert_called_once()
        to_number, body = send.call_args[0][:2]
        self.assertEqual(to_number, "+15559990000")
        self.assertIn("1 appointment", body)
        from .models import OwnerDigest

        log = OwnerDigest.objects.get(clinic=self.clinic)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(log.date.isoformat(), "2026-07-10")

    def test_second_run_same_day_is_idempotent(self):
        self._appt_today(hour=10)
        self._run()
        send2 = self._run(clock=datetime(2026, 7, 10, 9, 30, tzinfo=NY))
        send2.assert_not_called()

    def test_outside_morning_window_sends_nothing(self):
        self._appt_today(hour=10)
        send = self._run(clock=datetime(2026, 7, 10, 14, 0, tzinfo=NY))  # afternoon
        send.assert_not_called()
        from .models import OwnerDigest

        self.assertFalse(OwnerDigest.objects.exists())

    def test_before_configured_hour_sends_nothing(self):
        self.clinic.owner_digest_hour = 9
        self.clinic.save()
        self._appt_today(hour=10)
        send = self._run(clock=datetime(2026, 7, 10, 8, 30, tzinfo=NY))
        send.assert_not_called()

    def test_no_owner_phone_skips_clinic(self):
        self.clinic.owner_phone_e164 = ""
        self.clinic.save()
        self._appt_today(hour=10)
        send = self._run()
        send.assert_not_called()

    def test_at_risk_count_surfaced(self):
        self._appt_today(hour=10)  # unconfirmed
        appt = self._appt_today(hour=11)
        r24 = appt.scheduled_messages.get(kind=ScheduledMessageKind.REMINDER_24H)
        r24.status = ScheduledMessageStatus.SENT
        r24.save()
        send = self._run()
        body = send.call_args[0][1]
        self.assertIn("1 still unconfirmed", body)

    def test_send_failure_releases_day_for_retry(self):
        from .models import OwnerDigest
        from .tasks import send_owner_digests

        self._appt_today(hour=10)
        clock = self.MORNING.astimezone(ZoneInfo("UTC"))
        with patch("django.utils.timezone.now", return_value=clock), patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_template",
            side_effect=RuntimeError("network down"),
        ):
            send_owner_digests()
        # The claim row was released so a later morning run can retry.
        self.assertFalse(OwnerDigest.objects.exists())

    def test_empty_day_reports_no_appointments(self):
        send = self._run()
        send.assert_called_once()
        self.assertIn("No appointments", send.call_args[0][1])

    def test_digest_sends_approved_template_spec(self):
        self._appt_today(hour=10)
        send = self._run()
        template = send.call_args[1]["template"]
        self.assertEqual(template["name"], "owner_daily_digest")
        self.assertEqual(template["language"], "en_US")
        # Five always-present params: clinic, date, count, first arrival, note.
        self.assertEqual(len(template["body_params"]), 5)
        self.assertEqual(template["body_params"][0], "Bright Smiles")
        self.assertEqual(template["body_params"][2], "1")


class CostTrackerTests(TestCase):
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

    def test_unit_cost_reads_rate_and_defaults_to_zero(self):
        from decimal import Decimal

        from .costs import unit_cost
        from .models import MessageCategory, MessageRate

        self.assertEqual(
            unit_cost("whatsapp", MessageCategory.UTILITY), Decimal("0.0400")
        )
        MessageRate.objects.filter(category=MessageCategory.MARKETING).delete()
        self.assertEqual(
            unit_cost("whatsapp", MessageCategory.MARKETING), Decimal("0")
        )

    def test_dispatched_reminder_snapshots_utility_cost(self):
        from decimal import Decimal

        from .models import MessageCategory

        msg = self.appt.scheduled_messages.get(kind=ScheduledMessageKind.CONFIRMATION)
        msg.scheduled_for = timezone.now() - timedelta(minutes=1)
        msg.save()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel._post_message",
            return_value="wamid.OUT",
        ):
            dispatch_due_messages()
        out = Message.objects.get(direction=Direction.OUT)
        self.assertEqual(out.category, MessageCategory.UTILITY)
        self.assertEqual(out.cost_amount, Decimal("0.0400"))


def _wa_status_envelope(status: dict):
    return {
        "entry": [
            {"changes": [{"value": {"messaging_product": "whatsapp", "statuses": [status]}}]}
        ]
    }


@override_settings(WHATSAPP_APP_SECRET="")
class DeliveryStatusTests(TestCase):
    """Meta delivery receipts (sent/delivered/read/failed) update the outbound
    Message they reference, keyed by provider_message_id."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", timezone="America/New_York"
        )
        self.msg = Message.objects.create(
            clinic=self.clinic, channel="whatsapp", direction=Direction.OUT,
            provider_message_id="wamid.OUT1", to_number="+15551230000", body="hi",
        )

    def _run(self, status, error=""):
        from .tasks import process_status

        return process_status(
            {"provider_message_id": "wamid.OUT1", "status": status, "error": error}
        )

    def test_parse_statuses_extracts_status_and_error(self):
        payload = _wa_status_envelope(
            {
                "id": "wamid.OUT1",
                "status": "failed",
                "errors": [{"code": 131026, "title": "Message undeliverable"}],
            }
        )
        updates = WhatsAppChannel().parse_statuses(payload)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].provider_message_id, "wamid.OUT1")
        self.assertEqual(updates[0].status, "failed")
        self.assertEqual(updates[0].error, "Message undeliverable")

    def test_status_advances_forward(self):
        self._run("sent")
        self._run("delivered")
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.delivery_status, "delivered")

    def test_out_of_order_status_does_not_downgrade(self):
        self._run("read")
        self._run("delivered")  # arrives late
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.delivery_status, "read")

    def test_failed_records_error(self):
        self._run("failed", error="Message undeliverable")
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.delivery_status, "failed")
        self.assertEqual(self.msg.delivery_error, "Message undeliverable")

    def test_unknown_message_id_is_ignored(self):
        from .tasks import process_status

        self.assertEqual(
            process_status({"provider_message_id": "wamid.NOPE", "status": "read"}),
            "unknown",
        )

    def test_webhook_dispatches_status_updates(self):
        from unittest.mock import patch as _patch

        body = json.dumps(
            _wa_status_envelope({"id": "wamid.OUT1", "status": "delivered"})
        ).encode()
        with _patch("apps.messaging.views.process_status.delay") as delay:
            resp = self.client.post(
                "/webhooks/whatsapp", data=body, content_type="application/json"
            )
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once()
        self.assertEqual(delay.call_args[0][0]["status"], "delivered")


def msg_body(msg):
    from .reminders import build_body

    return build_body(msg)


class WaitlistOfferTests(TestCase):
    """Cancellation → freed-slot offers to the oldest matching waitlist entries,
    first-confirm-wins on tap, hold expiry back to active."""

    def setUp(self):
        from apps.scheduling.models import ScheduleRule

        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", timezone="America/New_York",
            quiet_hours_start="00:00", quiet_hours_end="23:59",
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Cleaning", duration_min=30
        )
        # Open every day so any future slot is inside working hours.
        for wd in range(7):
            ScheduleRule.objects.create(
                clinic=self.clinic, weekday=wd, start_time="09:00", end_time="17:00"
            )
        self.canceller = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15550001111", name="Cass"
        )
        # A real bookable slot ~3 days out, held by the canceller.
        from apps.scheduling.engine import available_slots

        target = (timezone.now().astimezone(NY) + timedelta(days=3)).date()
        self.slot = available_slots(
            self.clinic, self.service, start_date=target, end_date=target, limit=1
        )[0]
        self.appt = Appointment.objects.create(
            clinic=self.clinic, patient=self.canceller, service=self.service,
            starts_at=self.slot.start, ends_at=self.slot.end,
        )

    def _patient(self, n, name):
        return Patient.objects.create(
            clinic=self.clinic, phone_e164=f"+1555000{n:04d}", name=name
        )

    def _entry(self, patient, *, age_minutes=0, **kwargs):
        from apps.scheduling.models import Waitlist

        entry = Waitlist.objects.create(
            clinic=self.clinic, patient=patient, service=self.service, **kwargs
        )
        if age_minutes:
            # Explicit created_at so ordering is deterministic under test speed.
            Waitlist.objects.filter(id=entry.id).update(
                created_at=timezone.now() - timedelta(minutes=age_minutes)
            )
            entry.refresh_from_db()
        return entry

    def _cancel(self):
        """Cancel the seeded appointment with on_commit callbacks executed (the
        offer task is enqueued on commit) and the transport mocked. Each mocked
        send returns a distinct provider id (the Message log enforces uniqueness)."""
        from itertools import count

        from apps.scheduling.engine import cancel_appointment

        ids = count()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_template",
            side_effect=lambda *a, **k: f"wamid.WL{next(ids)}",
        ) as send:
            with self.captureOnCommitCallbacks(execute=True):
                result = cancel_appointment(self.clinic, self.canceller, self.appt.id)
        self.assertTrue(result.ok)
        return send

    def test_cancellation_offers_to_oldest_matching_entries_in_order(self):
        from apps.scheduling.models import WaitlistStatus

        old = self._entry(self._patient(1, "Ada"), age_minutes=60)
        mid = self._entry(self._patient(2, "Ben"), age_minutes=40)
        new = self._entry(self._patient(3, "Cy"), age_minutes=20)
        overflow = self._entry(self._patient(4, "Dee"), age_minutes=5)  # 4th in line

        send = self._cancel()
        from .models import WaitlistOffer

        offered_ids = set(
            WaitlistOffer.objects.values_list("waitlist_id", flat=True)
        )
        self.assertEqual(offered_ids, {old.id, mid.id, new.id})  # fanout of 3
        self.assertEqual(send.call_count, 3)
        for entry in (old, mid, new):
            entry.refresh_from_db()
            self.assertEqual(entry.status, WaitlistStatus.OFFERED)
        overflow.refresh_from_db()
        self.assertEqual(overflow.status, WaitlistStatus.ACTIVE)
        # Offers are sent immediately (not waiting for beat) as utility messages.
        offer = WaitlistOffer.objects.first()
        self.assertEqual(offer.status, "sent")
        self.assertIsNotNone(offer.offer_expires_at)
        self.assertTrue(
            Message.objects.filter(direction=Direction.OUT, category="utility").exists()
        )

    def test_offer_template_carries_slot_and_tap_payload(self):
        from .models import WaitlistOffer
        from .waitlist import build_offer_template

        self._entry(self._patient(1, "Ada Lovelace"))
        self._cancel()
        offer = WaitlistOffer.objects.get()
        spec = build_offer_template(offer)
        self.assertEqual(spec["name"], "waitlist_slot_open")
        self.assertEqual(spec["body_params"][0], "Ada")
        self.assertEqual(spec["body_params"][1], "Bright Smiles")
        self.assertIn(":", spec["body_params"][2])  # a formatted time label
        self.assertEqual(
            [b["payload"] for b in spec["buttons"]], [f"waitlist_offer_{offer.id}"]
        )

    def test_non_matching_entries_are_skipped(self):
        from apps.scheduling.models import TimePreference

        from apps.scheduling.models import Waitlist

        other_service = Service.objects.create(
            clinic=self.clinic, name="Whitening", duration_min=30
        )
        Waitlist.objects.create(  # different service
            clinic=self.clinic, patient=self._patient(1, "WrongSvc"),
            service=other_service,
        )
        slot_day = self.slot.start.astimezone(NY).date()
        self._entry(  # window ends before the freed slot's day
            self._patient(2, "TooEarly"), date_to=slot_day - timedelta(days=1)
        )
        # Freed slot is 9:00 AM (first of the day) — evening pref can't match.
        self._entry(
            self._patient(3, "EveOnly"), time_preference=TimePreference.EVENING
        )
        opted = self._patient(4, "Opted")
        opted.opted_out_at = timezone.now()
        opted.save()
        self._entry(opted)
        # The canceller is waitlisted too — never offered their own freed slot.
        self._entry(self.canceller)

        send = self._cancel()
        from .models import WaitlistOffer

        self.assertEqual(WaitlistOffer.objects.count(), 0)
        send.assert_not_called()

    def test_repeat_processing_cannot_double_offer(self):
        from .models import WaitlistOffer
        from .waitlist import create_offers

        self._entry(self._patient(1, "Ada"))
        self._cancel()
        self.assertEqual(WaitlistOffer.objects.count(), 1)
        # Re-saving the cancelled appointment fires no new task (no transition)...
        self.appt.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            self.appt.save()
        # ...and even a direct re-run is blocked by the unique constraint + the
        # entry no longer being active.
        self.assertEqual(create_offers(self.appt), 0)
        self.assertEqual(WaitlistOffer.objects.count(), 1)

    def test_first_confirm_wins_second_gets_filled(self):
        from apps.scheduling.models import WaitlistStatus
        from .models import WaitlistOffer
        from .waitlist import accept_offer

        ada, ben = self._patient(1, "Ada"), self._patient(2, "Ben")
        e1, e2 = self._entry(ada, age_minutes=10), self._entry(ben)
        self._cancel()
        offer1 = WaitlistOffer.objects.get(waitlist=e1)
        offer2 = WaitlistOffer.objects.get(waitlist=e2)

        win = accept_offer(self.clinic, ada, offer1.id)
        self.assertEqual(win.result, "booked")
        self.assertEqual(win.appointment.patient_id, ada.id)
        self.assertEqual(win.appointment.starts_at, self.slot.start)

        lose = accept_offer(self.clinic, ben, offer2.id)
        self.assertEqual(lose.result, "filled")
        e1.refresh_from_db(); e2.refresh_from_db()
        self.assertEqual(e1.status, WaitlistStatus.BOOKED)
        self.assertEqual(e2.status, WaitlistStatus.ACTIVE)  # back in line
        # Exactly one active appointment occupies the slot.
        self.assertEqual(
            Appointment.objects.filter(
                starts_at=self.slot.start, status__in=("pending", "confirmed")
            ).count(),
            1,
        )

    def test_double_tap_reconfirms_without_double_booking(self):
        from .models import WaitlistOffer
        from .waitlist import accept_offer

        ada = self._patient(1, "Ada")
        entry = self._entry(ada)
        self._cancel()
        offer = WaitlistOffer.objects.get(waitlist=entry)
        first = accept_offer(self.clinic, ada, offer.id)
        again = accept_offer(self.clinic, ada, offer.id)
        self.assertEqual(first.result, "booked")
        self.assertEqual(again.result, "already_booked")
        self.assertEqual(Appointment.objects.filter(patient=ada).count(), 1)

    def test_hold_expiry_returns_entry_to_active(self):
        from apps.scheduling.models import WaitlistStatus
        from .models import WaitlistOffer, WaitlistOfferStatus
        from .waitlist import expire_stale_offers

        entry = self._entry(self._patient(1, "Ada"))
        self._cancel()
        WaitlistOffer.objects.update(
            offer_expires_at=timezone.now() - timedelta(minutes=1)
        )
        expire_stale_offers()
        offer = WaitlistOffer.objects.get()
        entry.refresh_from_db()
        self.assertEqual(offer.status, WaitlistOfferStatus.EXPIRED)
        self.assertEqual(entry.status, WaitlistStatus.ACTIVE)

    def test_expired_offer_tap_does_not_book(self):
        from .models import WaitlistOffer
        from .waitlist import accept_offer

        ada = self._patient(1, "Ada")
        entry = self._entry(ada)
        self._cancel()
        WaitlistOffer.objects.update(
            offer_expires_at=timezone.now() - timedelta(minutes=1)
        )
        offer = WaitlistOffer.objects.get(waitlist=entry)
        outcome = accept_offer(self.clinic, ada, offer.id)
        self.assertEqual(outcome.result, "expired")
        self.assertEqual(Appointment.objects.filter(patient=ada).count(), 0)

    def test_offer_for_another_patient_cannot_be_accepted(self):
        from .models import WaitlistOffer
        from .waitlist import accept_offer

        ada = self._patient(1, "Ada")
        self._entry(ada)
        self._cancel()
        offer = WaitlistOffer.objects.get()
        mal = self._patient(9, "Mal")
        outcome = accept_offer(self.clinic, mal, offer.id)
        self.assertEqual(outcome.result, "not_found")
        self.assertEqual(Appointment.objects.filter(patient=mal).count(), 0)

    def test_quiet_hours_defer_offer_send(self):
        from .models import WaitlistOffer, WaitlistOfferStatus

        self.clinic.quiet_hours_start = "08:00"
        self.clinic.quiet_hours_end = "21:00"
        self.clinic.save()
        self._entry(self._patient(1, "Ada"))
        # 23:00 tonight (clinic-local) — after close, but well before the freed
        # slot 3 days out, so the offer defers instead of dying.
        clock = (
            timezone.now()
            .astimezone(NY)
            .replace(hour=23, minute=0, second=0, microsecond=0)
            .astimezone(ZoneInfo("UTC"))
        )
        with patch("django.utils.timezone.now", return_value=clock):
            send = self._cancel()
        send.assert_not_called()
        offer = WaitlistOffer.objects.get()
        self.assertEqual(offer.status, WaitlistOfferStatus.PENDING)
        self.assertEqual(offer.scheduled_for.astimezone(NY).hour, 8)

    def test_near_term_freed_slot_is_not_offered(self):
        # Slot inside min-notice (2h default) — not genuinely bookable, no offers.
        from .models import WaitlistOffer

        self._entry(self._patient(1, "Ada"))
        self.appt.starts_at = timezone.now() + timedelta(minutes=30)
        self.appt.ends_at = self.appt.starts_at + timedelta(minutes=30)
        self.appt.save()
        self._cancel()
        self.assertEqual(WaitlistOffer.objects.count(), 0)


class NoShowRecoveryTests(TestCase):
    """No-show → two-step recovery outbox rows, and deterministic attribution of
    the booking that recovers the no-show."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles", slug="bright-smiles", timezone="America/New_York",
            quiet_hours_start="00:00", quiet_hours_end="23:59",
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15551230000", name="Alex"
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Cleaning", duration_min=30
        )

    def _no_show(self):
        from apps.scheduling.engine import mark_no_show

        start = timezone.now() - timedelta(hours=3)
        appt = Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )
        result = mark_no_show(self.clinic, appt.id)
        self.assertTrue(result.ok)
        appt.refresh_from_db()
        return appt

    def _recovery_rows(self, appt):
        return appt.scheduled_messages.filter(
            kind__in=(
                ScheduledMessageKind.RECOVERY_SAMEDAY,
                ScheduledMessageKind.RECOVERY_REBOOK,
            )
        )

    def test_no_show_queues_exactly_the_recovery_pair(self):
        appt = self._no_show()
        rows = {r.kind: r for r in self._recovery_rows(appt)}
        self.assertEqual(
            set(rows),
            {ScheduledMessageKind.RECOVERY_SAMEDAY, ScheduledMessageKind.RECOVERY_REBOOK},
        )
        now = timezone.now()
        self.assertLessEqual(rows[ScheduledMessageKind.RECOVERY_SAMEDAY].scheduled_for, now)
        rebook_due = rows[ScheduledMessageKind.RECOVERY_REBOOK].scheduled_for
        self.assertGreater(rebook_due, now + timedelta(days=1, hours=23))
        self.assertLess(rebook_due, now + timedelta(days=2, minutes=5))

    def test_re_save_does_not_duplicate_recovery_rows(self):
        appt = self._no_show()
        appt.save()  # any later save re-fires the reconcile signal
        reconcile_appointment_reminders(appt)
        self.assertEqual(self._recovery_rows(appt).count(), 2)

    def test_cancelled_and_completed_do_not_queue_recovery(self):
        for status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED):
            start = timezone.now() - timedelta(hours=3)
            appt = Appointment.objects.create(
                clinic=self.clinic, patient=self.patient, service=self.service,
                starts_at=start, ends_at=start + timedelta(minutes=30),
            )
            appt.status = status
            appt.save()
            self.assertEqual(self._recovery_rows(appt).count(), 0, status)

    def test_recovery_rows_survive_later_reconcile(self):
        appt = self._no_show()
        # Pre-appointment rows are skipped for the dead appointment...
        pre = appt.scheduled_messages.get(kind=ScheduledMessageKind.CONFIRMATION)
        self.assertEqual(pre.status, ScheduledMessageStatus.SKIPPED)
        # ...but a later reconcile leaves the recovery rows pending.
        reconcile_appointment_reminders(appt)
        statuses = set(self._recovery_rows(appt).values_list("status", flat=True))
        self.assertEqual(statuses, {ScheduledMessageStatus.PENDING})

    def test_recovery_respects_quiet_hours(self):
        self.clinic.quiet_hours_start = "08:00"
        self.clinic.quiet_hours_end = "21:00"
        self.clinic.save()
        # Freeze the clock at 23:00 NY — past the window close.
        clock = datetime(2026, 7, 10, 23, 0, tzinfo=NY).astimezone(ZoneInfo("UTC"))
        with patch("django.utils.timezone.now", return_value=clock):
            appt = self._no_show()
        sameday = appt.scheduled_messages.get(kind=ScheduledMessageKind.RECOVERY_SAMEDAY)
        local = sameday.scheduled_for.astimezone(NY)
        self.assertEqual((local.hour, local.minute), (8, 0))

    def test_recovery_disabled_flag_queues_nothing(self):
        self.clinic.no_show_recovery_enabled = False
        self.clinic.save()
        appt = self._no_show()
        self.assertEqual(self._recovery_rows(appt).count(), 0)

    def test_opted_out_patient_gets_no_recovery(self):
        self.patient.opted_out_at = timezone.now()
        self.patient.save()
        appt = self._no_show()
        self.assertEqual(self._recovery_rows(appt).count(), 0)

    def test_dispatch_skips_row_when_patient_opted_out_after_queueing(self):
        appt = self._no_show()
        row = appt.scheduled_messages.get(kind=ScheduledMessageKind.RECOVERY_SAMEDAY)
        row.scheduled_for = timezone.now() - timedelta(minutes=1)
        row.save()
        self.patient.opted_out_at = timezone.now()
        self.patient.save()
        with patch(
            "apps.messaging.channels.whatsapp.WhatsAppChannel.send_template"
        ) as send:
            dispatch_due_messages()
        send.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, ScheduledMessageStatus.SKIPPED)

    def _mark_rebook_sent(self, appt):
        row = appt.scheduled_messages.get(kind=ScheduledMessageKind.RECOVERY_REBOOK)
        row.status = ScheduledMessageStatus.SENT
        row.sent_at = timezone.now()
        row.save()
        return row

    def test_booking_after_recovery_send_is_attributed(self):
        no_show = self._no_show()
        self._mark_rebook_sent(no_show)
        start = timezone.now() + timedelta(days=3)
        new_appt = Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )
        new_appt.refresh_from_db()
        self.assertEqual(new_appt.recovered_from_id, no_show.id)

    def test_booking_without_recovery_send_is_not_attributed(self):
        self._no_show()  # rows queued but never sent
        start = timezone.now() + timedelta(days=3)
        new_appt = Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )
        new_appt.refresh_from_db()
        self.assertIsNone(new_appt.recovered_from_id)

    def test_other_patients_booking_is_not_attributed(self):
        no_show = self._no_show()
        self._mark_rebook_sent(no_show)
        other = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15559990000", name="Sam"
        )
        start = timezone.now() + timedelta(days=3)
        new_appt = Appointment.objects.create(
            clinic=self.clinic, patient=other, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )
        new_appt.refresh_from_db()
        self.assertIsNone(new_appt.recovered_from_id)

    def test_build_template_recovery_sameday(self):
        appt = self._no_show()
        row = appt.scheduled_messages.get(kind=ScheduledMessageKind.RECOVERY_SAMEDAY)
        spec = build_template(row)
        self.assertEqual(spec["name"], "noshow_recovery_sameday")
        self.assertEqual(spec["body_params"], ["Alex", "Bright Smiles"])
        self.assertNotIn("buttons", spec)

    def test_build_template_rebook_offer_has_button_and_openings(self):
        from apps.scheduling.models import ScheduleRule

        # Open every weekday so the openings sentence has real slots to cite.
        for wd in range(7):
            ScheduleRule.objects.create(
                clinic=self.clinic, weekday=wd, start_time="09:00", end_time="17:00"
            )
        appt = self._no_show()
        row = appt.scheduled_messages.get(kind=ScheduledMessageKind.RECOVERY_REBOOK)
        spec = build_template(row)
        self.assertEqual(spec["name"], "noshow_rebook_offer")
        self.assertEqual(spec["body_params"][:2], ["Alex", "Bright Smiles"])
        self.assertTrue(spec["body_params"][2].startswith("We have openings "))
        self.assertNotIn("\n", spec["body_params"][2])  # Meta rejects newlines
        self.assertEqual(
            [b["payload"] for b in spec["buttons"]], [f"rebook_appt_{appt.id}"]
        )

    def test_rebook_openings_falls_back_when_no_slots(self):
        # No ScheduleRule rows → no availability at all.
        appt = self._no_show()
        row = appt.scheduled_messages.get(kind=ScheduledMessageKind.RECOVERY_REBOOK)
        spec = build_template(row)
        self.assertEqual(spec["body_params"][2], "New openings come up every day.")
