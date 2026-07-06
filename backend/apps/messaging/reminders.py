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

# Kinds that fire *before* the appointment. Only these are cancelled when an
# appointment leaves an active state — the post-visit THANK_YOU is created after
# completion and must survive later reconciliation.
_PRE_APPOINTMENT_KINDS = (
    ScheduledMessageKind.CONFIRMATION,
    ScheduledMessageKind.REMINDER_24H,
    ScheduledMessageKind.REMINDER_2H,
)

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
    """Mark all not-yet-sent *pre-appointment* reminders for this appointment as
    skipped. The post-visit THANK_YOU is left alone so completing an appointment
    (which drops the appointment out of ACTIVE_STATUSES) never skips it."""
    ScheduledMessage.objects.filter(
        appointment=appointment,
        status=ScheduledMessageStatus.PENDING,
        kind__in=_PRE_APPOINTMENT_KINDS,
    ).update(status=ScheduledMessageStatus.SKIPPED, updated_at=timezone.now())


# Meta-approved template names per reminder kind (see CLAUDE.md / WhatsApp
# Manager). Every business-initiated send outside the 24h customer-service
# window must go through one of these. Language is fixed to the approved locale.
TEMPLATE_NAMES = {
    ScheduledMessageKind.CONFIRMATION: "appointment_confirmation",
    ScheduledMessageKind.REMINDER_24H: "appointment_reminder_24h",
    ScheduledMessageKind.REMINDER_2H: "appointment_reminder_2h",
    ScheduledMessageKind.THANK_YOU: "appointment_thank_you",
}
TEMPLATE_LANG = "en_US"


def _template_parts(scheduled: ScheduledMessage):
    """Shared bits every reminder body/template needs: patient first name (never
    empty — Meta rejects blank template params), clinic name, and the formatted
    appointment time. PHI-minimal: date/time/clinic only, never procedure."""
    appt = scheduled.appointment
    clinic = scheduled.clinic
    tz = ZoneInfo(clinic.timezone)
    name = (appt.patient.name or "").strip()
    first = name.split()[0] if name else "there"
    when = appt.starts_at.astimezone(tz).strftime("%a, %b %-d at %-I:%M %p")
    time_only = appt.starts_at.astimezone(tz).strftime("%-I:%M %p")
    return first, clinic.name, when, time_only


def build_template(scheduled: ScheduledMessage) -> dict | None:
    """The Meta template spec for this reminder: name, language, ordered body
    params, and (for the 24h reminder) the quick-reply button payloads that carry
    the appointment id so a tap round-trips back to our tap-routing. Returns None
    for kinds with no template (nothing outside our 4 approved templates)."""
    name = TEMPLATE_NAMES.get(scheduled.kind)
    if name is None:
        return None
    first, clinic_name, when, time_only = _template_parts(scheduled)

    if scheduled.kind == ScheduledMessageKind.THANK_YOU:
        body_params = [first, clinic_name]
    elif scheduled.kind == ScheduledMessageKind.REMINDER_2H:
        body_params = [first, clinic_name, time_only]
    else:
        body_params = [first, clinic_name, when]

    spec: dict = {
        "name": name,
        "language": TEMPLATE_LANG,
        "body_params": body_params,
    }
    if scheduled.kind == ScheduledMessageKind.REMINDER_24H:
        appt_id = scheduled.appointment_id
        spec["buttons"] = [
            {"index": 0, "payload": option_id("confirm", appt_id)},
            {"index": 1, "payload": option_id("reschedule", appt_id)},
            {"index": 2, "payload": option_id("cancel", appt_id)},
        ]
    return spec


def build_body(scheduled: ScheduledMessage) -> str:
    """Plain-text fallback, kept in sync with the approved template wording. Used
    for channels without templates and when WhatsApp credentials are missing (dev)."""
    first, clinic_name, when, time_only = _template_parts(scheduled)
    hi = f"Hi {first}, "

    if scheduled.kind == ScheduledMessageKind.CONFIRMATION:
        return (
            f"{hi}your appointment at {clinic_name} is confirmed for {when}. "
            "Reply here if you need to reschedule or cancel."
        )
    if scheduled.kind == ScheduledMessageKind.REMINDER_24H:
        return (
            f"{hi}a reminder of your appointment at {clinic_name} tomorrow, {when}. "
            "Tap a button below to confirm, reschedule, or cancel."
        )
    if scheduled.kind == ScheduledMessageKind.THANK_YOU:
        return (
            f"{hi}thanks for visiting {clinic_name}! "
            "Reply here anytime to book your next appointment."
        )
    # 2-hour reminder — short.
    return f"{hi}see you soon — your appointment at {clinic_name} is today at {time_only}. See you then!"
