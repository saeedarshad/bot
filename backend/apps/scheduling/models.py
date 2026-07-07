from django.db import models

from apps.clinics.models import Clinic, Patient


class Practitioner(models.Model):
    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="practitioners"
    )
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=100, blank=True)
    specialty = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Service(models.Model):
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=200)
    name_i18n = models.JSONField(default=dict, blank=True)
    duration_min = models.PositiveIntegerField(default=30)
    price_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_display = models.CharField(max_length=64, blank=True)  # e.g. "from $150"
    requires_practitioner = models.BooleanField(default=False)
    # Which practitioners can perform this service. Empty = any active
    # practitioner (no restriction). When non-empty, availability/booking are
    # limited to this set (see engine._candidate_practitioners).
    practitioners = models.ManyToManyField(
        "Practitioner", blank=True, related_name="services"
    )
    buffer_after_min = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class ScheduleRule(models.Model):
    """Recurring weekly working hours. `practitioner` null = applies clinic-wide.
    `weekday` uses Python's convention: Monday=0 .. Sunday=6."""

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="schedule_rules"
    )
    practitioner = models.ForeignKey(
        Practitioner,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="schedule_rules",
    )
    weekday = models.PositiveSmallIntegerField()  # 0=Mon .. 6=Sun
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self) -> str:
        return f"wd{self.weekday} {self.start_time}-{self.end_time}"


class ScheduleException(models.Model):
    """A one-off override for a specific date: closure or altered hours."""

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="schedule_exceptions"
    )
    practitioner = models.ForeignKey(
        Practitioner,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="schedule_exceptions",
    )
    date = models.DateField()
    is_closed = models.BooleanField(default=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)

    def __str__(self) -> str:
        return f"{self.date} {'closed' if self.is_closed else 'altered'}"


class TimePreference(models.TextChoices):
    ANY = "any", "Any time"
    MORNING = "morning", "Morning"
    AFTERNOON = "afternoon", "Afternoon"
    EVENING = "evening", "Evening"


class WaitlistStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    OFFERED = "offered", "Offered"  # a freed slot was offered; short hold running
    BOOKED = "booked", "Booked"
    EXPIRED = "expired", "Expired"  # desired window passed without a fill
    CANCELLED = "cancelled", "Cancelled"


class Waitlist(models.Model):
    """A patient waiting for a slot that wasn't available when they asked.

    Deterministic matching only (see engine.match_waitlist): when a cancellation
    frees a slot, the oldest active entries whose service/date window/practitioner/
    time preference fit are offered the slot, first-confirm-wins."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="waitlist")
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="waitlist_entries"
    )
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="waitlist_entries"
    )
    practitioner = models.ForeignKey(
        Practitioner,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="waitlist_entries",
    )
    # Desired window, clinic-local dates. Null bound = open-ended on that side.
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    time_preference = models.CharField(
        max_length=12, choices=TimePreference.choices, default=TimePreference.ANY
    )
    status = models.CharField(
        max_length=12, choices=WaitlistStatus.choices, default=WaitlistStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["clinic", "service", "status"])]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"waitlist {self.patient_id} svc {self.service_id} [{self.status}]"


class AppointmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "No-show"
    RESCHEDULED = "rescheduled", "Rescheduled"


class AppointmentSource(models.TextChoices):
    BOT = "bot", "Bot"
    DASHBOARD = "dashboard", "Dashboard"
    WALK_IN = "walk_in", "Walk-in"


# Statuses that occupy a time slot (block other bookings).
ACTIVE_STATUSES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


class Appointment(models.Model):
    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="appointments"
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="appointments"
    )
    practitioner = models.ForeignKey(
        Practitioner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name="appointments"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=AppointmentStatus.choices, default=AppointmentStatus.CONFIRMED
    )
    # Set when the patient actively confirms (taps Confirm / replies C to a
    # reminder). Distinct from `status=confirmed`, which is the booking's own
    # state — this tracks the patient's acknowledgement for at-risk detection.
    patient_confirmed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=16, choices=AppointmentSource.choices, default=AppointmentSource.BOT
    )
    # The no-show appointment this booking recovered, when the patient rebooked
    # off a recovery offer. Set by attribution (messaging), never by the LLM —
    # drives the "recovered bookings / revenue" metric.
    recovered_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recovered_bookings",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "starts_at"]),
            models.Index(fields=["practitioner", "starts_at"]),
        ]
        ordering = ["starts_at"]

    def __str__(self) -> str:
        return f"{self.service_id} {self.starts_at:%Y-%m-%d %H:%M} [{self.status}]"
