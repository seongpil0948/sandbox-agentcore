"""Small shared Block Kit builders used by Slack workflows and slash commands."""

from __future__ import annotations

import json
from typing import Any


def plain_text(text: str, emoji: bool = True) -> dict[str, Any]:
    return {"type": "plain_text", "text": text, "emoji": emoji}


def mrkdwn(text: str) -> dict[str, str]:
    return {"type": "mrkdwn", "text": text}


def button(
    text: str, action_id: str, value: dict[str, str], style: str | None = None
) -> dict[str, Any]:
    element: dict[str, Any] = {
        "type": "button",
        "text": plain_text(text),
        "action_id": action_id,
        "value": json.dumps(value, separators=(",", ":")),
    }
    if style:
        element["style"] = style
    return element


def option(text: str, value: str) -> dict[str, Any]:
    return {"text": plain_text(text[:75]), "value": value[:75]}
