from django.db import models

from apps.clinics.models import Channel, Clinic, Patient


class ConversationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ESCALATED = "escalated", "Escalated"


class Conversation(models.Model):
    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="conversations"
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="conversations"
    )
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(
        max_length=16, choices=ConversationStatus.choices, default=ConversationStatus.ACTIVE
    )
    # When a human takes over, the bot goes silent until staff resolve the ticket.
    bot_paused = models.BooleanField(default=False)
    last_message_at = models.DateTimeField(null=True, blank=True)
    service_window_expires_at = models.DateTimeField(null=True, blank=True)
    prompt_version = models.CharField(max_length=32, blank=True)
    # How many turns the false-confirmation guardrail had to correct here. >0 marks
    # the conversation for the weekly quality review (prompt iteration dataset).
    false_confirmation_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["clinic", "patient"])]
        ordering = ["-last_message_at"]

    def __str__(self) -> str:
        return f"conv {self.pk} ({self.status})"


class FAQEntry(models.Model):
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="faqs")
    question_patterns = models.TextField(
        help_text="Newline-separated example phrasings / keywords."
    )
    answer_en = models.TextField()
    answers_i18n = models.JSONField(default=dict, blank=True)
    category = models.CharField(max_length=64, blank=True)

    def __str__(self) -> str:
        return f"{self.category}: {self.answer_en[:40]}"


class EscalationStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"


class EscalationTicket(models.Model):
    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="escalations"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="escalations"
    )
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16, choices=EscalationStatus.choices, default=EscalationStatus.OPEN
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ticket {self.pk} ({self.status})"
