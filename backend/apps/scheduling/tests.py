from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.clinics.models import Clinic, Patient

from .engine import (
    available_slots,
    book_slot,
    cancel_appointment,
    decode_token,
    reschedule_slot,
)
from .models import (
    Appointment,
    AppointmentStatus,
    Practitioner,
    ScheduleException,
    ScheduleRule,
    Service,
)

NY = ZoneInfo("America/New_York")


class SchedulingBase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            name="Bright Smiles",
            slug="bright-smiles",
            timezone="America/New_York",
            min_notice_minutes=120,
            slot_granularity_minutes=15,
            booking_horizon_days=60,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15551230000", name="Alex"
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Cleaning", duration_min=30, buffer_after_min=0
        )
        # A weekday comfortably in the future to dodge min-notice / horizon edges.
        self.target = (timezone.now().astimezone(NY) + timedelta(days=10)).date()
        ScheduleRule.objects.create(
            clinic=self.clinic,
            weekday=self.target.weekday(),
            start_time="09:00",
            end_time="17:00",
        )

    def slots(self, **kw):
        kw.setdefault("start_date", self.target)
        kw.setdefault("end_date", self.target)
        return available_slots(self.clinic, self.service, **kw)


class SlotComputationTests(SchedulingBase):
    def test_generates_slots_within_hours(self):
        slots = self.slots(limit=6)
        self.assertEqual(len(slots), 6)
        first_local = slots[0].start.astimezone(NY)
        self.assertEqual((first_local.hour, first_local.minute), (9, 0))
        # 15-min granularity
        second_local = slots[1].start.astimezone(NY)
        self.assertEqual((second_local.hour, second_local.minute), (9, 15))

    def test_timezone_offset_is_correct(self):
        slot = self.slots(limit=1)[0]
        expected_utc = datetime.combine(
            self.target, datetime.min.time(), tzinfo=NY
        ).replace(hour=9).astimezone(ZoneInfo("UTC"))
        self.assertEqual(slot.start, expected_utc)

    def test_existing_appointment_blocks_slot(self):
        start = datetime.combine(self.target, datetime.min.time(), tzinfo=NY).replace(hour=9)
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            service=self.service,
            starts_at=start.astimezone(ZoneInfo("UTC")),
            ends_at=(start + timedelta(minutes=30)).astimezone(ZoneInfo("UTC")),
            status=AppointmentStatus.CONFIRMED,
        )
        first_local = self.slots(limit=1)[0].start.astimezone(NY)
        self.assertEqual((first_local.hour, first_local.minute), (9, 30))

    def test_buffer_after_is_respected(self):
        self.service.buffer_after_min = 15
        self.service.save()
        start = datetime.combine(self.target, datetime.min.time(), tzinfo=NY).replace(hour=9)
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            service=self.service,
            starts_at=start.astimezone(ZoneInfo("UTC")),
            ends_at=(start + timedelta(minutes=30)).astimezone(ZoneInfo("UTC")),
            status=AppointmentStatus.CONFIRMED,
        )
        # 9:30 would start inside the buffer window (ends 9:45) -> first free is 9:45.
        first_local = self.slots(limit=1)[0].start.astimezone(NY)
        self.assertEqual((first_local.hour, first_local.minute), (9, 45))

    def test_closed_exception_yields_no_slots(self):
        ScheduleException.objects.create(
            clinic=self.clinic, date=self.target, is_closed=True, reason="Holiday"
        )
        self.assertEqual(self.slots(), [])

    def test_altered_hours_exception(self):
        ScheduleException.objects.create(
            clinic=self.clinic,
            date=self.target,
            is_closed=False,
            start_time="13:00",
            end_time="15:00",
        )
        slots = self.slots(limit=10)
        first_local = slots[0].start.astimezone(NY)
        last_local = slots[-1].start.astimezone(NY)
        self.assertEqual(first_local.hour, 13)
        self.assertLess(last_local.hour, 15)

    def test_cancelled_appointment_frees_slot(self):
        start = datetime.combine(self.target, datetime.min.time(), tzinfo=NY).replace(hour=9)
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            service=self.service,
            starts_at=start.astimezone(ZoneInfo("UTC")),
            ends_at=(start + timedelta(minutes=30)).astimezone(ZoneInfo("UTC")),
            status=AppointmentStatus.CANCELLED,
        )
        first_local = self.slots(limit=1)[0].start.astimezone(NY)
        self.assertEqual(first_local.hour, 9)

    def test_time_preference_filters_afternoon(self):
        slots = self.slots(limit=6, time_preference="afternoon")
        for s in slots:
            self.assertGreaterEqual(s.start.astimezone(NY).hour, 12)


class BookingTests(SchedulingBase):
    def test_book_slot_success(self):
        token = self.slots(limit=1)[0].token
        result = book_slot(self.clinic, self.patient, token)
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.appointment)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_double_book_same_slot_fails_with_alternatives(self):
        token = self.slots(limit=1)[0].token
        first = book_slot(self.clinic, self.patient, token)
        self.assertTrue(first.ok)

        other = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15559999999", name="Bo"
        )
        second = book_slot(self.clinic, other, token)
        self.assertFalse(second.ok)
        self.assertEqual(second.error, "slot_taken")
        self.assertTrue(second.alternatives)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_invalid_token_rejected(self):
        result = book_slot(self.clinic, self.patient, "not-a-real-token")
        self.assertFalse(result.ok)
        self.assertTrue(result.error.startswith("invalid_slot"))

    def test_token_round_trip(self):
        slot = self.slots(limit=1)[0]
        decoded = decode_token(slot.token)
        self.assertEqual(decoded.service_id, self.service.id)
        self.assertEqual(decoded.start, slot.start)


class RescheduleTests(SchedulingBase):
    def _book_first(self):
        token = self.slots(limit=1)[0].token
        result = book_slot(self.clinic, self.patient, token)
        self.assertTrue(result.ok)
        return result.appointment

    def test_reschedule_moves_appointment(self):
        appt = self._book_first()  # 9:00
        # A later free slot on the same day.
        new_slot = self.slots(limit=6)[3]
        result = reschedule_slot(self.clinic, self.patient, appt.id, new_slot.token)
        self.assertTrue(result.ok)
        self.assertEqual(result.appointment.starts_at, new_slot.start)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.RESCHEDULED)
        # Exactly one active appointment remains.
        self.assertEqual(
            Appointment.objects.filter(
                status__in=(AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
            ).count(),
            1,
        )

    def test_reschedule_frees_the_old_slot(self):
        appt = self._book_first()  # 9:00 taken
        new_slot = self.slots(limit=6)[3]
        reschedule_slot(self.clinic, self.patient, appt.id, new_slot.token)
        # 9:00 should now be offered again.
        first_local = self.slots(limit=1)[0].start.astimezone(NY)
        self.assertEqual((first_local.hour, first_local.minute), (9, 0))

    def test_reschedule_to_taken_slot_fails_with_alternatives(self):
        appt = self._book_first()  # patient at 9:00
        other = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15557778888", name="Bo"
        )
        taken = self.slots(limit=6)[3]
        book_slot(self.clinic, other, taken.token)  # someone else grabs it
        result = reschedule_slot(self.clinic, self.patient, appt.id, taken.token)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "slot_taken")
        self.assertTrue(result.alternatives)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)  # untouched

    def test_reschedule_unknown_appointment(self):
        result = reschedule_slot(
            self.clinic, self.patient, 999999, self.slots(limit=1)[0].token
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "appointment_not_found")

    def test_reschedule_other_patients_appointment_is_rejected(self):
        appt = self._book_first()
        intruder = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15550001111", name="Mal"
        )
        new_slot = self.slots(limit=6)[3]
        result = reschedule_slot(self.clinic, intruder, appt.id, new_slot.token)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "appointment_not_found")


class CancelTests(SchedulingBase):
    def _book_first(self):
        token = self.slots(limit=1)[0].token
        return book_slot(self.clinic, self.patient, token).appointment

    def test_cancel_frees_slot(self):
        appt = self._book_first()  # 9:00
        result = cancel_appointment(self.clinic, self.patient, appt.id, reason="sick")
        self.assertTrue(result.ok)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)
        self.assertIn("sick", appt.notes)
        first_local = self.slots(limit=1)[0].start.astimezone(NY)
        self.assertEqual((first_local.hour, first_local.minute), (9, 0))

    def test_cancel_unknown_appointment(self):
        result = cancel_appointment(self.clinic, self.patient, 999999)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "appointment_not_found")

    def test_cancel_other_patients_appointment_is_rejected(self):
        appt = self._book_first()
        intruder = Patient.objects.create(
            clinic=self.clinic, phone_e164="+15550002222", name="Mal"
        )
        result = cancel_appointment(self.clinic, intruder, appt.id)
        self.assertFalse(result.ok)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)


class PractitionerScopingTests(SchedulingBase):
    def test_service_requires_practitioner_uses_per_doctor_rules(self):
        self.service.requires_practitioner = True
        self.service.save()
        ScheduleRule.objects.all().delete()  # drop clinic-wide rule
        doc = Practitioner.objects.create(clinic=self.clinic, name="Dr. Smith")
        ScheduleRule.objects.create(
            clinic=self.clinic,
            practitioner=doc,
            weekday=self.target.weekday(),
            start_time="10:00",
            end_time="12:00",
        )
        slots = self.slots(limit=3)
        self.assertTrue(slots)
        self.assertTrue(all(s.practitioner_id == doc.id for s in slots))
        self.assertEqual(slots[0].start.astimezone(NY).hour, 10)
