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
from apps.scheduling.models import ACTIVE_STATUSES, Appointment, AppointmentStatus

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

# No-show recovery kinds and the lead time before the rebooking offer goes out.
_RECOVERY_KINDS = (
    ScheduledMessageKind.RECOVERY_SAMEDAY,
    ScheduledMessageKind.RECOVERY_REBOOK,
)
_REBOOK_DELAY = timedelta(days=2)
# A booking within this window after a recovery send counts as recovered.
_RECOVERY_ATTRIBUTION_WINDOW = timedelta(days=14)

# Reply-option ids on the interactive 24h reminder. The action is encoded in the
# id so a tap round-trips back to us as `{action}_appt_{appointment_id}` and the
# inbound pipeline can route it deterministically (see conversations/inbound.py).
# `rebook` rides on a recovery template button and references a NO-SHOW (not
# active) appointment.
_ACTION_PREFIX = {
    "confirm": "confirm_appt_",
    "reschedule": "reschedule_appt_",
    "cancel": "cancel_appt_",
    "rebook": "rebook_appt_",
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
        if appointment.status == AppointmentStatus.NO_SHOW:
            schedule_no_show_recovery(appointment)
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


def schedule_no_show_recovery(appointment: Appointment) -> None:
    """Queue the two-step recovery sequence for a no-show: a gentle same-day
    message and a rebooking offer 2 days later. Idempotent via UNIQUE(appointment,
    kind) — re-saving the no-show never duplicates. Both are post-appointment
    kinds, so later reconciles never skip them. Opted-out patients are excluded
    here and again at dispatch time (belt and suspenders)."""
    clinic = appointment.clinic
    if not clinic.no_show_recovery_enabled:
        return
    if appointment.patient.opted_out_at is not None:
        return

    now = timezone.now()
    due = {
        ScheduledMessageKind.RECOVERY_SAMEDAY: next_send_time(clinic, now),
        ScheduledMessageKind.RECOVERY_REBOOK: next_send_time(clinic, now + _REBOOK_DELAY),
    }
    for kind, scheduled_for in due.items():
        ScheduledMessage.objects.get_or_create(
            appointment=appointment,
            kind=kind,
            defaults={"clinic": clinic, "scheduled_for": scheduled_for},
        )


def attribute_recovered_booking(appointment: Appointment) -> None:
    """If this new booking follows a recently-SENT recovery message for the same
    patient, link it to the no-show it recovers. Deterministic (never the LLM):
    the newest no-show whose recovery message went out within the attribution
    window wins. Called from the post_save signal on Appointment creation."""
    if appointment.recovered_from_id is not None:
        return
    if appointment.status not in ACTIVE_STATUSES:
        return

    cutoff = timezone.now() - _RECOVERY_ATTRIBUTION_WINDOW
    recovery = (
        ScheduledMessage.objects.filter(
            clinic=appointment.clinic,
            appointment__patient=appointment.patient,
            appointment__status=AppointmentStatus.NO_SHOW,
            kind__in=_RECOVERY_KINDS,
            status=ScheduledMessageStatus.SENT,
            sent_at__gte=cutoff,
        )
        .exclude(appointment=appointment)
        .order_by("-sent_at")
        .first()
    )
    if recovery is None:
        return
    appointment.recovered_from = recovery.appointment
    appointment.save(update_fields=["recovered_from", "updated_at"])


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
    ScheduledMessageKind.RECOVERY_SAMEDAY: "noshow_recovery_sameday",
    ScheduledMessageKind.RECOVERY_REBOOK: "noshow_rebook_offer",
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

    if scheduled.kind in (ScheduledMessageKind.THANK_YOU, ScheduledMessageKind.RECOVERY_SAMEDAY):
        body_params = [first, clinic_name]
    elif scheduled.kind == ScheduledMessageKind.RECOVERY_REBOOK:
        body_params = [first, clinic_name, _rebook_openings_sentence(scheduled.appointment)]
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
    elif scheduled.kind == ScheduledMessageKind.RECOVERY_REBOOK:
        spec["buttons"] = [
            {"index": 0, "payload": option_id("rebook", scheduled.appointment_id)},
        ]
    return spec


def _rebook_openings_sentence(appointment: Appointment) -> str:
    """One sentence of real openings for the missed service, computed at dispatch
    time (never when the row was queued 2 days earlier). Template button labels
    are fixed at Meta approval, so live slot times can only ride in a body param;
    the tap opens the 24h session window where the bot presents real tappable
    slots. Single line — Meta rejects newlines in params."""
    from apps.scheduling.engine import available_slots

    clinic = appointment.clinic
    tz = ZoneInfo(clinic.timezone)
    slots = available_slots(clinic, appointment.service, limit=3)
    if not slots:
        return "New openings come up every day."
    return "We have openings " + "; ".join(s.label(tz) for s in slots) + "."


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
    if scheduled.kind == ScheduledMessageKind.RECOVERY_SAMEDAY:
        return (
            f"{hi}we're sorry we missed you at {clinic_name} today — life happens! "
            "Reply here whenever you'd like to find a new time."
        )
    if scheduled.kind == ScheduledMessageKind.RECOVERY_REBOOK:
        openings = _rebook_openings_sentence(scheduled.appointment)
        return (
            f"{hi}we'd love to get you back on the schedule at {clinic_name}. "
            f"{openings} Reply here and we'll get you booked."
        )
    # 2-hour reminder — short.
    return f"{hi}see you soon — your appointment at {clinic_name} is today at {time_only}. See you then!"
