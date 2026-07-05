"""Structured bot reply. A reply is always text, and may additionally carry an
`interactive` payload (tappable options) that channels render natively where they
can and degrade to a numbered text list where they can't."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BotReply:
    text: str
    # {"body": str, "options": [{"id": str, "title": str, "description": str}],
    #  "button_label": str, "footer": str}
    interactive: dict | None = None

    @property
    def has_options(self) -> bool:
        return bool(self.interactive and self.interactive.get("options"))


def render_options_as_text(interactive: dict) -> str:
    """Fallback rendering for channels without interactive support (and for
    message history): the body followed by a numbered list of the option titles."""
    lines = [interactive.get("body", "").strip()]
    for i, opt in enumerate(interactive.get("options", []), start=1):
        title = opt.get("title", "")
        desc = opt.get("description")
        lines.append(f"{i}. {title}" + (f" — {desc}" if desc else ""))
    footer = interactive.get("footer")
    if footer:
        lines.append(footer)
    return "\n".join(l for l in lines if l).strip()
