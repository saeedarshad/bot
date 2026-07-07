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
    # Meta delivery lifecycle for outbound messages: sent → delivered → read, or
    # failed. Blank until the first status webhook arrives (and for inbound rows).
    delivery_status = models.CharField(max_length=16, blank=True)
    delivery_error = models.TextField(blank=True)
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
    # No-show recovery sequence. Post-appointment kinds: they are queued when the
    # appointment becomes a no-show, so they must survive reconcile-skip (which
    # only touches _PRE_APPOINTMENT_KINDS).
    RECOVERY_SAMEDAY = "recovery_sameday", "No-show same-day recovery"
    RECOVERY_REBOOK = "recovery_rebook", "No-show rebooking offer"


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


class WaitlistOfferStatus(models.TextChoices):
    PENDING = "pending", "Pending"  # queued, not yet sent (quiet hours / retry)
    SENT = "sent", "Sent"  # offer out; short hold running (offer_expires_at)
    ACCEPTED = "accepted", "Accepted"  # patient tapped first and booked
    EXPIRED = "expired", "Expired"  # hold lapsed, slot lost, or send gave up


class WaitlistOffer(models.Model):
    """Outbox row for a "this slot just opened" offer to one waitlisted patient.

    Follows the ScheduledMessage pattern (row first, claim under lock, quiet
    hours, retry) but keyed to a waitlist entry + the freed appointment:
    UNIQUE(waitlist, freed_appointment) makes re-processing the same freed slot
    structurally unable to double-offer. First-confirm-wins is enforced by
    book_slot's advisory lock + live re-check at tap time, never here."""

    clinic = models.ForeignKey(
        Clinic, on_delete=models.CASCADE, related_name="waitlist_offers"
    )
    waitlist = models.ForeignKey(
        "scheduling.Waitlist", on_delete=models.CASCADE, related_name="offers"
    )
    freed_appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name="waitlist_offers"
    )
    # Engine slot token for the freed slot — re-validated at booking, so a stale
    # offer can never book over someone.
    slot_token = models.CharField(max_length=160)
    slot_starts_at = models.DateTimeField()
    status = models.CharField(
        max_length=12,
        choices=WaitlistOfferStatus.choices,
        default=WaitlistOfferStatus.PENDING,
    )
    scheduled_for = models.DateTimeField()  # UTC; earliest moment it may be sent
    sent_at = models.DateTimeField(null=True, blank=True)
    offer_expires_at = models.DateTimeField(null=True, blank=True)  # set at send
    provider_message_id = models.CharField(max_length=128, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["waitlist", "freed_appointment"],
                name="uniq_waitlist_freed_appointment",
            )
        ]
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["status", "offer_expires_at"]),
        ]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"offer {self.waitlist_id} for appt {self.freed_appointment_id} [{self.status}]"


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


class RecallRule(models.Model):
    """A clinic rule that periodically brings patients back: N days after a
    completed `service`, they become eligible for a recall (a MARKETING message).
    Firing is never automatic — staff preview eligibility + projected cost, then
    run a campaign. `template_name` is the clinic's Meta-approved marketing
    template; `message_override` customizes the plain-text fallback."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="recall_rules")
    name = models.CharField(max_length=120, blank=True)
    service = models.ForeignKey(
        "scheduling.Service", on_delete=models.CASCADE, related_name="recall_rules"
    )
    interval_days = models.PositiveIntegerField()  # e.g. 180 for a 6-month recall
    window_days = models.PositiveSmallIntegerField(default=7)  # ± eligibility window
    template_name = models.CharField(max_length=64)
    message_override = models.TextField(blank=True)  # {name}/{clinic} placeholders
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or f"recall {self.service_id} +{self.interval_days}d"


class RecallCampaignStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class RecallCampaign(models.Model):
    """One run of a RecallRule. Records eligibility + cost so the numbers shown at
    confirm time are preserved. `projected_cost` is snapshotted at run; `actual_cost`
    and the sent/skipped/failed counts accrue as the outbox drains."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="recall_campaigns")
    rule = models.ForeignKey(RecallRule, on_delete=models.CASCADE, related_name="campaigns")
    status = models.CharField(
        max_length=12, choices=RecallCampaignStatus.choices,
        default=RecallCampaignStatus.RUNNING,
    )
    eligible = models.PositiveIntegerField(default=0)
    sent = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    projected_cost = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    actual_cost = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"campaign {self.rule_id} [{self.status}]"


class RecallSendStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"  # opted out after enqueue


class RecallSend(models.Model):
    """Outbox row for one recall message to one patient in a campaign.

    Mirrors the ScheduledMessage/WaitlistOffer discipline (claim under a row lock,
    quiet-hours deferral, retry) but keyed to (campaign, patient) since recalls
    aren't tied to an appointment. UNIQUE(campaign, patient) makes a re-run
    structurally unable to double-send within a campaign."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="recall_sends")
    campaign = models.ForeignKey(RecallCampaign, on_delete=models.CASCADE, related_name="sends")
    patient = models.ForeignKey(
        "clinics.Patient", on_delete=models.CASCADE, related_name="recall_sends"
    )
    status = models.CharField(
        max_length=12, choices=RecallSendStatus.choices, default=RecallSendStatus.PENDING
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
                fields=["campaign", "patient"], name="uniq_campaign_patient_recall"
            )
        ]
        indexes = [models.Index(fields=["status", "scheduled_for"])]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"recall {self.patient_id} campaign {self.campaign_id} [{self.status}]"


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
