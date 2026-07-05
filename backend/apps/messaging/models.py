from django.db import models

from apps.clinics.models import Clinic


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
    channel = models.CharField(max_length=16, choices=Channel.choices)
    direction = models.CharField(max_length=4, choices=Direction.choices)
    provider_message_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    from_number = models.CharField(max_length=32, blank=True)
    to_number = models.CharField(max_length=32, blank=True)
    body = models.TextField(blank=True)
    message_type = models.CharField(max_length=16, default="text")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["clinic", "created_at"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.channel}/{self.direction}] {self.body[:40]}"
