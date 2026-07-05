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
            return BotReply(text=_output_filter(interactive["body"]), interactive=interactive)
        return BotReply(text=_output_filter(text or FALLBACK))

    logger.warning("Tool loop exhausted without a final reply")
    return BotReply(text=FALLBACK)
