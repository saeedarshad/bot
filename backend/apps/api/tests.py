from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import Conversation, EscalationTicket
from apps.messaging.models import (
    ScheduledMessage,
    ScheduledMessageKind,
    ScheduledMessageStatus,
)
from apps.scheduling.models import Appointment, Service

NY = ZoneInfo("America/New_York")


class ApiBase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Bright Smiles", slug="bright-smiles")
        self.user = get_user_model().objects.create_user(
            username="demo", password="demo12345", is_staff=True
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Cleaning", duration_min=30
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15551230000", name="Alex"
        )
        self.client = APIClient()

    def auth(self):
        self.client.force_authenticate(self.user)


class AuthTests(ApiBase):
    def test_me_requires_auth(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_login_and_me(self):
        resp = self.client.post(
            "/api/auth/login", {"username": "demo", "password": "demo12345"}
        )
        self.assertEqual(resp.status_code, 200)
        me = self.client.get("/api/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["clinic"]["name"], "Bright Smiles")

    def test_bad_login(self):
        resp = self.client.post(
            "/api/auth/login", {"username": "demo", "password": "wrong"}
        )
        self.assertEqual(resp.status_code, 401)


class AppointmentApiTests(ApiBase):
    def test_create_manual_appointment_sets_ends_at(self):
        self.auth()
        start = timezone.now() + timedelta(days=1)
        resp = self.client.post(
            "/api/appointments",
            {
                "patient": self.patient.id,
                "service": self.service.id,
                "starts_at": start.isoformat(),
                "status": "confirmed",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        appt = Appointment.objects.get()
        self.assertEqual(appt.source, "dashboard")
        self.assertEqual((appt.ends_at - appt.starts_at).total_seconds(), 1800)

    def test_list_scoped_to_clinic(self):
        other = Clinic.objects.create(name="Other", slug="other")
        other_patient = Patient.objects.create(clinic=other, phone_e164="+1999")
        other_service = Service.objects.create(clinic=other, name="X", duration_min=15)
        Appointment.objects.create(
            clinic=other, patient=other_patient, service=other_service,
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(minutes=15),
        )
        self.auth()
        resp = self.client.get("/api/appointments")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 0)  # current_clinic = first clinic (this one)


class AppointmentLifecycleApiTests(ApiBase):
    def _appt(self, status="confirmed"):
        start = timezone.now() + timedelta(days=1)
        return Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30), status=status,
        )

    def test_no_show_action_marks_and_counts(self):
        appt = self._appt()
        self.auth()
        resp = self.client.post(f"/api/appointments/{appt.id}/no_show")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], "no_show")
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.no_show_count, 1)

    def test_complete_action_marks_completed(self):
        appt = self._appt()
        self.auth()
        resp = self.client.post(f"/api/appointments/{appt.id}/complete")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], "completed")

    def test_lifecycle_action_requires_auth(self):
        appt = self._appt()
        self.assertEqual(
            self.client.post(f"/api/appointments/{appt.id}/no_show").status_code, 403
        )

    def test_no_show_on_terminal_appointment_404s(self):
        appt = self._appt(status="completed")
        self.auth()
        resp = self.client.post(f"/api/appointments/{appt.id}/no_show")
        self.assertEqual(resp.status_code, 404)


class AtRiskFlagTests(ApiBase):
    def _appt(self, days=1):
        start = timezone.now() + timedelta(days=days)
        return Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30), status="confirmed",
        )

    def _sent_24h(self, appt):
        # Creating the appointment already reconciled reminders; flip the 24h to sent.
        msg = appt.scheduled_messages.get(kind=ScheduledMessageKind.REMINDER_24H)
        msg.status = ScheduledMessageStatus.SENT
        msg.save()
        return msg

    def _fetch(self, appt):
        self.auth()
        resp = self.client.get(f"/api/appointments/{appt.id}")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def test_unconfirmed_after_reminder_is_at_risk(self):
        appt = self._appt(days=2)
        self._sent_24h(appt)
        self.assertTrue(self._fetch(appt)["at_risk"])

    def test_confirmed_appointment_is_not_at_risk(self):
        appt = self._appt(days=2)
        self._sent_24h(appt)
        appt.patient_confirmed_at = timezone.now()
        appt.save()
        self.assertFalse(self._fetch(appt)["at_risk"])

    def test_no_reminder_sent_is_not_at_risk(self):
        appt = self._appt(days=2)  # reminders still pending, not sent
        self.assertFalse(self._fetch(appt)["at_risk"])


class CostSummaryApiTests(ApiBase):
    def _out(self, category, amount):
        from decimal import Decimal

        from apps.messaging.models import Message

        return Message.objects.create(
            clinic=self.clinic, channel="whatsapp", direction="out",
            category=category, cost_amount=Decimal(amount),
        )

    def test_summary_aggregates_current_month_by_category(self):
        self._out("utility", "0.04")
        self._out("utility", "0.04")
        self._out("marketing", "0.0625")
        self._out("service", "0")  # inbound reply, free
        self.auth()
        resp = self.client.get("/api/costs")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["message_count"], 4)
        self.assertEqual(data["total"], "0.1425")
        cats = {r["category"]: r for r in data["by_category"]}
        self.assertEqual(cats["utility"]["count"], 2)
        self.assertEqual(cats["utility"]["amount"], "0.0800")

    def test_summary_requires_auth(self):
        self.assertEqual(self.client.get("/api/costs").status_code, 403)

    def test_summary_excludes_other_clinic(self):
        from decimal import Decimal

        from apps.messaging.models import Message

        other = Clinic.objects.create(name="Other", slug="other")
        Message.objects.create(
            clinic=other, channel="whatsapp", direction="out",
            category="marketing", cost_amount=Decimal("9.99"),
        )
        self._out("utility", "0.04")
        self.auth()
        resp = self.client.get("/api/costs")
        self.assertEqual(resp.json()["total"], "0.0400")


class AnalyticsTests(ApiBase):
    """Aggregation over controlled data in a fully-past clinic-local month
    (June 2026), so the `now` cutoff never trims the fixtures."""

    def setUp(self):
        super().setUp()
        from apps.api import analytics
        from decimal import Decimal

        self.priced = Service.objects.create(
            clinic=self.clinic, name="Scaling", duration_min=45,
            price_min=Decimal("150.00"), price_max=Decimal("200.00"),
        )
        self.rng = analytics.month_range(self.clinic, 2026, 6)
        # A June instant to hang fixtures on (auto_now fields are updated after).
        self.june = datetime(2026, 6, 15, 14, 0, tzinfo=NY)

    def _appt(self, *, source="bot", status="completed", starts=None,
              created=None, recovered_from=None, service=None):
        starts = starts or self.june
        appt = Appointment.objects.create(
            clinic=self.clinic, patient=self.patient,
            service=service or self.service,
            starts_at=starts, ends_at=starts + timedelta(minutes=30),
            status=status, source=source, recovered_from=recovered_from,
        )
        Appointment.objects.filter(id=appt.id).update(
            created_at=created or self.june
        )
        appt.refresh_from_db()
        return appt

    # --- pure module functions ---------------------------------------------

    def test_bookings_by_source_and_bot_share(self):
        from apps.api import analytics

        self._appt(source="bot")
        self._appt(source="bot")
        self._appt(source="dashboard")
        out = analytics.bookings_by_source(self.clinic, self.rng)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["bot_share"], round(2 / 3, 4))
        by = {r["source"]: r["count"] for r in out["by_source"]}
        self.assertEqual(by["bot"], 2)
        self.assertEqual(by["dashboard"], 1)
        self.assertEqual(by["walk_in"], 0)

    def test_no_show_rate_excludes_cancellations(self):
        from apps.api import analytics

        self._appt(status="completed")
        self._appt(status="completed")
        self._appt(status="no_show")
        self._appt(status="cancelled")  # must not count against the rate
        out = analytics.no_show_stats(self.clinic, self.rng)
        self.assertEqual(out["decided"], 3)
        self.assertEqual(out["no_show"], 1)
        self.assertEqual(out["rate"], round(1 / 3, 4))

    def test_out_of_range_appointments_are_ignored(self):
        from apps.api import analytics

        # A completed visit in July is outside the June range.
        self._appt(status="completed", starts=datetime(2026, 7, 2, 10, tzinfo=NY))
        self._appt(status="no_show")
        out = analytics.no_show_stats(self.clinic, self.rng)
        self.assertEqual(out["decided"], 1)
        self.assertEqual(out["rate"], 1.0)

    def test_recovered_revenue_uses_price_min(self):
        from apps.api import analytics

        no_show = self._appt(status="no_show")
        self._appt(service=self.priced, recovered_from=no_show)
        self._appt(service=self.priced, recovered_from=no_show)
        out = analytics.recovered_revenue(self.clinic, self.rng)
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["revenue"], "300.00")  # 2 × price_min 150

    def test_no_show_trend_buckets_by_month(self):
        from apps.api import analytics

        wide = analytics.DateRange(
            start=analytics.month_range(self.clinic, 2026, 5).start,
            end=analytics.month_range(self.clinic, 2026, 6).end,
            tz=self.rng.tz,
        )
        self._appt(status="no_show", starts=datetime(2026, 5, 10, 10, tzinfo=NY))
        self._appt(status="completed", starts=datetime(2026, 6, 10, 10, tzinfo=NY))
        trend = analytics.no_show_trend(self.clinic, wide)
        periods = [b["period"] for b in trend]
        self.assertEqual(periods, ["2026-05", "2026-06"])
        self.assertEqual(trend[0]["rate"], 1.0)
        self.assertEqual(trend[1]["rate"], 0.0)

    def test_containment_rate(self):
        from apps.api import analytics

        # Two conversations with June messages; one escalates.
        for i in range(2):
            conv = Conversation.objects.create(
                clinic=self.clinic, patient=self.patient, channel="whatsapp"
            )
            msg = conv.messages.create(
                clinic=self.clinic, channel="whatsapp", direction="in", body="hi"
            )
            conv.messages.filter(id=msg.id).update(created_at=self.june)
            if i == 0:
                t = EscalationTicket.objects.create(clinic=self.clinic, conversation=conv)
                EscalationTicket.objects.filter(id=t.id).update(created_at=self.june)
        out = analytics.containment_stats(self.clinic, self.rng)
        self.assertEqual(out["total_conversations"], 2)
        self.assertEqual(out["escalated"], 1)
        self.assertEqual(out["rate"], 0.5)

    def test_response_time_median(self):
        from apps.api import analytics

        conv = Conversation.objects.create(
            clinic=self.clinic, patient=self.patient, channel="whatsapp"
        )
        m_in = conv.messages.create(
            clinic=self.clinic, channel="whatsapp", direction="in", body="hi"
        )
        m_out = conv.messages.create(
            clinic=self.clinic, channel="whatsapp", direction="out", body="hello"
        )
        conv.messages.filter(id=m_in.id).update(created_at=self.june)
        conv.messages.filter(id=m_out.id).update(created_at=self.june + timedelta(seconds=30))
        out = analytics.response_time_stats(self.clinic, self.rng)
        self.assertEqual(out["median_seconds"], 30)
        self.assertEqual(out["sample"], 1)

    def test_empty_range_is_all_zeros_not_crash(self):
        from apps.api import analytics

        data = analytics.compute_analytics(self.clinic, self.rng)
        self.assertEqual(data["bookings"]["total"], 0)
        self.assertEqual(data["no_show"]["rate"], 0.0)
        self.assertEqual(data["recovered"]["revenue"], "0")
        self.assertIsNone(data["response_time"]["median_seconds"])
        self.assertEqual(data["containment"]["rate"], 0.0)

    # --- endpoint -----------------------------------------------------------

    def test_analytics_endpoint_requires_auth(self):
        self.assertEqual(self.client.get("/api/analytics").status_code, 403)

    def test_analytics_endpoint_returns_metrics(self):
        self._appt(source="bot", status="no_show")
        self.auth()
        resp = self.client.get("/api/analytics?from=2026-06-01&to=2026-06-30")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["bookings"]["total"], 1)
        self.assertEqual(body["no_show"]["no_show"], 1)
        self.assertEqual(body["currency"], self.clinic.currency)

    def test_monthly_report_generation_is_idempotent(self):
        from apps.clinics.models import MonthlyReport
        from apps.messaging.tasks import generate_monthly_reports

        # "Now" = July 2026 → previous month is June.
        self._appt(source="bot", status="completed")
        with patch("django.utils.timezone.now", return_value=self.june.astimezone(ZoneInfo("UTC")) + timedelta(days=30)):
            generate_monthly_reports()
            generate_monthly_reports()
        report = MonthlyReport.objects.get(clinic=self.clinic)
        self.assertEqual((report.year, report.month), (2026, 6))
        self.assertEqual(report.data["bookings"]["total"], 1)
        self.assertEqual(MonthlyReport.objects.count(), 1)

    def test_monthly_report_endpoint_lists_reports(self):
        from apps.clinics.models import MonthlyReport

        MonthlyReport.objects.create(
            clinic=self.clinic, year=2026, month=6, data={"bookings": {"total": 4}}
        )
        self.auth()
        resp = self.client.get("/api/reports/monthly")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(rows[0]["month"], 6)
        self.assertEqual(rows[0]["data"]["bookings"]["total"], 4)


class EscalationApiTests(ApiBase):
    def test_resolve_resumes_bot(self):
        conv = Conversation.objects.create(
            clinic=self.clinic, patient=self.patient, channel="whatsapp", bot_paused=True
        )
        ticket = EscalationTicket.objects.create(clinic=self.clinic, conversation=conv)
        self.auth()
        resp = self.client.post(f"/api/escalations/{ticket.id}/resolve")
        self.assertEqual(resp.status_code, 200)
        conv.refresh_from_db()
        ticket.refresh_from_db()
        self.assertFalse(conv.bot_paused)
        self.assertEqual(ticket.status, "resolved")
