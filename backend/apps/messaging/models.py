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
