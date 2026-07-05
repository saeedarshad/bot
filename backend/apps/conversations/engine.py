"""Conversation engine: the Anthropic tool-use loop plus the code-side guardrails
that make the bot safe regardless of what the model does."""
from __future__ import annotations

import json
import logging
import re

from django.conf import settings

from .emergency import emergency_reply, is_emergency
from .models import EscalationTicket
from .prompt import PROMPT_VERSION, build_system_prompt
from .reply import BotReply
from .tools import TOOL_DEFS, ConvContext, execute_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ITERS = 6
MAX_LLM_ATTEMPTS = 3
FALLBACK = "I'm having trouble right now — a staff member will get back to you shortly."

# Conservative medical-advice detector for the outbound filter. Only fires on
# clear advice/diagnosis phrasing so normal booking replies pass untouched.
_ADVICE_RE = re.compile(
    r"\b(you (probably|likely|may) have|i (think|believe) you have|diagnos|"
    r"\d+\s?mg\b|take \d+|prescrib|you should take)\b",
    re.IGNORECASE,
)
_ADVICE_REPLY = (
    "I can't give medical advice, but the doctor will be glad to discuss that "
    "at your appointment. Would you like me to help you book a time?"
)

# Anti-false-confirmation guardrail. The model has been observed telling a patient
# an appointment was booked/moved/cancelled without actually calling the tool that
# performs it — a serious correctness bug (patient believes they have an
# appointment they don't). We detect confirmation phrasing in the outgoing reply
# and only allow it if the matching mutating tool actually SUCCEEDED this turn.
_CONFIRM_PATTERNS = {
    "book": re.compile(
        r"\b(all set|all booked|you'?re booked|booked (you|your)|is booked|"
        r"you'?re confirmed|is confirmed|see you (on|then))\b",
        re.IGNORECASE,
    ),
    "reschedule": re.compile(
        r"\b(moved (it |your )?to|rescheduled|switched (it )?to|changed (it )?to|"
        r"now booked for|is now (on |at )?"
        r"(mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d))",
        re.IGNORECASE,
    ),
    "cancel": re.compile(r"\b(cancell?ed|has been cancell?ed)\b", re.IGNORECASE),
}
_CORRECTION = (
    "STOP. You just told the patient an appointment was booked, moved, or "
    "cancelled, but you did NOT successfully call the tool that performs it this "
    "turn. Never claim an action is done unless its tool returned success. Do the "
    "action now: to book or reschedule, call check_availability and then "
    "book_appointment / reschedule_appointment with a real slot_token; to cancel, "
    "call cancel_appointment. If you are missing something, ask the patient the one "
    "question you need instead of confirming."
)


def _record_success(succeeded: set[str], name: str, out: dict) -> None:
    if name == "book_appointment" and out.get("booked"):
        succeeded.add("book")
    elif name == "reschedule_appointment" and out.get("rescheduled"):
        succeeded.add("reschedule")
    elif name == "cancel_appointment" and out.get("cancelled"):
        succeeded.add("cancel")


def _false_confirmation(text: str, succeeded: set[str]) -> str | None:
    """Return the action the reply falsely confirms, or None. A reschedule that
    genuinely succeeded also satisfies book-style phrasing, and vice versa."""
    for action, pattern in _CONFIRM_PATTERNS.items():
        if action in succeeded:
            continue
        if action in ("book", "reschedule") and succeeded & {"book", "reschedule"}:
            # A real booking/reschedule happened; don't second-guess the wording.
            continue
        if pattern.search(text):
            return action
    return None


def _client():
    import anthropic  # imported lazily so the app boots without the key/SDK

    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _serialize_assistant(content) -> list[dict]:
    out: list[dict] = []
    for block in content:
        if block.type == "text":
            out.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            out.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
            )
    return out


def _output_filter(text: str) -> str:
    if _ADVICE_RE.search(text):
        logger.info("Outbound blocked by medical-advice filter")
        return _ADVICE_REPLY
    return text


def _escalate(ctx: ConvContext, reason: str) -> None:
    EscalationTicket.objects.create(
        clinic=ctx.clinic, conversation=ctx.conversation, reason=reason[:255]
    )


def generate_reply(ctx: ConvContext, history: list[dict], inbound_text: str) -> BotReply:
    """Produce the bot's reply for the latest inbound message.

    `history` is the full Anthropic-format message list ending with the current
    patient turn. Emergencies bypass the model entirely.
    """
    ctx.conversation.prompt_version = PROMPT_VERSION

    if is_emergency(inbound_text):
        logger.info("Emergency fast-path triggered")
        _escalate(ctx, "emergency keyword")
        return BotReply(text=emergency_reply(ctx.clinic))

    system = build_system_prompt(ctx.clinic, ctx.patient)
    messages = list(history)

    for attempt in range(MAX_LLM_ATTEMPTS):
        try:
            return _run_tool_loop(ctx, system, messages)
        except Exception:  # noqa: BLE001 — any SDK/tool failure falls back safely
            logger.exception("LLM turn failed (attempt %s)", attempt + 1)

    _escalate(ctx, "llm_failure")
    return BotReply(text=FALLBACK)


def _run_tool_loop(ctx: ConvContext, system: str, messages: list[dict]) -> BotReply:
    client = _client()
    # Options set by present_options in the most recent tool-use iteration; carried
    # forward to the end-of-turn reply. Reset each iteration so only the last one
    # (e.g. a slot offer) attaches, not a stale earlier one.
    last_interactive: dict | None = None
    # Mutating tools that actually succeeded this turn (see _false_confirmation).
    succeeded: set[str] = set()
    corrected = False
    for _ in range(MAX_TOOL_ITERS):
        ctx.interactive = None
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=system,
            tools=TOOL_DEFS,
            messages=messages,
        )
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": _serialize_assistant(resp.content)})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out = execute_tool(ctx, block.name, block.input or {})
                    _record_success(succeeded, block.name, out)
                    logger.info(
                        "tool_call conv=%s %s input=%s result=%s",
                        ctx.conversation.id,
                        block.name,
                        json.dumps(block.input or {})[:300],
                        json.dumps(out)[:300],
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(out),
                        }
                    )
            messages.append({"role": "user", "content": results})
            last_interactive = ctx.interactive
            continue

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        # If the model presented tappable options, that payload's body is the
        # message; use any free text only as a fallback body.
        if last_interactive:
            interactive = dict(last_interactive)
            if not interactive.get("body"):
                interactive["body"] = text or FALLBACK
            out_text = interactive["body"]
        else:
            interactive = None
            out_text = text or FALLBACK

        false_action = _false_confirmation(out_text, succeeded)
        if false_action:
            if not corrected:
                # Give the model exactly one chance to actually perform the action
                # it just claimed, then re-evaluate.
                corrected = True
                messages.append({"role": "assistant", "content": _serialize_assistant(resp.content)})
                messages.append({"role": "user", "content": [{"type": "text", "text": _CORRECTION}]})
                last_interactive = None
                continue
            logger.warning(
                "conv=%s persistent false %s confirmation; escalating",
                ctx.conversation.id,
                false_action,
            )
            _escalate(ctx, f"false_confirmation:{false_action}")
            return BotReply(text=FALLBACK)

        filtered = _output_filter(out_text)
        if interactive is not None:
            interactive["body"] = filtered
            return BotReply(text=filtered, interactive=interactive)
        return BotReply(text=filtered)

    logger.warning("Tool loop exhausted without a final reply")
    return BotReply(text=FALLBACK)
