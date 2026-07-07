"""Clinic analytics: the renewal pitch, computed deterministically from the DB.

All aggregation lives here as pure functions taking a clinic + an aware UTC
[start, end) range, so the view and the monthly-report task share one code path
and the numbers are unit-testable without HTTP. Date bucketing is clinic-local
(appointments are stored UTC); callers pass ranges, this module owns the tz math.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

from django.db.models import Count
from django.utils import timezone

from apps.conversations.models import Conversation, EscalationStatus, EscalationTicket
from apps.messaging.models import Direction, Message, WaitlistOffer, WaitlistOfferStatus
from apps.scheduling.models import Appointment, AppointmentSource, AppointmentStatus


@dataclass(frozen=True)
class DateRange:
    start: datetime  # aware UTC, inclusive
    end: datetime  # aware UTC, exclusive
    tz: ZoneInfo


def _tz(clinic) -> ZoneInfo:
    return ZoneInfo(clinic.timezone)


def month_range(clinic, year: int, month: int) -> DateRange:
    """The [start, end) UTC range covering one clinic-local calendar month."""
    tz = _tz(clinic)
    last_day = calendar.monthrange(year, month)[1]
    start_local = datetime.combine(date_cls(year, month, 1), time.min, tzinfo=tz)
    end_local = datetime.combine(
        date_cls(year, month, last_day), time.max, tzinfo=tz
    ) + timedelta(microseconds=1)
    return DateRange(
        start=start_local.astimezone(ZoneInfo("UTC")),
        end=end_local.astimezone(ZoneInfo("UTC")),
        tz=tz,
    )


def previous_month(clinic, now: datetime | None = None) -> tuple[int, int]:
    """(year, month) of the calendar month before `now` in clinic-local time."""
    local = (now or timezone.now()).astimezone(_tz(clinic))
    first_of_this = local.replace(day=1)
    last_of_prev = first_of_this - timedelta(days=1)
    return last_of_prev.year, last_of_prev.month


def resolve_range(clinic, start_str: str | None, end_str: str | None) -> DateRange:
    """Turn optional YYYY-MM-DD query params into a UTC range. Missing start →
    first of the current clinic-local month; missing end → now. `end` is treated
    as inclusive of the whole given day."""
    tz = _tz(clinic)
    now = timezone.now().astimezone(tz)

    def _parse(s: str | None) -> date_cls | None:
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None

    start_d = _parse(start_str) or now.replace(day=1).date()
    start_local = datetime.combine(start_d, time.min, tzinfo=tz)

    end_d = _parse(end_str)
    if end_d is None:
        end_local = now
    else:
        end_local = datetime.combine(end_d, time.max, tzinfo=tz) + timedelta(microseconds=1)

    return DateRange(
        start=start_local.astimezone(ZoneInfo("UTC")),
        end=end_local.astimezone(ZoneInfo("UTC")),
        tz=tz,
    )


def _service_price(service) -> Decimal:
    """Conservative single-number estimate of a service's revenue: the low end of
    the price band, falling back to the high end, then zero."""
    if service.price_min is not None:
        return service.price_min
    if service.price_max is not None:
        return service.price_max
    return Decimal("0")


def _month_key(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%Y-%m")


def bookings_by_source(clinic, rng: DateRange) -> dict:
    """Appointments *created* in the range, grouped by source, with the bot's
    share of the total (the automation story)."""
    qs = Appointment.objects.filter(
        clinic=clinic, created_at__gte=rng.start, created_at__lt=rng.end
    )
    counts = {
        row["source"]: row["n"]
        for row in qs.values("source").annotate(n=Count("id"))
    }
    total = sum(counts.values())
    bot = counts.get(AppointmentSource.BOT, 0)
    return {
        "total": total,
        "by_source": [
            {"source": src, "count": counts.get(src, 0)}
            for src in AppointmentSource.values
        ],
        "bot_share": round(bot / total, 4) if total else 0.0,
    }


def no_show_stats(clinic, rng: DateRange) -> dict:
    """No-show rate over appointments that had *happened* (starts_at) in the range
    and reached a decided state (completed or no_show). Cancellations don't count
    against the rate — they were never a missed visit."""
    qs = Appointment.objects.filter(
        clinic=clinic,
        starts_at__gte=rng.start,
        starts_at__lt=rng.end,
        status__in=(AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW),
    )
    completed = qs.filter(status=AppointmentStatus.COMPLETED).count()
    no_show = qs.filter(status=AppointmentStatus.NO_SHOW).count()
    decided = completed + no_show
    return {
        "no_show": no_show,
        "completed": completed,
        "decided": decided,
        "rate": round(no_show / decided, 4) if decided else 0.0,
    }


def no_show_trend(clinic, rng: DateRange) -> list[dict]:
    """Monthly no-show rate buckets (clinic-local) across the range, oldest first —
    the trend line for the report."""
    qs = Appointment.objects.filter(
        clinic=clinic,
        starts_at__gte=rng.start,
        starts_at__lt=rng.end,
        status__in=(AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW),
    ).values_list("starts_at", "status")

    buckets: dict[str, list[int]] = {}  # period -> [no_show, decided]
    for starts_at, status in qs:
        key = _month_key(starts_at, rng.tz)
        b = buckets.setdefault(key, [0, 0])
        b[1] += 1
        if status == AppointmentStatus.NO_SHOW:
            b[0] += 1
    return [
        {
            "period": key,
            "no_show": b[0],
            "decided": b[1],
            "rate": round(b[0] / b[1], 4) if b[1] else 0.0,
        }
        for key, b in sorted(buckets.items())
    ]


def recovered_revenue(clinic, rng: DateRange) -> dict:
    """Bookings attributed to no-show recovery (Slice 1's `recovered_from`) that
    were *created* in the range, and their estimated revenue."""
    qs = Appointment.objects.filter(
        clinic=clinic,
        recovered_from__isnull=False,
        created_at__gte=rng.start,
        created_at__lt=rng.end,
    ).select_related("service")
    count = 0
    revenue = Decimal("0")
    for appt in qs:
        count += 1
        revenue += _service_price(appt.service)
    return {"count": count, "revenue": str(revenue)}


def waitlist_stats(clinic, rng: DateRange) -> dict:
    """Waitlist activity: offers accepted (fills) in the range — the slots we
    saved from going empty."""
    fills = WaitlistOffer.objects.filter(
        clinic=clinic,
        status=WaitlistOfferStatus.ACCEPTED,
        updated_at__gte=rng.start,
        updated_at__lt=rng.end,
    ).count()
    return {"fills": fills}


def containment_stats(clinic, rng: DateRange) -> dict:
    """Bot containment: share of conversations active in the range that never
    escalated to a human. A conversation counts as active if it had a message in
    the range; escalation is measured by a ticket opened for it in the range."""
    conv_ids = set(
        Message.objects.filter(
            clinic=clinic, created_at__gte=rng.start, created_at__lt=rng.end
        )
        .exclude(conversation__isnull=True)
        .values_list("conversation_id", flat=True)
    )
    total = len(conv_ids)
    escalated = (
        EscalationTicket.objects.filter(
            clinic=clinic,
            conversation_id__in=conv_ids,
            created_at__gte=rng.start,
            created_at__lt=rng.end,
        )
        .values("conversation_id")
        .distinct()
        .count()
    )
    return {
        "total_conversations": total,
        "escalated": escalated,
        "rate": round(1 - escalated / total, 4) if total else 0.0,
    }


def response_time_stats(clinic, rng: DateRange) -> dict:
    """Median seconds from a patient's first inbound to the bot's first outbound,
    over conversations whose first inbound falls in the range. One data point per
    conversation; conversations with no reply are skipped."""
    rows = (
        Message.objects.filter(
            clinic=clinic, created_at__gte=rng.start, created_at__lt=rng.end
        )
        .exclude(conversation__isnull=True)
        .values_list("conversation_id", "direction", "created_at")
        .order_by("created_at")
    )
    first_in: dict[int, datetime] = {}
    first_out: dict[int, datetime] = {}
    for conv_id, direction, created_at in rows:
        if direction == Direction.IN:
            first_in.setdefault(conv_id, created_at)
        elif direction == Direction.OUT:
            first_out.setdefault(conv_id, created_at)

    deltas = [
        (first_out[cid] - first_in[cid]).total_seconds()
        for cid in first_in
        if cid in first_out and first_out[cid] >= first_in[cid]
    ]
    return {
        "median_seconds": int(median(deltas)) if deltas else None,
        "sample": len(deltas),
    }


def compute_analytics(clinic, rng: DateRange) -> dict:
    """Everything the dashboard/report needs for one range, in one dict."""
    return {
        "from": rng.start.isoformat(),
        "to": rng.end.isoformat(),
        "currency": clinic.currency,
        "bookings": bookings_by_source(clinic, rng),
        "no_show": no_show_stats(clinic, rng),
        "no_show_trend": no_show_trend(clinic, rng),
        "recovered": recovered_revenue(clinic, rng),
        "waitlist": waitlist_stats(clinic, rng),
        "containment": containment_stats(clinic, rng),
        "response_time": response_time_stats(clinic, rng),
    }
