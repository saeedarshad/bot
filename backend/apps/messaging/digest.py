"""Daily owner digest: a short morning summary of the day's schedule for the
clinic owner/manager. Business-facing (goes to the clinic's own number, never a
patient). Sent as a Meta-approved template outside the 24h window, with the
plain-text body as the fallback."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, time
from zoneinfo import ZoneInfo

from apps.clinics.models import Clinic
from apps.scheduling.models import ACTIVE_STATUSES, Appointment

from .models import ScheduledMessageKind, ScheduledMessageStatus

# Meta-approved template for the owner digest. Fixed shape (WhatsApp templates
# can't do conditionals), so every variable is always present — the zero-appt
# and at-risk cases are folded into the params, not the structure.
OWNER_DIGEST_TEMPLATE = "owner_daily_digest"
OWNER_DIGEST_LANG = "en_US"


@dataclass
class _DigestParts:
    clinic_name: str
    date_str: str
    count: int
    first_str: str
    note: str


def _day_bounds_utc(clinic: Clinic, on_date: date_cls):
    tz = ZoneInfo(clinic.timezone)
    start = datetime.combine(on_date, time.min, tzinfo=tz)
    end = start.replace(hour=23, minute=59, second=59)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


def _digest_parts(clinic: Clinic, on_date: date_cls) -> _DigestParts:
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
    count = len(appts)
    if count == 0:
        note = "Enjoy the quieter day."
        first_str = "none"
    else:
        at_risk = sum(1 for a in appts if _is_at_risk(a))
        first_str = appts[0].starts_at.astimezone(tz).strftime("%-I:%M %p")
        if at_risk:
            plural = "s" if at_risk != 1 else ""
            note = (
                f"{at_risk} still unconfirmed after their reminder{plural} — "
                "worth a nudge."
            )
        else:
            note = "All confirmed so far."
    return _DigestParts(
        clinic_name=clinic.name,
        date_str=on_date.strftime("%a, %b %-d"),
        count=count,
        first_str=first_str,
        note=note,
    )


def build_owner_digest(clinic: Clinic, on_date: date_cls) -> str:
    """Plain-text fallback (used when no template/creds). Kept in sync with the
    approved `owner_daily_digest` template wording."""
    p = _digest_parts(clinic, on_date)
    if p.count == 0:
        return f"Good morning! No appointments booked at {p.clinic_name} today."
    plural = "s" if p.count != 1 else ""
    text = (
        f"Good morning! {p.clinic_name} today: {p.count} appointment{plural}, "
        f"first at {p.first_str}."
    )
    if "unconfirmed" in p.note:
        text += f" {p.note}"
    return text


def build_owner_digest_template(clinic: Clinic, on_date: date_cls) -> dict:
    """Template spec for `send_template`: fixed body with five always-present
    params — clinic, date, count, first arrival, and a status note."""
    p = _digest_parts(clinic, on_date)
    return {
        "name": OWNER_DIGEST_TEMPLATE,
        "language": OWNER_DIGEST_LANG,
        "body_params": [p.clinic_name, p.date_str, str(p.count), p.first_str, p.note],
    }


def _is_at_risk(appt: Appointment) -> bool:
    if appt.patient_confirmed_at is not None:
        return False
    return any(
        m.kind == ScheduledMessageKind.REMINDER_24H
        and m.status == ScheduledMessageStatus.SENT
        for m in appt.scheduled_messages.all()
    )
