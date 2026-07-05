"""System-prompt assembly. Prompts are versioned assets in /prompts and treated
as code; the version that handled each turn is recorded on the Conversation."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from apps.scheduling.models import ScheduleRule, Service

PROMPT_VERSION = "booking_v1"
_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "booking_system_v1.md"
)

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@lru_cache(maxsize=1)
def _template() -> str:
    return _PROMPT_PATH.read_text()


def _services_block(clinic) -> str:
    lines = []
    for s in Service.objects.filter(clinic=clinic, is_active=True).order_by("name"):
        price = f" — {s.price_display}" if s.price_display else ""
        lines.append(f"- {s.name} ({s.duration_min} min){price}")
    return "\n".join(lines) or "- (no services configured)"


def _hours_block(clinic) -> str:
    by_day: dict[int, list[str]] = {}
    for r in ScheduleRule.objects.filter(clinic=clinic, practitioner__isnull=True).order_by(
        "weekday", "start_time"
    ):
        by_day.setdefault(r.weekday, []).append(
            f"{r.start_time.strftime('%-I:%M %p')}–{r.end_time.strftime('%-I:%M %p')}"
        )
    if not by_day:
        return "- (hours not configured)"
    return "\n".join(
        f"- {_WEEKDAYS[wd]}: {', '.join(by_day[wd])}" for wd in sorted(by_day)
    )


def build_system_prompt(clinic) -> str:
    return _template().format(
        clinic_name=clinic.name,
        clinic_timezone=clinic.timezone,
        clinic_currency=clinic.currency,
        clinic_address=clinic.address or "(not set)",
        clinic_maps_link=clinic.maps_link or "(not set)",
        emergency_phone=clinic.emergency_phone or "(not set)",
        cancellation_policy=clinic.cancellation_policy or "(none stated)",
        accepted_insurance=", ".join(clinic.accepted_insurance) or "(ask front desk)",
        new_patient_form_url=clinic.new_patient_form_url or "(none)",
        languages=", ".join(clinic.languages) or "en",
        services_block=_services_block(clinic),
        hours_block=_hours_block(clinic),
    )
