"""Reminder scheduling: reconcile an appointment's outbox rows and build the
message body for each kind.

The scheduling engine stays free of any messaging concern — reconciliation is
driven by a post_save signal on Appointment (see apps.py). Everything here is
idempotent: creating rows uses get_or_create on the UNIQUE(appointment, kind),
and cancelling only touches rows that haven't been sent yet.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.clinics.models import Clinic
from apps.scheduling.models import ACTIVE_STATUSES, Appointment

from .models import ScheduledMessage, ScheduledMessageKind, ScheduledMessageStatus

# How far before the appointment each reminder is due.
_LEAD = {
    ScheduledMessageKind.REMINDER_24H: timedelta(hours=24),
    ScheduledMessageKind.REMINDER_2H: timedelta(hours=2),
}


def reconcile_appointment_reminders(appointment: Appointment) -> None:
    """Ensure the outbox matches the appointment's current state.

    Active appointment → confirmation + any still-future reminders exist.
    Otherwise (cancelled / rescheduled / completed / no_show) → its unsent rows
    are marked skipped so nothing fires for a dead appointment.
    """
    if not appointment.clinic.reminders_enabled:
        return

    if appointment.status not in ACTIVE_STATUSES:
        cancel_appointment_reminders(appointment)
        return

    now = timezone.now()

    # Confirmation is due immediately (dispatcher still honors quiet hours).
    ScheduledMessage.objects.get_or_create(
        appointment=appointment,
        kind=ScheduledMessageKind.CONFIRMATION,
        defaults={"clinic": appointment.clinic, "scheduled_for": now},
    )

    for kind, lead in _LEAD.items():
        due = appointment.starts_at - lead
        # Don't schedule a reminder whose send time has already passed (e.g. a
        # booking made <24h out skips the 24h reminder).
        if due <= now:
            continue
        ScheduledMessage.objects.get_or_create(
            appointment=appointment,
            kind=kind,
            defaults={"clinic": appointment.clinic, "scheduled_for": due},
        )


def _as_time(value) -> time:
    """A TimeField default may still be a `HH:MM` string in memory before a DB
    round-trip — normalize either form to a `datetime.time`."""
    if isinstance(value, time):
        return value
    hh, mm, *rest = str(value).split(":")
    return time(int(hh), int(mm), int(rest[0]) if rest else 0)


def next_send_time(clinic: Clinic, when: datetime) -> datetime:
    """Return the earliest instant at/after `when` that falls inside the clinic's
    TCPA quiet-hours window. A message due outside the window is deferred to the
    next window open — never dropped. Handles both normal (08:00–21:00) and
    overnight (22:00–06:00) windows.
    """
    tz = ZoneInfo(clinic.timezone)
    local = when.astimezone(tz)
    start = _as_time(clinic.quiet_hours_start)
    end = _as_time(clinic.quiet_hours_end)
    t = local.time()

    if start <= end:
        # Same-day window, e.g. 08:00–21:00.
        if t < start:
            local = local.replace(
                hour=start.hour, minute=start.minute, second=0, microsecond=0
            )
        elif t > end:
            nxt = (local + timedelta(days=1)).replace(
                hour=start.hour, minute=start.minute, second=0, microsecond=0
            )
            local = nxt
    else:
        # Overnight window, e.g. 22:00–06:00 — allowed when t >= start OR t <= end.
        if end < t < start:
            local = local.replace(
                hour=start.hour, minute=start.minute, second=0, microsecond=0
            )
    return local.astimezone(when.tzinfo or ZoneInfo("UTC"))


def cancel_appointment_reminders(appointment: Appointment) -> None:
    """Mark all not-yet-sent reminders for this appointment as skipped."""
    ScheduledMessage.objects.filter(
        appointment=appointment, status=ScheduledMessageStatus.PENDING
    ).update(status=ScheduledMessageStatus.SKIPPED, updated_at=timezone.now())


def build_body(scheduled: ScheduledMessage) -> str:
    """PHI-minimal message text: date/time/clinic only, never procedure details."""
    appt = scheduled.appointment
    clinic = scheduled.clinic
    tz = ZoneInfo(clinic.timezone)
    when = appt.starts_at.astimezone(tz).strftime("%a, %b %-d at %-I:%M %p")
    name = (appt.patient.name or "").strip()
    hi = f"Hi {name.split()[0]}, " if name else "Hi, "

    if scheduled.kind == ScheduledMessageKind.CONFIRMATION:
        return (
            f"{hi}your appointment at {clinic.name} is confirmed for {when}. "
            "Reply here if you need to reschedule or cancel."
        )
    if scheduled.kind == ScheduledMessageKind.REMINDER_24H:
        return (
            f"{hi}a reminder of your appointment at {clinic.name} tomorrow, {when}. "
            "Reply C to confirm, R to reschedule, or X to cancel."
        )
    # 2-hour reminder — short.
    return f"{hi}see you soon at {clinic.name} today at {appt.starts_at.astimezone(tz).strftime('%-I:%M %p')}."
