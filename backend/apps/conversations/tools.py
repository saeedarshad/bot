"""LLM tool contract. The model can only act through these tools; each one
validates its input with Pydantic and delegates to deterministic code. Slot times
and bookings come exclusively from the scheduling engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from pydantic import BaseModel, Field, ValidationError

from apps.scheduling.engine import available_slots, book_slot
from apps.scheduling.models import (
    ACTIVE_STATUSES,
    Appointment,
    Practitioner,
    Service,
)

from .models import Conversation, ConversationStatus, EscalationTicket, FAQEntry


@dataclass
class ConvContext:
    clinic: object
    patient: object
    conversation: Conversation


# --- Pydantic input schemas -------------------------------------------------

class FaqInput(BaseModel):
    topic: str


class AvailabilityInput(BaseModel):
    service_id: int
    from_date: str | None = None  # YYYY-MM-DD
    to_date: str | None = None
    practitioner_id: int | None = None
    time_preference: str | None = None  # morning|afternoon|evening


class BookInput(BaseModel):
    slot_token: str
    patient_name: str | None = None


class AppointmentsInput(BaseModel):
    status: str | None = None


class EscalateInput(BaseModel):
    reason: str = Field(default="")


# --- Anthropic tool definitions --------------------------------------------

TOOL_DEFS = [
    {
        "name": "get_services",
        "description": "List the clinic's bookable services with duration and price display.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_faq_answer",
        "description": "Look up a pre-approved answer (hours, location, insurance, payment, doctors, policies). Returns null if none matches.",
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "What the patient is asking about."}},
            "required": ["topic"],
        },
    },
    {
        "name": "check_availability",
        "description": "Get up to 6 real open appointment slots for a service. The ONLY source of appointment times. Returns slots each with an opaque slot_token and a human 'when' label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_id": {"type": "integer"},
                "from_date": {"type": "string", "description": "Earliest date YYYY-MM-DD (optional)."},
                "to_date": {"type": "string", "description": "Latest date YYYY-MM-DD (optional)."},
                "practitioner_id": {"type": "integer", "description": "Optional specific practitioner."},
                "time_preference": {"type": "string", "enum": ["morning", "afternoon", "evening"]},
            },
            "required": ["service_id"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book one of the slots returned by check_availability. Pass the exact slot_token. Returns a confirmation, or a conflict with alternative slots if the slot was just taken.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slot_token": {"type": "string"},
                "patient_name": {"type": "string", "description": "Patient's name if not already known."},
            },
            "required": ["slot_token"],
        },
    },
    {
        "name": "get_patient_appointments",
        "description": "List this patient's upcoming appointments.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Hand off to clinic staff. Use when the patient wants a person or you cannot help. Pauses the bot on this conversation.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
        },
    },
]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


# --- Executors --------------------------------------------------------------

def execute_tool(ctx: ConvContext, name: str, raw_input: dict) -> dict:
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown_tool:{name}"}
    try:
        return handler(ctx, raw_input)
    except ValidationError as exc:
        return {"error": "invalid_input", "detail": exc.errors()}


def _get_services(ctx: ConvContext, _raw: dict) -> dict:
    services = Service.objects.filter(clinic=ctx.clinic, is_active=True).order_by("name")
    return {
        "services": [
            {
                "id": s.id,
                "name": s.name,
                "duration_min": s.duration_min,
                "price": s.price_display or None,
                "requires_practitioner": s.requires_practitioner,
            }
            for s in services
        ]
    }


def _get_faq_answer(ctx: ConvContext, raw: dict) -> dict:
    data = FaqInput(**raw)
    topic = data.topic.lower()
    best = None
    for faq in FAQEntry.objects.filter(clinic=ctx.clinic):
        haystack = f"{faq.question_patterns} {faq.category}".lower()
        if any(word in haystack for word in topic.split()) or topic in haystack:
            best = faq
            break
    if best is None:
        return {"answer": None}
    return {"answer": best.answer_en, "category": best.category}


def _check_availability(ctx: ConvContext, raw: dict) -> dict:
    data = AvailabilityInput(**raw)
    try:
        service = Service.objects.get(id=data.service_id, clinic=ctx.clinic, is_active=True)
    except Service.DoesNotExist:
        return {"error": "unknown_service"}
    practitioner = None
    if data.practitioner_id:
        practitioner = Practitioner.objects.filter(
            id=data.practitioner_id, clinic=ctx.clinic
        ).first()
    tz = ZoneInfo(ctx.clinic.timezone)
    slots = available_slots(
        ctx.clinic,
        service,
        start_date=_parse_date(data.from_date),
        end_date=_parse_date(data.to_date),
        practitioner=practitioner,
        time_preference=data.time_preference,
        limit=6,
    )
    return {
        "service": service.name,
        "slots": [{"slot_token": s.token, "when": s.label(tz)} for s in slots],
    }


def _book_appointment(ctx: ConvContext, raw: dict) -> dict:
    data = BookInput(**raw)
    if data.patient_name and not ctx.patient.name:
        ctx.patient.name = data.patient_name.strip()[:200]
        ctx.patient.save(update_fields=["name"])

    result = book_slot(ctx.clinic, ctx.patient, data.slot_token)
    tz = ZoneInfo(ctx.clinic.timezone)
    if result.ok:
        appt = result.appointment
        local = appt.starts_at.astimezone(tz)
        return {
            "booked": True,
            "appointment_id": appt.id,
            "service": appt.service.name,
            "when": local.strftime("%a, %b %-d, %-I:%M %p"),
            "address": ctx.clinic.address or None,
            "cancellation_policy": ctx.clinic.cancellation_policy or None,
            "new_patient_form": ctx.clinic.new_patient_form_url or None,
        }
    if result.error and result.error.startswith("invalid_slot"):
        return {
            "booked": False,
            "error": "invalid_slot_token",
            "hint": "That slot_token is not one I issued. Call check_availability "
            "and book with the exact opaque slot_token it returns — never construct "
            "a token yourself.",
        }
    payload = {"booked": False, "error": result.error}
    if result.alternatives:
        payload["alternatives"] = [
            {"slot_token": s.token, "when": s.label(tz)} for s in result.alternatives
        ]
    return payload


def _get_patient_appointments(ctx: ConvContext, raw: dict) -> dict:
    data = AppointmentsInput(**raw)
    qs = Appointment.objects.filter(
        clinic=ctx.clinic, patient=ctx.patient, starts_at__gte=timezone.now()
    )
    if data.status:
        qs = qs.filter(status=data.status)
    else:
        qs = qs.filter(status__in=ACTIVE_STATUSES)
    tz = ZoneInfo(ctx.clinic.timezone)
    return {
        "appointments": [
            {
                "id": a.id,
                "service": a.service.name,
                "when": a.starts_at.astimezone(tz).strftime("%a, %b %-d, %-I:%M %p"),
                "status": a.status,
            }
            for a in qs.order_by("starts_at")
        ]
    }


def _escalate_to_human(ctx: ConvContext, raw: dict) -> dict:
    data = EscalateInput(**raw)
    EscalationTicket.objects.create(
        clinic=ctx.clinic, conversation=ctx.conversation, reason=data.reason[:255]
    )
    ctx.conversation.bot_paused = True
    ctx.conversation.status = ConversationStatus.ESCALATED
    ctx.conversation.save(update_fields=["bot_paused", "status"])
    return {"escalated": True}


_HANDLERS = {
    "get_services": _get_services,
    "get_faq_answer": _get_faq_answer,
    "check_availability": _check_availability,
    "book_appointment": _book_appointment,
    "get_patient_appointments": _get_patient_appointments,
    "escalate_to_human": _escalate_to_human,
}
