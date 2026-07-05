"""Deterministic scheduling engine.

Principle 2: the LLM never owns the calendar. Every open slot and every booking
is computed here in plain Python against the DB. The LLM can only pass back a
slot token that this engine independently re-validates, so it is structurally
impossible for the model to invent a time or double-book.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import connection, models, transaction
from django.utils import timezone

from apps.clinics.models import Patient

from .models import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    Practitioner,
    ScheduleException,
    ScheduleRule,
    Service,
)


@dataclass(frozen=True)
class Slot:
    service_id: int
    practitioner_id: int | None
    start: datetime  # aware, UTC
    end: datetime  # aware, UTC (appointment end, excludes buffer)

    @property
    def token(self) -> str:
        raw = f"{self.service_id}|{self.practitioner_id or 0}|{self.start.isoformat()}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    def label(self, tz: ZoneInfo) -> str:
        local = self.start.astimezone(tz)
        # US formatting: "Tue, Mar 4, 2:30 PM"
        return local.strftime("%a, %b %-d, %-I:%M %p")


@dataclass(frozen=True)
class DecodedToken:
    service_id: int
    practitioner_id: int | None
    start: datetime


class InvalidToken(Exception):
    pass


def decode_token(token: str) -> DecodedToken:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        service_id, pract_id, iso = raw.split("|", 2)
        start = datetime.fromisoformat(iso)
    except (ValueError, binascii.Error) as exc:
        raise InvalidToken(str(exc)) from exc
    if start.tzinfo is None:
        raise InvalidToken("naive datetime in token")
    return DecodedToken(
        service_id=int(service_id),
        practitioner_id=int(pract_id) or None,
        start=start.astimezone(ZoneInfo("UTC")),
    )


def _tz(clinic) -> ZoneInfo:
    return ZoneInfo(clinic.timezone)


def _working_intervals(
    clinic, on_date: date_cls, practitioner: Practitioner | None
) -> list[tuple[time, time]]:
    """Local-time working windows for a date, after applying exceptions."""
    exc = (
        ScheduleException.objects.filter(clinic=clinic, date=on_date)
        .filter(_practitioner_q(practitioner))
        .order_by("practitioner_id")  # practitioner-specific override wins
        .last()
    )
    if exc is not None:
        if exc.is_closed or not (exc.start_time and exc.end_time):
            return []
        return [(exc.start_time, exc.end_time)]

    rules = ScheduleRule.objects.filter(
        clinic=clinic, weekday=on_date.weekday()
    ).filter(_practitioner_q(practitioner))
    return [(r.start_time, r.end_time) for r in rules.order_by("start_time")]


def _practitioner_q(practitioner: Practitioner | None):
    from django.db.models import Q

    if practitioner is None:
        return Q(practitioner__isnull=True)
    return Q(practitioner=practitioner)


def _candidate_practitioners(clinic, service: Service, practitioner) -> list:
    if practitioner is not None:
        return [practitioner]
    if service.requires_practitioner:
        return list(clinic.practitioners.filter(is_active=True).order_by("id"))
    return [None]


def _occupied(
    clinic, practitioner, day_start_utc, day_end_utc, exclude_ids=None
) -> list[tuple[datetime, datetime]]:
    """Buffered busy intervals (UTC) for a practitioner (or clinic-wide) on a day.

    `exclude_ids` drops specific appointments from the busy set — used when
    rescheduling so an appointment doesn't block its own new time.
    """
    qs = Appointment.objects.filter(
        clinic=clinic,
        status__in=ACTIVE_STATUSES,
        starts_at__lt=day_end_utc,
        ends_at__gt=day_start_utc,
    ).select_related("service")
    if practitioner is None:
        qs = qs.filter(practitioner__isnull=True)
    else:
        qs = qs.filter(practitioner=practitioner)
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)
    out = []
    for appt in qs:
        buf = timedelta(minutes=appt.service.buffer_after_min)
        out.append((appt.starts_at, appt.ends_at + buf))
    return out


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def available_slots(
    clinic,
    service: Service,
    *,
    start_date: date_cls | None = None,
    end_date: date_cls | None = None,
    practitioner: Practitioner | None = None,
    time_preference: str | None = None,
    limit: int = 6,
    exclude_appointment_ids=None,
) -> list[Slot]:
    """Compute up to `limit` concrete open slots for a service."""
    tz = _tz(clinic)
    now = timezone.now()
    today_local = now.astimezone(tz).date()
    horizon = today_local + timedelta(days=clinic.booking_horizon_days)

    start_date = max(start_date or today_local, today_local)
    end_date = min(end_date or horizon, horizon)
    min_start = now + timedelta(minutes=clinic.min_notice_minutes)

    duration = timedelta(minutes=service.duration_min)
    buffer = timedelta(minutes=service.buffer_after_min)
    step = timedelta(minutes=clinic.slot_granularity_minutes)

    slots: list[Slot] = []
    day = start_date
    while day <= end_date and len(slots) < limit:
        for pract in _candidate_practitioners(clinic, service, practitioner):
            day_start_utc = datetime.combine(day, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
            day_end_utc = day_start_utc + timedelta(days=1)
            busy = _occupied(
                clinic, pract, day_start_utc, day_end_utc, exclude_appointment_ids
            )

            for win_start, win_end in _working_intervals(clinic, day, pract):
                cursor_local = datetime.combine(day, win_start, tzinfo=tz)
                win_end_local = datetime.combine(day, win_end, tzinfo=tz)
                while cursor_local + duration <= win_end_local:
                    start_utc = cursor_local.astimezone(ZoneInfo("UTC"))
                    end_utc = start_utc + duration
                    if start_utc >= min_start and _slot_ok(
                        start_utc, end_utc, buffer, busy, time_preference, tz
                    ):
                        slots.append(
                            Slot(
                                service_id=service.id,
                                practitioner_id=pract.id if pract else None,
                                start=start_utc,
                                end=end_utc,
                            )
                        )
                        if len(slots) >= limit:
                            break
                    cursor_local += step
                if len(slots) >= limit:
                    break
            if len(slots) >= limit:
                break
        day += timedelta(days=1)
    return slots


def _slot_ok(start_utc, end_utc, buffer, busy, time_preference, tz) -> bool:
    blocked_end = end_utc + buffer
    for b_start, b_end in busy:
        if _overlaps(start_utc, blocked_end, b_start, b_end):
            return False
    if time_preference:
        hour = start_utc.astimezone(tz).hour
        windows = {
            "morning": range(0, 12),
            "afternoon": range(12, 17),
            "evening": range(17, 24),
        }
        rng = windows.get(time_preference.lower())
        if rng is not None and hour not in rng:
            return False
    return True


@dataclass
class BookingResult:
    ok: bool
    appointment: Appointment | None = None
    alternatives: list[Slot] | None = None
    error: str | None = None


def book_slot(
    clinic,
    patient,
    token: str,
    *,
    source: str = AppointmentSource.BOT,
) -> BookingResult:
    """Atomically book a slot. Re-validates the token against live availability
    under an advisory lock so two patients racing for the last slot can't both win."""
    try:
        decoded = decode_token(token)
    except InvalidToken as exc:
        return BookingResult(ok=False, error=f"invalid_slot:{exc}")

    try:
        service = Service.objects.get(id=decoded.service_id, clinic=clinic, is_active=True)
    except Service.DoesNotExist:
        return BookingResult(ok=False, error="unknown_service")

    practitioner = None
    if decoded.practitioner_id:
        practitioner = Practitioner.objects.filter(
            id=decoded.practitioner_id, clinic=clinic
        ).first()

    with transaction.atomic():
        # Serialize concurrent bookings for the same (clinic, practitioner).
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                [clinic.id, decoded.practitioner_id or 0],
            )

        if not _still_available(clinic, service, practitioner, decoded.start):
            alts = available_slots(
                clinic,
                service,
                start_date=decoded.start.astimezone(_tz(clinic)).date(),
                practitioner=practitioner,
                limit=3,
            )
            return BookingResult(ok=False, alternatives=alts, error="slot_taken")

        appt = Appointment.objects.create(
            clinic=clinic,
            patient=patient,
            practitioner=practitioner,
            service=service,
            starts_at=decoded.start,
            ends_at=decoded.start + timedelta(minutes=service.duration_min),
            source=source,
        )
    return BookingResult(ok=True, appointment=appt)


def _still_available(clinic, service, practitioner, start_utc, exclude_appointment_ids=None) -> bool:
    """The requested start must be a genuine open slot right now (not invented)."""
    day = start_utc.astimezone(_tz(clinic)).date()
    slots = available_slots(
        clinic,
        service,
        start_date=day,
        end_date=day,
        practitioner=practitioner,
        limit=200,
        exclude_appointment_ids=exclude_appointment_ids,
    )
    return any(s.start == start_utc for s in slots)


@dataclass
class RescheduleResult:
    ok: bool
    appointment: Appointment | None = None
    old_appointment: Appointment | None = None
    alternatives: list[Slot] | None = None
    error: str | None = None


def reschedule_slot(
    clinic,
    patient,
    appointment_id: int,
    token: str,
    *,
    source: str = AppointmentSource.BOT,
) -> RescheduleResult:
    """Move an existing appointment to a new slot atomically.

    The old slot is only released once the new one is committed: both the
    creation of the new appointment and the marking of the old one as
    RESCHEDULED happen in a single transaction, so a failure anywhere leaves the
    original booking untouched.
    """
    try:
        decoded = decode_token(token)
    except InvalidToken as exc:
        return RescheduleResult(ok=False, error=f"invalid_slot:{exc}")

    appt = (
        Appointment.objects.filter(
            id=appointment_id,
            clinic=clinic,
            patient=patient,
            status__in=ACTIVE_STATUSES,
        )
        .select_related("service")
        .first()
    )
    if appt is None:
        return RescheduleResult(ok=False, error="appointment_not_found")

    try:
        service = Service.objects.get(id=decoded.service_id, clinic=clinic, is_active=True)
    except Service.DoesNotExist:
        return RescheduleResult(ok=False, error="unknown_service")

    practitioner = None
    if decoded.practitioner_id:
        practitioner = Practitioner.objects.filter(
            id=decoded.practitioner_id, clinic=clinic
        ).first()

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                [clinic.id, decoded.practitioner_id or 0],
            )

        # Ignore the appointment being moved when checking the new time so it
        # doesn't block itself (e.g. shifting to an adjacent slot).
        if not _still_available(
            clinic, service, practitioner, decoded.start, exclude_appointment_ids={appt.id}
        ):
            alts = available_slots(
                clinic,
                service,
                start_date=decoded.start.astimezone(_tz(clinic)).date(),
                practitioner=practitioner,
                limit=3,
                exclude_appointment_ids={appt.id},
            )
            return RescheduleResult(ok=False, alternatives=alts, error="slot_taken")

        new_appt = Appointment.objects.create(
            clinic=clinic,
            patient=patient,
            practitioner=practitioner,
            service=service,
            starts_at=decoded.start,
            ends_at=decoded.start + timedelta(minutes=service.duration_min),
            source=source,
        )
        appt.status = AppointmentStatus.RESCHEDULED
        appt.save(update_fields=["status", "updated_at"])
    return RescheduleResult(ok=True, appointment=new_appt, old_appointment=appt)


@dataclass
class CancelResult:
    ok: bool
    appointment: Appointment | None = None
    error: str | None = None


def cancel_appointment(clinic, patient, appointment_id: int, reason: str = "") -> CancelResult:
    """Cancel an active appointment, freeing its slot."""
    appt = Appointment.objects.filter(
        id=appointment_id,
        clinic=clinic,
        patient=patient,
        status__in=ACTIVE_STATUSES,
    ).first()
    if appt is None:
        return CancelResult(ok=False, error="appointment_not_found")

    appt.status = AppointmentStatus.CANCELLED
    fields = ["status", "updated_at"]
    if reason:
        appt.notes = f"{appt.notes}\nCancelled: {reason}".strip()
        fields.append("notes")
    appt.save(update_fields=fields)
    return CancelResult(ok=True, appointment=appt)


@dataclass
class LifecycleResult:
    ok: bool
    appointment: Appointment | None = None
    error: str | None = None


def _active_appt(clinic, appointment_id: int) -> Appointment | None:
    return Appointment.objects.filter(
        id=appointment_id, clinic=clinic, status__in=ACTIVE_STATUSES
    ).select_related("patient").first()


def mark_no_show(clinic, appointment_id: int) -> LifecycleResult:
    """Staff action: mark an active appointment as a no-show and bump the patient's
    running no_show_count. Idempotent by construction — an already-terminal
    appointment (cancelled/completed/no_show) is not re-counted."""
    with transaction.atomic():
        appt = _active_appt(clinic, appointment_id)
        if appt is None:
            return LifecycleResult(ok=False, error="appointment_not_found")
        appt.status = AppointmentStatus.NO_SHOW
        appt.save(update_fields=["status", "updated_at"])
        Patient.objects.filter(id=appt.patient_id).update(
            no_show_count=models.F("no_show_count") + 1
        )
    return LifecycleResult(ok=True, appointment=appt)


def mark_completed(clinic, appointment_id: int) -> LifecycleResult:
    """Mark an active appointment as completed (patient attended)."""
    appt = _active_appt(clinic, appointment_id)
    if appt is None:
        return LifecycleResult(ok=False, error="appointment_not_found")
    appt.status = AppointmentStatus.COMPLETED
    appt.save(update_fields=["status", "updated_at"])
    return LifecycleResult(ok=True, appointment=appt)
