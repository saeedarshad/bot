from django.db import models


class Clinic(models.Model):
    """A single tenant. `clinic_id` lives on every domain table from day 1
    so multi-tenancy (later) is a config change, not a rewrite."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    timezone = models.CharField(max_length=64, default="America/New_York")
    currency = models.CharField(max_length=8, default="USD")
    phone_display = models.CharField(max_length=40, blank=True)
    emergency_phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True)
    maps_link = models.URLField(blank=True)
    languages = models.JSONField(default=list)  # e.g. ["en"]

    # WhatsApp Cloud API routing: inbound webhooks are matched by phone_number_id.
    whatsapp_phone_number_id = models.CharField(
        max_length=64, blank=True, db_index=True
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Booking policy (per-clinic config surfaced to patients).
    booking_horizon_days = models.PositiveIntegerField(default=30)
    min_notice_minutes = models.PositiveIntegerField(default=120)
    slot_granularity_minutes = models.PositiveIntegerField(default=15)
    cancellation_policy = models.CharField(max_length=255, blank=True)
    new_patient_form_url = models.URLField(blank=True)
    accepted_insurance = models.JSONField(default=list)  # e.g. ["Delta Dental"]

    # Reminders / business-initiated messaging.
    reminders_enabled = models.BooleanField(default=True)
    # No-show recovery sequence (same-day gentle message + 2-day rebook offer).
    # Subordinate to reminders_enabled — off means no recovery messages queue.
    no_show_recovery_enabled = models.BooleanField(default=True)
    # Where the daily owner digest is sent (clinic owner/manager, not a patient).
    # Blank disables the digest for this clinic.
    owner_phone_e164 = models.CharField(max_length=32, blank=True)
    owner_digest_hour = models.PositiveSmallIntegerField(default=8)  # clinic-local send hour
    # TCPA quiet hours: automated messages only send between these clinic-local
    # times. A message due outside the window is deferred to the next open window,
    # never dropped.
    quiet_hours_start = models.TimeField(default="08:00")  # earliest send (local)
    quiet_hours_end = models.TimeField(default="21:00")  # latest send (local)

    def __str__(self) -> str:
        return self.name


class Channel(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    SMS = "sms", "SMS"


class Patient(models.Model):
    """A person who has texted the clinic. Name + phone + appointment at a named
    clinic is PHID; treat with care. Unique per (clinic, phone)."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="patients")
    phone_e164 = models.CharField(max_length=32)
    preferred_channel = models.CharField(
        max_length=16, choices=Channel.choices, default=Channel.WHATSAPP
    )
    name = models.CharField(max_length=200, blank=True)
    language_pref = models.CharField(max_length=8, default="en")
    notes = models.TextField(blank=True)
    no_show_count = models.PositiveIntegerField(default=0)

    # TCPA consent trail (captured before any business-initiated message).
    sms_consent_at = models.DateTimeField(null=True, blank=True)
    sms_consent_source = models.CharField(max_length=64, blank=True)
    sms_consent_text = models.TextField(blank=True)
    opted_out_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "phone_e164"], name="uniq_clinic_phone"
            )
        ]
        indexes = [models.Index(fields=["clinic", "phone_e164"])]

    def __str__(self) -> str:
        return f"{self.name or self.phone_e164} @ {self.clinic_id}"
