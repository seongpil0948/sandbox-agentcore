from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from apps.slack.workflows import parse_action_value

MENTION_TOKEN_PATTERN = re.compile(r"<@[A-Z0-9]+>")


class SlackRequestLike(Protocol):
    @property
    def type(self) -> str: ...

    @property
    def payload(self) -> dict[Any, Any] | None: ...


@dataclass(frozen=True)
class SlackMessagePrompt:
    channel: str
    prompt: str
    thread_ts: str


@dataclass(frozen=True)
class SlackInteractiveAction:
    channel: str
    message_ts: str
    action_id: str
    value: dict[str, str]


@dataclass(frozen=True)
class SlackOptionsRequest:
    action_id: str
    value: str
    scope: str = ""


def normalize_prompt(text: str) -> str:
    # app_mention payloads include the raw mention token (e.g. <@U123>).
    normalized = MENTION_TOKEN_PATTERN.sub("", text)
    return " ".join(normalized.split()).strip()


def extract_message_prompt(req: SlackRequestLike) -> SlackMessagePrompt | None:
    if req.type != "events_api":
        return None

    payload = req.payload or {}
    event = payload.get("event", {})
    if not isinstance(event, dict):
        return None

    event_type = event.get("type")
    if event_type not in {"message", "app_mention"}:
        return None
    if event_type == "message" and event.get("subtype") is not None:
        return None

    channel = str(event.get("channel", "")).strip()
    text = normalize_prompt(str(event.get("text", "")))
    ts = str(event.get("ts", "")).strip()
    if not channel or not text or not ts:
        return None
    return SlackMessagePrompt(channel=channel, prompt=text, thread_ts=ts)


def extract_interactive_action(req: SlackRequestLike) -> SlackInteractiveAction | None:
    if req.type != "interactive":
        return None

    payload = req.payload or {}
    if payload.get("type") != "block_actions":
        return None

    actions = payload.get("actions", [])
    if not actions:
        return None
    action = actions[0]
    if not isinstance(action, dict):
        return None

    action_id = str(action.get("action_id", "")).strip()
    value = parse_action_value(str(action.get("value", "")))

    # external_select / static_select carry no button ``value``; the chosen option's value is the
    # human response and the resume context (session + interrupt id) is encoded in the block_id.
    selected = action.get("selected_option")
    if isinstance(selected, dict) and selected.get("value"):
        block_ctx = parse_action_value(str(action.get("block_id", "")))
        value = {**block_ctx, "response": str(selected.get("value"))}

    channel = payload.get("channel", {})
    message = payload.get("message", {})
    channel_id = str(channel.get("id", "")).strip() if isinstance(channel, dict) else ""
    message_ts = str(message.get("ts", "")).strip() if isinstance(message, dict) else ""
    if not action_id or not channel_id or not message_ts:
        return None
    return SlackInteractiveAction(
        channel=channel_id,
        message_ts=message_ts,
        action_id=action_id,
        value=value,
    )


def extract_options_request(req: SlackRequestLike) -> SlackOptionsRequest | None:
    """Extract an external_select options (block_suggestion) request over Socket Mode."""
    if req.type != "interactive":
        return None
    payload = req.payload or {}
    if payload.get("type") != "block_suggestion":
        return None
    action_id = str(payload.get("action_id", "")).strip()
    if not action_id:
        return None
    # Decode the scope hint from the block_id json (set when the interrupt was rendered).
    block_id = str(payload.get("block_id", ""))
    block_ctx = parse_action_value(block_id)
    scope = str(block_ctx.get("scope", ""))
    return SlackOptionsRequest(
        action_id=action_id, value=str(payload.get("value", "")), scope=scope
    )


def event_type_for_log(req: SlackRequestLike) -> str:
    payload = req.payload or {}
    event = payload.get("event", {})
    if req.type == "events_api" and isinstance(event, dict):
        return str(event.get("type", "events_api:unknown"))
    return req.type
