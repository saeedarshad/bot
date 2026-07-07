from django.conf import settings
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

    # A/B prompt variant. Blank/"v1" → the default template; "v2" → the variant
    # (prompts/booking_system_v2.md). Lets us trial prompt changes per clinic.
    prompt_variant = models.CharField(max_length=16, blank=True)

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
    # Recall campaigns (marketing). Kill switch: a running campaign won't dispatch
    # while this is off.
    recalls_enabled = models.BooleanField(default=True)
    # Per-patient marketing frequency cap: no marketing message within this many
    # days of the patient's last one. Deliverability + TCPA hygiene.
    marketing_min_interval_days = models.PositiveSmallIntegerField(default=30)
    # Where the daily owner digest is sent (clinic owner/manager, not a patient).
    # Blank disables the digest for this clinic.
    owner_phone_e164 = models.CharField(max_length=32, blank=True)
    owner_digest_hour = models.PositiveSmallIntegerField(default=8)  # clinic-local send hour
    # TCPA quiet hours: automated messages only send between these clinic-local
    # times. A message due outside the window is deferred to the next open window,
    # never dropped.
    quiet_hours_start = models.TimeField(default="08:00")  # earliest send (local)
    quiet_hours_end = models.TimeField(default="21:00")  # latest send (local)

    @property
    def service_suspended(self) -> bool:
        """True when the clinic's subscription is not active (unpaid/cancelled).
        A clinic with no subscription row is treated as active (fresh installs are
        backfilled + seeded with one). Drives dashboard + bot cutoff."""
        sub = getattr(self, "subscription", None)
        return sub is not None and not sub.is_active

    def __str__(self) -> str:
        return self.name


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"  # unpaid — dashboard + bot cut off
    CANCELLED = "cancelled", "Cancelled"  # ended — same effect as suspended


class Subscription(models.Model):
    """A clinic's plan + pay status, managed by hand by the platform operator
    (billing is entirely off-platform — no processor, no self-serve). Only ACTIVE
    keeps the clinic's dashboard and bot alive; SUSPENDED/CANCELLED cut both off.
    `paid_through` is informational (the operator flips `status` deliberately)."""

    clinic = models.OneToOneField(
        Clinic, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.CharField(max_length=40, default="demo")
    status = models.CharField(
        max_length=16,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
    )
    paid_through = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_active(self) -> bool:
        return self.status == SubscriptionStatus.ACTIVE

    def __str__(self) -> str:
        return f"{self.clinic_id}: {self.plan} ({self.status})"


class UserProfile(models.Model):
    """Binds a Django auth User to exactly one Clinic — the tenant boundary for
    staff. Every dashboard request resolves its clinic through this profile, so a
    staff user can only ever see their own clinic's data (Phase 4 multi-tenancy).

    A superuser (the platform operator) has no profile and is not clinic-scoped;
    they manage clinics through Django admin."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="staff_profiles"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user} @ {self.clinic_id}"


class MonthlyReport(models.Model):
    """A frozen snapshot of one clinic-local calendar month's analytics — the
    artifact shown at renewal. `data` holds the full compute_analytics() dict so
    the numbers are stable even as later data changes. UNIQUE(clinic, year, month)
    makes generation idempotent (the beat task get_or_creates the month)."""

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="monthly_reports"
    )
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()  # 1..12, clinic-local
    data = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "year", "month"], name="uniq_clinic_report_month"
            )
        ]
        ordering = ["-year", "-month"]

    def __str__(self) -> str:
        return f"report {self.clinic_id} {self.year}-{self.month:02d}"


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
    # The practitioner this patient usually sees ("my usual with Dr. Rivera").
    # Set from their most recent practitioner booking; the bot offers them first.
    preferred_practitioner = models.ForeignKey(
        "scheduling.Practitioner",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="preferring_patients",
    )

    # TCPA consent trail (captured before any business-initiated message).
    sms_consent_at = models.DateTimeField(null=True, blank=True)
    sms_consent_source = models.CharField(max_length=64, blank=True)
    sms_consent_text = models.TextField(blank=True)
    opted_out_at = models.DateTimeField(null=True, blank=True)
    # When the patient last received a MARKETING message (recall). Drives the
    # per-clinic marketing frequency cap; set at send time.
    last_marketing_at = models.DateTimeField(null=True, blank=True)

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
