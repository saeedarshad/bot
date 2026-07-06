from django.db import models

from apps.clinics.models import Clinic
from apps.conversations.models import Conversation
from apps.scheduling.models import Appointment


class Channel(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    SMS = "sms", "SMS"


class Direction(models.TextChoices):
    IN = "in", "Inbound"
    OUT = "out", "Outbound"


class MessageCategory(models.TextChoices):
    """WhatsApp conversation categories, used to price outbound messages. Inbound
    and in-session ("service") replies are effectively free; business-initiated
    reminders/templates fall under "utility"."""

    SERVICE = "service", "Service (in-session)"
    UTILITY = "utility", "Utility"
    MARKETING = "marketing", "Marketing"
    AUTHENTICATION = "authentication", "Authentication"


class Message(models.Model):
    """Every inbound and outbound message is logged here. `provider_message_id`
    is unique so we can dedupe retried webhooks (idempotency)."""

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, null=True, blank=True, related_name="messages"
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
    )
    channel = models.CharField(max_length=16, choices=Channel.choices)
    direction = models.CharField(max_length=4, choices=Direction.choices)
    provider_message_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    from_number = models.CharField(max_length=32, blank=True)
    to_number = models.CharField(max_length=32, blank=True)
    body = models.TextField(blank=True)
    message_type = models.CharField(max_length=16, default="text")
    # Tappable options payload for interactive outbound messages (null for plain text).
    interactive = models.JSONField(null=True, blank=True)
    # Billing: category drives the estimated cost, snapshotted at send time so a
    # later rate change doesn't rewrite history.
    category = models.CharField(
        max_length=16, choices=MessageCategory.choices, default=MessageCategory.SERVICE
    )
    cost_amount = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["clinic", "created_at"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.channel}/{self.direction}] {self.body[:40]}"


class ScheduledMessageKind(models.TextChoices):
    CONFIRMATION = "confirmation", "Booking confirmation"
    REMINDER_24H = "reminder_24h", "24-hour reminder"
    REMINDER_2H = "reminder_2h", "2-hour reminder"
    THANK_YOU = "thank_you", "Post-appointment thank-you"


class ScheduledMessageStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"  # appointment cancelled/rescheduled before send


class ScheduledMessage(models.Model):
    """Outbox row for a business-initiated message tied to an appointment.

    Idempotency is structural: UNIQUE(appointment, kind) means a given reminder
    can exist at most once, so it can never be sent twice. The dispatcher claims
    due rows under a row lock (`select_for_update(skip_locked=True)`), so parallel
    workers never double-send, and a crashed worker leaves the row `pending` to be
    retried — never silently skipped.
    """

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="scheduled_messages"
    )
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name="scheduled_messages"
    )
    kind = models.CharField(max_length=24, choices=ScheduledMessageKind.choices)
    status = models.CharField(
        max_length=12,
        choices=ScheduledMessageStatus.choices,
        default=ScheduledMessageStatus.PENDING,
    )
    scheduled_for = models.DateTimeField()  # UTC; earliest moment it may be sent
    sent_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=128, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "kind"], name="uniq_appointment_kind"
            )
        ]
        indexes = [models.Index(fields=["status", "scheduled_for"])]
        ordering = ["scheduled_for"]

    def __str__(self) -> str:
        return f"{self.kind} for appt {self.appointment_id} [{self.status}]"


class OwnerDigest(models.Model):
    """One row per (clinic, local date) records that the daily owner digest was
    sent. `UNIQUE(clinic, date)` makes the send idempotent — the beat task claims
    the day via get_or_create, so the owner never gets two digests for one day."""

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="owner_digests"
    )
    date = models.DateField()  # clinic-local calendar date the digest covers
    body = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=128, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["clinic", "date"], name="uniq_clinic_digest_date")
        ]
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"digest {self.clinic_id} {self.date}"


class MessageRate(models.Model):
    """Per-message price estimate for a (channel, category). Global (not per-clinic)
    for now; the cost estimator reads the current rate to snapshot onto each
    outbound Message. Missing rate → treated as free (0)."""

    channel = models.CharField(
        max_length=16, choices=Channel.choices, default=Channel.WHATSAPP
    )
    category = models.CharField(max_length=16, choices=MessageCategory.choices)
    unit_cost = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    currency = models.CharField(max_length=8, default="USD")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "category"], name="uniq_channel_category_rate"
            )
        ]

    def __str__(self) -> str:
        return f"{self.channel}/{self.category} {self.unit_cost} {self.currency}"
