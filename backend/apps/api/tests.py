from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clinics.models import Clinic, Patient
from apps.conversations.models import Conversation, EscalationTicket
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
