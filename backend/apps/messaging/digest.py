"""Daily owner digest: a short morning summary of the day's schedule for the
clinic owner/manager. Text-only and business-facing (goes to the clinic's own
number, never a patient)."""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time
from zoneinfo import ZoneInfo

from apps.clinics.models import Clinic
from apps.scheduling.models import ACTIVE_STATUSES, Appointment

from .models import ScheduledMessageKind, ScheduledMessageStatus


def _day_bounds_utc(clinic: Clinic, on_date: date_cls):
    tz = ZoneInfo(clinic.timezone)
    start = datetime.combine(on_date, time.min, tzinfo=tz)
    end = start.replace(hour=23, minute=59, second=59)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


def build_owner_digest(clinic: Clinic, on_date: date_cls) -> str:
    """A one-message summary of `on_date`'s bookings: total, first arrival, and how
    many are still unconfirmed after their 24h reminder (at-risk)."""
    tz = ZoneInfo(clinic.timezone)
    start_utc, end_utc = _day_bounds_utc(clinic, on_date)
    appts = list(
        Appointment.objects.filter(
            clinic=clinic,
            status__in=ACTIVE_STATUSES,
            starts_at__gte=start_utc,
            starts_at__lte=end_utc,
        )
        .select_related("patient")
        .prefetch_related("scheduled_messages")
        .order_by("starts_at")
    )

    if not appts:
        return f"Good morning! No appointments booked at {clinic.name} today."

    at_risk = sum(1 for a in appts if _is_at_risk(a))
    first = appts[0].starts_at.astimezone(tz).strftime("%-I:%M %p")
    lines = [
        f"Good morning! {clinic.name} today: {len(appts)} "
        f"appointment{'s' if len(appts) != 1 else ''}, first at {first}.",
    ]
    if at_risk:
        lines.append(
            f"{at_risk} still unconfirmed after their reminder — worth a nudge."
        )
    return " ".join(lines)


def _is_at_risk(appt: Appointment) -> bool:
    if appt.patient_confirmed_at is not None:
        return False
    return any(
        m.kind == ScheduledMessageKind.REMINDER_24H
        and m.status == ScheduledMessageStatus.SENT
        for m in appt.scheduled_messages.all()
    )
