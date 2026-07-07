from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clinics.models import (
    Clinic,
    Patient,
    Subscription,
    SubscriptionStatus,
    UserProfile,
)
from apps.conversations.inbound import resolve_clinic
from apps.conversations.models import Conversation, EscalationTicket
from apps.messaging.models import (
    ScheduledMessage,
    ScheduledMessageKind,
    ScheduledMessageStatus,
)
from apps.scheduling.models import Appointment, Practitioner, ScheduleRule, Service

NY = ZoneInfo("America/New_York")


class ApiBase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Bright Smiles", slug="bright-smiles")
        self.user = get_user_model().objects.create_user(
            username="demo", password="demo12345", is_staff=True
        )
        UserProfile.objects.create(user=self.user, clinic=self.clinic)
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


class TenantScopingTests(ApiBase):
    """current_clinic resolves per-user, not "first active clinic": each staff
    user only ever sees their own clinic (Phase 4 tenant boundary)."""

    def _clinic_b_user(self):
        clinic_b = Clinic.objects.create(name="Clinic B", slug="clinic-b")
        user_b = get_user_model().objects.create_user(
            username="staffb", password="pw12345678", is_staff=True
        )
        UserProfile.objects.create(user=user_b, clinic=clinic_b)
        return clinic_b, user_b

    def test_me_returns_users_own_clinic(self):
        clinic_b, user_b = self._clinic_b_user()
        self.client.force_authenticate(user_b)
        me = self.client.get("/api/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["clinic"]["name"], "Clinic B")

    def test_staff_cannot_read_another_clinics_appointments(self):
        # An appointment in THIS clinic is visible to its own staff...
        start = timezone.now() + timedelta(days=1)
        Appointment.objects.create(
            clinic=self.clinic, patient=self.patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )
        clinic_b, user_b = self._clinic_b_user()
        self.client.force_authenticate(user_b)
        # ...but clinic B's staff sees none of it.
        resp = self.client.get("/api/appointments")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 0)

    def test_user_without_profile_has_no_clinic(self):
        orphan = get_user_model().objects.create_user(
            username="orphan", password="pw12345678", is_staff=True
        )
        self.client.force_authenticate(orphan)
        self.assertEqual(self.client.get("/api/me").status_code, 404)


class CrossTenantWriteTests(ApiBase):
    """Queryset scoping guards which rows you can *address*; these prove the FK
    *values* in a write body can't reach into another clinic either. Staff auth
    is clinic A (self.user); clinic B holds the foreign objects."""

    def setUp(self):
        super().setUp()
        self.clinic_b = Clinic.objects.create(name="Clinic B", slug="clinic-b")
        self.patient_b = Patient.objects.create(
            clinic=self.clinic_b, phone_e164="+15559990000", name="Bianca"
        )
        self.service_b = Service.objects.create(
            clinic=self.clinic_b, name="B Cleaning", duration_min=30
        )
        self.practitioner_b = Practitioner.objects.create(
            clinic=self.clinic_b, name="Dr. Bee"
        )
        self.auth()  # as clinic A

    def _start(self):
        return (timezone.now() + timedelta(days=1)).isoformat()

    def test_cannot_book_with_other_clinics_patient(self):
        resp = self.client.post(
            "/api/appointments",
            {"patient": self.patient_b.id, "service": self.service.id,
             "starts_at": self._start(), "status": "confirmed"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_cannot_book_with_other_clinics_service(self):
        resp = self.client.post(
            "/api/appointments",
            {"patient": self.patient.id, "service": self.service_b.id,
             "starts_at": self._start(), "status": "confirmed"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_cannot_book_with_other_clinics_practitioner(self):
        resp = self.client.post(
            "/api/appointments",
            {"patient": self.patient.id, "service": self.service.id,
             "practitioner": self.practitioner_b.id,
             "starts_at": self._start(), "status": "confirmed"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_own_clinic_booking_still_works(self):
        resp = self.client.post(
            "/api/appointments",
            {"patient": self.patient.id, "service": self.service.id,
             "starts_at": self._start(), "status": "confirmed"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_cannot_set_preferred_practitioner_across_clinic(self):
        resp = self.client.patch(
            f"/api/patients/{self.patient.id}",
            {"preferred_practitioner": self.practitioner_b.id}, format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_cannot_create_schedule_rule_for_other_clinics_practitioner(self):
        resp = self.client.post(
            "/api/schedule-rules",
            {"practitioner": self.practitioner_b.id, "weekday": 1,
             "start_time": "09:00", "end_time": "17:00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_cannot_restrict_service_to_other_clinics_practitioner(self):
        resp = self.client.post(
            "/api/services",
            {"name": "New", "duration_min": 30,
             "practitioners": [self.practitioner_b.id]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_cannot_patch_other_clinics_appointment(self):
        # A row in clinic B is not even addressable → 404, never a silent write.
        start = timezone.now() + timedelta(days=1)
        appt_b = Appointment.objects.create(
            clinic=self.clinic_b, patient=self.patient_b, service=self.service_b,
            starts_at=start, ends_at=start + timedelta(minutes=30),
        )
        resp = self.client.patch(
            f"/api/appointments/{appt_b.id}", {"status": "cancelled"}, format="json"
        )
        self.assertEqual(resp.status_code, 404)


class SuspensionTests(ApiBase):
    """An unpaid (suspended/cancelled) clinic is cut off: dashboard 403 + bot
    silent. A clinic with no subscription row is treated as active."""

    def _sub(self, status):
        Subscription.objects.create(clinic=self.clinic, status=status)

    def test_no_subscription_treated_active(self):
        self.auth()
        self.assertEqual(self.client.get("/api/me").status_code, 200)

    def test_active_subscription_dashboard_ok(self):
        self._sub(SubscriptionStatus.ACTIVE)
        self.auth()
        self.assertEqual(self.client.get("/api/me").status_code, 200)

    def test_suspended_clinic_dashboard_forbidden(self):
        self._sub(SubscriptionStatus.SUSPENDED)
        self.auth()
        self.assertEqual(self.client.get("/api/me").status_code, 403)
        self.assertEqual(self.client.get("/api/appointments").status_code, 403)

    def test_cancelled_clinic_dashboard_forbidden(self):
        self._sub(SubscriptionStatus.CANCELLED)
        self.auth()
        self.assertEqual(self.client.get("/api/appointments").status_code, 403)

    def test_inbound_bot_silent_when_suspended(self):
        self.clinic.whatsapp_phone_number_id = "PNID123"
        self.clinic.save(update_fields=["whatsapp_phone_number_id"])
        self._sub(SubscriptionStatus.SUSPENDED)
        self.assertIsNone(resolve_clinic("PNID123"))

    def test_inbound_bot_resolves_when_active(self):
        self.clinic.whatsapp_phone_number_id = "PNID123"
        self.clinic.save(update_fields=["whatsapp_phone_number_id"])
        self._sub(SubscriptionStatus.ACTIVE)
        self.assertEqual(resolve_clinic("PNID123"), self.clinic)


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
        self.assertEqual(len(resp.json()), 0)  # scoped to this user's clinic, not "other"


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


class RecallApiTests(ApiBase):
    def _rule(self, **kw):
        from apps.messaging.models import RecallRule

        defaults = dict(
            clinic=self.clinic, name="6-month", service=self.service,
            interval_days=180, window_days=7, template_name="recall_checkup",
        )
        defaults.update(kw)
        return RecallRule.objects.create(**defaults)

    def _completed(self, patient, days_ago):
        start = timezone.now() - timedelta(days=days_ago)
        return Appointment.objects.create(
            clinic=self.clinic, patient=patient, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30),
            status="completed",
        )

    def test_create_rule_scopes_to_clinic(self):
        self.auth()
        resp = self.client.post(
            "/api/recall-rules",
            {"service": self.service.id, "interval_days": 180, "template_name": "recall_checkup"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        from apps.messaging.models import RecallRule
        rule = RecallRule.objects.get(id=resp.json()["id"])
        self.assertEqual(rule.clinic_id, self.clinic.id)

    def test_rules_require_auth(self):
        self.assertEqual(self.client.get("/api/recall-rules").status_code, 403)

    def test_preview_returns_count_and_cost(self):
        rule = self._rule()
        self._completed(self.patient, days_ago=180)
        self.auth()
        resp = self.client.get(f"/api/recall-rules/{rule.id}/preview")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["eligible"], 1)
        self.assertEqual(body["projected_cost"], "0.0625")
        self.assertEqual(body["sample"], ["Alex"])

    def test_run_creates_campaign_and_enqueues(self):
        from apps.messaging.models import RecallSend

        rule = self._rule()
        self._completed(self.patient, days_ago=180)
        self.auth()
        resp = self.client.post(f"/api/recall-rules/{rule.id}/run")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["eligible"], 1)
        self.assertEqual(RecallSend.objects.filter(campaign_id=resp.json()["id"]).count(), 1)

    def test_run_blocked_when_recalls_disabled(self):
        rule = self._rule()
        self._completed(self.patient, days_ago=180)
        self.clinic.recalls_enabled = False
        self.clinic.save()
        self.auth()
        resp = self.client.post(f"/api/recall-rules/{rule.id}/run")
        self.assertEqual(resp.status_code, 400)

    def test_campaign_list(self):
        from apps.messaging.models import RecallCampaign

        rule = self._rule()
        RecallCampaign.objects.create(clinic=self.clinic, rule=rule, eligible=5)
        self.auth()
        resp = self.client.get("/api/recall-campaigns")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["eligible"], 5)


class QualityExportTests(ApiBase):
    def _conv(self, *, last_days_ago=1, corrected=0, prompt_version="booking_v1"):
        conv = Conversation.objects.create(
            clinic=self.clinic, patient=self.patient, channel="whatsapp",
            false_confirmation_count=corrected, prompt_version=prompt_version,
            last_message_at=timezone.now() - timedelta(days=last_days_ago),
        )
        return conv

    def _msg(self, conv, direction, body, days_ago=1):
        m = conv.messages.create(
            clinic=self.clinic, channel="whatsapp", direction=direction, body=body
        )
        conv.messages.filter(id=m.id).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
        return m

    def test_export_includes_escalated_and_corrected(self):
        from apps.api import quality

        escalated = self._conv()
        EscalationTicket.objects.create(
            clinic=self.clinic, conversation=escalated, reason="false_confirmation:book"
        )
        self._msg(escalated, "in", "book me please")
        self._msg(escalated, "out", "all booked!")

        corrected = self._conv(corrected=1)
        clean = self._conv()  # neither escalated nor corrected → excluded

        start = timezone.now() - timedelta(days=7)
        data = quality.export_review_dataset(self.clinic, start, timezone.now())
        ids = {c["conversation_id"] for c in data}
        self.assertEqual(ids, {escalated.id, corrected.id})
        self.assertNotIn(clean.id, ids)
        # Escalated (with a ticket) sorts before the merely-corrected one.
        self.assertEqual(data[0]["conversation_id"], escalated.id)
        self.assertEqual(data[0]["escalations"][0]["reason"], "false_confirmation:book")
        self.assertEqual([m["role"] for m in data[0]["messages"]], ["patient", "bot"])

    def test_export_respects_window(self):
        from apps.api import quality

        old = self._conv(last_days_ago=30, corrected=1)  # outside 7-day window
        start = timezone.now() - timedelta(days=7)
        data = quality.export_review_dataset(self.clinic, start, timezone.now())
        self.assertNotIn(old.id, {c["conversation_id"] for c in data})

    def test_endpoint_requires_auth(self):
        self.assertEqual(self.client.get("/api/quality/export").status_code, 403)

    def test_endpoint_returns_dataset(self):
        conv = self._conv(corrected=2)
        self.auth()
        resp = self.client.get("/api/quality/export")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["conversations"][0]["false_confirmation_count"], 2)


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
