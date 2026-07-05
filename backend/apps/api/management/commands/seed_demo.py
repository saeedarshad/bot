"""Seed a demo clinic, staff login, services, hours, and FAQs. Idempotent."""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.clinics.models import Clinic
from apps.conversations.models import FAQEntry
from apps.scheduling.models import Practitioner, ScheduleRule, Service

DEMO_USER = "demo"
DEMO_PASS = "demo12345"


class Command(BaseCommand):
    help = "Create/refresh the demo clinic and a staff login."

    def handle(self, *args, **options):
        clinic, _ = Clinic.objects.get_or_create(
            slug="bright-smiles",
            defaults={"name": "Bright Smiles Dental"},
        )
        clinic.name = "Bright Smiles Dental"
        clinic.timezone = "America/New_York"
        clinic.currency = "USD"
        clinic.phone_display = "(555) 010-2020"
        clinic.emergency_phone = "(555) 911-0000"
        clinic.address = "120 Market St, Springfield, IL"
        clinic.maps_link = "https://maps.google.com/?q=120+Market+St+Springfield+IL"
        clinic.languages = ["en"]
        clinic.cancellation_policy = "24-hour notice required or a $50 fee applies."
        clinic.new_patient_form_url = "https://brightsmiles.example.com/new-patient"
        clinic.accepted_insurance = ["Delta Dental", "Cigna", "MetLife"]
        clinic.whatsapp_phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "") or clinic.whatsapp_phone_number_id
        clinic.is_active = True
        clinic.save()

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=DEMO_USER, defaults={"is_staff": True}
        )
        user.is_staff = True
        user.set_password(DEMO_PASS)
        user.save()

        practitioner, _ = Practitioner.objects.get_or_create(
            clinic=clinic, name="Dr. Rivera", defaults={"title": "DDS"}
        )

        services = [
            ("Cleaning", 30, "from $120", 0),
            ("New Patient Exam", 45, "from $95", 10),
            ("Whitening", 60, "from $350", 0),
            ("Root Canal Consult", 30, "from $200", 10),
        ]
        for name, dur, price, buffer in services:
            Service.objects.get_or_create(
                clinic=clinic,
                name=name,
                defaults={"duration_min": dur, "price_display": price, "buffer_after_min": buffer},
            )

        # Mon–Fri 9:00–17:00 clinic-wide.
        for weekday in range(0, 5):
            ScheduleRule.objects.get_or_create(
                clinic=clinic, practitioner=None, weekday=weekday,
                start_time="09:00", end_time="17:00",
            )

        faqs = [
            ("hours open close time", "We're open Monday to Friday, 9 AM to 5 PM.", "hours"),
            ("location address where parking directions",
             "We're at 120 Market St, Springfield, IL — free parking in the rear lot.", "location"),
            ("insurance delta cigna metlife accept coverage",
             "We accept Delta Dental, Cigna, and MetLife. For coverage details, our front desk can help.",
             "insurance"),
            ("payment pay card cash cost",
             "We accept cash and all major cards. Exact pricing is confirmed at your visit.", "payment"),
            ("doctor dentist who practitioner",
             "Dr. Rivera, DDS, sees our patients.", "staff"),
        ]
        for patterns, answer, category in faqs:
            FAQEntry.objects.get_or_create(
                clinic=clinic, category=category,
                defaults={"question_patterns": patterns, "answer_en": answer},
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded clinic '{clinic.name}' (id={clinic.id}). "
            f"Login: {DEMO_USER} / {DEMO_PASS}. "
            f"whatsapp_phone_number_id={clinic.whatsapp_phone_number_id or '(unset)'}"
        ))
