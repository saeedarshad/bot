"""System-prompt assembly. Prompts are versioned assets in /prompts and treated
as code; the version that handled each turn is recorded on the Conversation."""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

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


def _date_reference_block(today) -> str:
    """Explicit weekday->date lookup for the next two weeks so the model never
    does calendar arithmetic itself (a frequent source of off-by-one errors)."""
    lines = []
    for i in range(15):
        d = today + timedelta(days=i)
        label = "today" if i == 0 else ("tomorrow" if i == 1 else "")
        suffix = f"  ({label})" if label else ""
        lines.append(f"- {d.strftime('%A')} {d.strftime('%Y-%m-%d')}{suffix}")
    return "\n".join(lines)


def _patient_context(patient) -> str:
    if patient and (patient.name or "").strip():
        base = (
            f"You are speaking with {patient.name.strip()}, a returning patient. "
            "Greet them by name and do NOT ask for their name again when booking."
        )
        pref = getattr(patient, "preferred_practitioner", None)
        if pref is not None:
            base += (
                f" Their usual practitioner is {pref.name}. When they book, offer "
                f"{pref.name} first (pass that practitioner_id to check_availability), "
                "unless they ask for someone else or no time with them works."
            )
        return base
    return "You do not yet know this patient's name; ask for it before you book."


def build_system_prompt(clinic, patient=None) -> str:
    now_local = datetime.now(ZoneInfo(clinic.timezone))
    return _template().format(
        date_reference=_date_reference_block(now_local.date()),
        patient_context=_patient_context(patient),
        clinic_name=clinic.name,
        current_date=now_local.strftime("%Y-%m-%d"),
        current_weekday=now_local.strftime("%A"),
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
