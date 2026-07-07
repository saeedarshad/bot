"""Recall campaigns: bring patients back N days after a service (a MARKETING
message). Eligibility and cost are deterministic Python; sending goes through a
dedicated outbox (RecallSend) that mirrors the reminder/waitlist dispatch
discipline — recalls aren't tied to an appointment, so they can't ride the
appointment-keyed ScheduledMessage.

Marketing is paid and regulated: eligibility hard-excludes opted-out patients
and anyone inside the clinic's marketing frequency cap, cost is projected before
any send, and the dispatcher re-checks opt-out so a STOP mid-campaign suppresses
the rest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from apps.clinics.models import Patient
from apps.scheduling.models import ACTIVE_STATUSES, Appointment, AppointmentStatus

from .channels import get_channel
from .costs import unit_cost
from .models import (
    Direction,
    Message,
    MessageCategory,
    RecallCampaign,
    RecallCampaignStatus,
    RecallRule,
    RecallSend,
    RecallSendStatus,
)
from .reminders import next_send_time

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5
RECALL_LANG = "en_US"


def eligible_patients(rule: RecallRule) -> list[Patient]:
    """Patients due for this recall: their most-recent *completed* appointment for
    the rule's service falls in the [interval ± window] window, they haven't opted
    out, they're outside the marketing frequency cap, and they don't already have
    a future booking for that service. Deterministic — no LLM, no side effects."""
    clinic = rule.clinic
    now = timezone.now()
    interval = timedelta(days=rule.interval_days)
    window = timedelta(days=rule.window_days)
    older_bound = now - interval - window
    newer_bound = now - interval + window

    # Latest completed visit per patient for this service, kept only if that visit
    # lands in the recall window.
    due = (
        Appointment.objects.filter(
            clinic=clinic, service=rule.service, status=AppointmentStatus.COMPLETED
        )
        .values("patient_id")
        .annotate(last=models.Max("starts_at"))
        .filter(last__gte=older_bound, last__lte=newer_bound)
    )
    due_ids = [row["patient_id"] for row in due]
    if not due_ids:
        return []

    # Patients already re-booked for this service don't need a nudge.
    future_booked = set(
        Appointment.objects.filter(
            clinic=clinic,
            service=rule.service,
            status__in=ACTIVE_STATUSES,
            starts_at__gte=now,
        ).values_list("patient_id", flat=True)
    )

    cap_cutoff = now - timedelta(days=clinic.marketing_min_interval_days)
    patients = Patient.objects.filter(
        id__in=due_ids, opted_out_at__isnull=True
    ).filter(
        models.Q(last_marketing_at__isnull=True) | models.Q(last_marketing_at__lt=cap_cutoff)
    )
    return [p for p in patients if p.id not in future_booked]


def marketing_unit_cost(clinic) -> Decimal:
    return unit_cost("whatsapp", MessageCategory.MARKETING)


def projected_cost(clinic, count: int) -> Decimal:
    return marketing_unit_cost(clinic) * count


@dataclass
class Preview:
    eligible: int
    projected_cost: Decimal
    sample: list[str]  # a few patient display names, for the confirm screen


def preview_campaign(rule: RecallRule) -> Preview:
    patients = eligible_patients(rule)
    sample = [(p.name or p.phone_e164) for p in patients[:5]]
    return Preview(
        eligible=len(patients),
        projected_cost=projected_cost(rule.clinic, len(patients)),
        sample=sample,
    )


def run_campaign(rule: RecallRule) -> RecallCampaign:
    """Materialize a campaign: snapshot eligibility + projected cost and enqueue a
    RecallSend per eligible patient (quiet-hours-clamped). The beat dispatcher
    drains the outbox; this returns immediately. Idempotent per patient via
    UNIQUE(campaign, patient)."""
    clinic = rule.clinic
    now = timezone.now()
    patients = eligible_patients(rule)
    with transaction.atomic():
        campaign = RecallCampaign.objects.create(
            clinic=clinic,
            rule=rule,
            status=RecallCampaignStatus.RUNNING,
            eligible=len(patients),
            projected_cost=projected_cost(clinic, len(patients)),
        )
        for patient in patients:
            RecallSend.objects.get_or_create(
                campaign=campaign,
                patient=patient,
                defaults={
                    "clinic": clinic,
                    "scheduled_for": next_send_time(clinic, now),
                },
            )
        if not patients:
            campaign.status = RecallCampaignStatus.COMPLETED
            campaign.completed_at = now
            campaign.save(update_fields=["status", "completed_at"])
    return campaign


def _recall_parts(send: RecallSend) -> tuple[str, str]:
    patient = send.patient
    name = (patient.name or "").strip()
    first = name.split()[0] if name else "there"
    return first, send.clinic.name


def build_recall_template(send: RecallSend) -> dict:
    """The clinic's approved marketing template with two body params (patient
    first name, clinic name). Template name is per-rule and clinic-configured."""
    first, clinic_name = _recall_parts(send)
    return {
        "name": send.campaign.rule.template_name,
        "language": RECALL_LANG,
        "body_params": [first, clinic_name],
    }


def build_recall_body(send: RecallSend) -> str:
    """Plain-text fallback. Honors the rule's override (with {name}/{clinic}
    placeholders) or a sensible default."""
    first, clinic_name = _recall_parts(send)
    override = send.campaign.rule.message_override
    if override:
        return override.replace("{name}", first).replace("{clinic}", clinic_name)
    return (
        f"Hi {first}, it's time for your next visit at {clinic_name}. "
        "Reply here to book — we'd love to see you again! Reply STOP to opt out."
    )


def dispatch_due_recalls(batch_size: int = 100) -> str:
    """Beat task body: send due recall rows. Same claiming discipline as the
    reminder dispatcher (row lock, quiet-hours deferral, retry). Opt-out is
    re-checked here so a STOP after enqueue suppresses the rest of the campaign."""
    now = timezone.now()
    sent = deferred = failed = skipped = 0

    with transaction.atomic():
        rows = list(
            RecallSend.objects.select_for_update(skip_locked=True)
            .filter(status=RecallSendStatus.PENDING, scheduled_for__lte=now)
            .select_related(
                "clinic", "patient", "campaign", "campaign__rule"
            )[:batch_size]
        )
        for row in rows:
            if not row.clinic.recalls_enabled:
                continue  # kill switch: leave pending, don't send
            if row.patient.opted_out_at is not None:
                _resolve(row, RecallSendStatus.SKIPPED, "patient_opted_out")
                _bump(row.campaign, "skipped")
                skipped += 1
                continue
            open_at = next_send_time(row.clinic, now)
            if open_at > now:
                row.scheduled_for = open_at
                row.save(update_fields=["scheduled_for", "updated_at"])
                deferred += 1
                continue
            if _send_recall(row):
                sent += 1
            else:
                failed += 1

    return f"sent={sent} deferred={deferred} failed={failed} skipped={skipped}"


def _send_recall(row: RecallSend) -> bool:
    from apps.conversations.inbound import get_conversation

    patient = row.patient
    channel_name = patient.preferred_channel or "whatsapp"
    body = build_recall_body(row)
    template = build_recall_template(row)
    row.attempts += 1
    try:
        channel = get_channel(channel_name)
        provider_id = channel.send_template(patient.phone_e164, body, template=template)
    except Exception as exc:  # noqa: BLE001 — record and let beat retry
        row.last_error = str(exc)[:2000]
        terminal = row.attempts >= _MAX_ATTEMPTS
        row.status = RecallSendStatus.FAILED if terminal else RecallSendStatus.PENDING
        row.save(update_fields=["attempts", "last_error", "status", "updated_at"])
        if terminal:
            _bump(row.campaign, "failed")
        logger.warning("Recall %s send failed: %s", row.id, exc)
        return False

    now = timezone.now()
    cost = unit_cost(channel_name, MessageCategory.MARKETING)
    conversation = get_conversation(row.clinic, patient, channel_name)
    Message.objects.create(
        clinic=row.clinic,
        conversation=conversation,
        channel=channel_name,
        direction=Direction.OUT,
        provider_message_id=provider_id,
        to_number=patient.phone_e164,
        body=body,
        message_type="template",
        category=MessageCategory.MARKETING,
        cost_amount=cost,
    )
    row.status = RecallSendStatus.SENT
    row.sent_at = now
    row.provider_message_id = provider_id or ""
    row.last_error = ""
    row.save(
        update_fields=[
            "status", "sent_at", "provider_message_id", "attempts",
            "last_error", "updated_at",
        ]
    )
    # Stamp the marketing frequency cap.
    Patient.objects.filter(id=patient.id).update(last_marketing_at=now)
    _bump(row.campaign, "sent", cost=cost)
    return True


def _resolve(row: RecallSend, status: str, error: str = "") -> None:
    row.status = status
    row.last_error = error
    row.save(update_fields=["status", "last_error", "updated_at"])


def _bump(campaign: RecallCampaign, field: str, cost: Decimal = Decimal("0")) -> None:
    """Increment a campaign counter (and actual_cost on a send), then complete the
    campaign once no sends remain pending."""
    updates = {field: models.F(field) + 1}
    if cost:
        updates["actual_cost"] = models.F("actual_cost") + cost
    RecallCampaign.objects.filter(id=campaign.id).update(**updates)
    if not campaign.sends.filter(status=RecallSendStatus.PENDING).exists():
        RecallCampaign.objects.filter(
            id=campaign.id, status=RecallCampaignStatus.RUNNING
        ).update(status=RecallCampaignStatus.COMPLETED, completed_at=timezone.now())
