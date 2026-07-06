"""Message cost estimation. WhatsApp bills per conversation category; this gives
a per-message estimate so the dashboard can show approximate spend. Costs are
snapshotted onto each outbound Message at send time (see tasks.py / views) so a
later rate change never rewrites historical spend."""
from __future__ import annotations

from decimal import Decimal

from .models import MessageCategory, MessageRate, ScheduledMessageKind

# Business-initiated reminders are all "utility" conversations. Kept here so the
# dispatcher doesn't need to know WhatsApp billing categories.
_KIND_CATEGORY = {
    ScheduledMessageKind.CONFIRMATION: MessageCategory.UTILITY,
    ScheduledMessageKind.REMINDER_24H: MessageCategory.UTILITY,
    ScheduledMessageKind.REMINDER_2H: MessageCategory.UTILITY,
    ScheduledMessageKind.THANK_YOU: MessageCategory.UTILITY,
    # Recovery follows up a specific missed appointment — transactional, not
    # promotional. Meta has the final say when it reviews the templates.
    ScheduledMessageKind.RECOVERY_SAMEDAY: MessageCategory.UTILITY,
    ScheduledMessageKind.RECOVERY_REBOOK: MessageCategory.UTILITY,
}


def category_for_kind(kind: str) -> str:
    return _KIND_CATEGORY.get(kind, MessageCategory.UTILITY)


def unit_cost(channel: str, category: str) -> Decimal:
    """Current per-message price for a (channel, category). Missing rate → free."""
    rate = MessageRate.objects.filter(channel=channel, category=category).first()
    return rate.unit_cost if rate is not None else Decimal("0")
