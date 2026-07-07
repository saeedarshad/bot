"""Conversation quality export: the week's escalated and false-confirmation-
corrected conversations, as a reviewable dataset for prompt iteration.

Clinic-scoped and read-only. Escalations come from EscalationTicket; corrected
turns come from Conversation.false_confirmation_count (bumped by the guardrail in
conversations/engine.py even when the retry then succeeds and no ticket opens).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.conversations.models import Conversation, EscalationTicket
from apps.messaging.models import Direction

# Cap transcript length per conversation so the export stays bounded on a
# long-running thread; the most recent turns carry the relevant context.
_MAX_MESSAGES = 40


def resolve_week(clinic, start_str: str | None, end_str: str | None):
    """[start, end) UTC for the export. Defaults to the last 7 days; explicit
    YYYY-MM-DD params are interpreted in the clinic's local timezone."""
    tz = ZoneInfo(clinic.timezone)
    now = timezone.now()

    def _parse_day(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    start_d = _parse_day(start_str)
    if start_d is None:
        start = now - timedelta(days=7)
    else:
        start = datetime.combine(start_d, datetime.min.time(), tzinfo=tz).astimezone(
            ZoneInfo("UTC")
        )

    end_d = _parse_day(end_str)
    if end_d is None:
        end = now
    else:
        end = (
            datetime.combine(end_d, datetime.max.time(), tzinfo=tz)
            + timedelta(microseconds=1)
        ).astimezone(ZoneInfo("UTC"))
    return start, end


def export_review_dataset(clinic, start, end) -> list[dict]:
    """Conversations worth reviewing in [start, end): those escalated in the
    window, plus those the false-confirmation guardrail corrected in the window."""
    escalations: dict[int, list[dict]] = {}
    for t in EscalationTicket.objects.filter(
        clinic=clinic, created_at__gte=start, created_at__lt=end
    ):
        escalations.setdefault(t.conversation_id, []).append(
            {"reason": t.reason, "status": t.status, "created_at": t.created_at}
        )

    corrected_ids = set(
        Conversation.objects.filter(
            clinic=clinic,
            false_confirmation_count__gt=0,
            last_message_at__gte=start,
            last_message_at__lt=end,
        ).values_list("id", flat=True)
    )

    conv_ids = set(escalations) | corrected_ids
    conversations = Conversation.objects.filter(id__in=conv_ids).select_related("patient")

    out = []
    for conv in conversations:
        recent = list(conv.messages.order_by("-created_at")[:_MAX_MESSAGES])
        recent.reverse()
        out.append(
            {
                "conversation_id": conv.id,
                "prompt_version": conv.prompt_version,
                "false_confirmation_count": conv.false_confirmation_count,
                "escalations": escalations.get(conv.id, []),
                "patient": (conv.patient.name or conv.patient.phone_e164),
                "messages": [
                    {
                        "role": "patient" if m.direction == Direction.IN else "bot",
                        "body": m.body,
                        "at": m.created_at,
                    }
                    for m in recent
                    if m.body
                ],
            }
        )
    # Escalated/most-corrected first — the ones most worth a human's attention.
    out.sort(
        key=lambda c: (len(c["escalations"]), c["false_confirmation_count"]),
        reverse=True,
    )
    return out
