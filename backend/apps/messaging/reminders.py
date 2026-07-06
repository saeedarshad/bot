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

# Reply-option ids on the interactive 24h reminder. The action is encoded in the
# id so a tap round-trips back to us as `{action}_appt_{appointment_id}` and the
# inbound pipeline can route it deterministically (see conversations/inbound.py).
_ACTION_PREFIX = {
    "confirm": "confirm_appt_",
    "reschedule": "reschedule_appt_",
    "cancel": "cancel_appt_",
}


def option_id(action: str, appointment_id: int) -> str:
    return f"{_ACTION_PREFIX[action]}{appointment_id}"


def parse_option_id(reply_option_id: str | None) -> tuple[str | None, int | None]:
    """Inverse of `option_id`. Returns (action, appointment_id) or (None, None)."""
    if not reply_option_id:
        return None, None
    for action, prefix in _ACTION_PREFIX.items():
        if reply_option_id.startswith(prefix):
            tail = reply_option_id[len(prefix):]
            if tail.isdigit():
                return action, int(tail)
    return None, None


def build_interactive(scheduled: ScheduledMessage) -> dict | None:
    """Tappable Confirm / Reschedule / Cancel options for the 24h reminder; None
    for kinds that are plain text. Rendering to real WhatsApp buttons needs a
    Meta-approved interactive template (see CLAUDE.md); the demo channel falls
    back to the text body, and the option ids still drive tap routing."""
    if scheduled.kind != ScheduledMessageKind.REMINDER_24H:
        return None
    appt_id = scheduled.appointment_id
    return {
        "body": build_body(scheduled),
        "options": [
            {"id": option_id("confirm", appt_id), "title": "Confirm"},
            {"id": option_id("reschedule", appt_id), "title": "Reschedule"},
            {"id": option_id("cancel", appt_id), "title": "Cancel"},
        ],
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
