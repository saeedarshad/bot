"""Emergency keyword fast-path. Runs BEFORE the LLM: if a patient message looks
like a medical emergency we respond immediately with the clinic's emergency number
and escalate, never routing the text through the model."""
from __future__ import annotations

import re

# English defaults. Per-clinic language lists can extend these later (config).
_EMERGENCY_PATTERNS = [
    r"\bcan'?t breathe\b",
    r"\bnot breathing\b",
    r"\bunconscious\b",
    r"\bpassed out\b",
    r"\bsevere (pain|bleeding)\b",
    r"\bbleeding (a lot|heavily|badly|won'?t stop)\b",
    r"\bwon'?t stop bleeding\b",
    r"\bchest pain\b",
    r"\bheart attack\b",
    r"\bstroke\b",
    r"\boverdose\b",
    r"\ballergic reaction\b",
    r"\banaphyla",
    r"\bsuicid",
    r"\bemergency\b",
    r"\b911\b",
]
_EMERGENCY_RE = re.compile("|".join(_EMERGENCY_PATTERNS), re.IGNORECASE)


def is_emergency(text: str) -> bool:
    return bool(_EMERGENCY_RE.search(text or ""))


def emergency_reply(clinic) -> str:
    if clinic.emergency_phone:
        return (
            "This may be a medical emergency. If so, please call emergency services "
            f"(911) now, or call us at {clinic.emergency_phone}. I'm not able to help "
            "with medical situations over text."
        )
    return (
        "This may be a medical emergency. Please call 911 or go to the nearest "
        "emergency room now. I'm not able to help with medical situations over text."
    )
