from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.slack.events import (
    SlackInteractiveAction,
    SlackMessagePrompt,
    event_type_for_log,
    extract_interactive_action,
    extract_message_prompt,
    extract_options_request,
)


@dataclass
class _FakeRequest:
    type: str
    payload: dict[str, Any]


def _req(req_type: str, payload: dict[str, Any]) -> _FakeRequest:
    return _FakeRequest(type=req_type, payload=payload)


def test_extract_message_prompt_returns_prompt_for_new_message() -> None:
    req = _req(
        "events_api",
        {
            "event": {
                "type": "message",
                "channel": "C123",
                "text": "hello",
                "ts": "1700000000.0001",
            }
        },
    )

    assert extract_message_prompt(req) == SlackMessagePrompt(
        channel="C123",
        prompt="hello",
        thread_ts="1700000000.0001",
    )


def test_extract_message_prompt_supports_app_mention() -> None:
    req = _req(
        "events_api",
        {
            "event": {
                "type": "app_mention",
                "channel": "C123",
                "text": "<@U999> Check certificate status for api.example.com",
                "ts": "1700000000.0001",
            }
        },
    )

    assert extract_message_prompt(req) == SlackMessagePrompt(
        channel="C123",
        prompt="Check certificate status for api.example.com",
        thread_ts="1700000000.0001",
    )


def test_extract_message_prompt_ignores_unsupported_events() -> None:
    req = _req("events_api", {"event": {"type": "reaction_added"}})
    assert extract_message_prompt(req) is None


def test_extract_message_prompt_ignores_subtype_messages() -> None:
    req = _req(
        "events_api",
        {
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel": "C123",
                "text": "hello",
                "ts": "1700000000.0001",
            }
        },
    )

    assert extract_message_prompt(req) is None


def test_extract_interactive_action_returns_first_block_action() -> None:
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": "hitl_approve",
                    "value": '{"session":"slack-C123-1","interrupt_id":"int-1","response":"approve"}',
                }
            ],
        },
    )

    assert extract_interactive_action(req) == SlackInteractiveAction(
        channel="C123",
        message_ts="1700000000.0001",
        action_id="hitl_approve",
        value={"session": "slack-C123-1", "interrupt_id": "int-1", "response": "approve"},
    )


def test_extract_interactive_action_reads_external_select_choice() -> None:
    """external_select carries no button value; the resume context lives in block_id and the
    chosen option's value becomes the human response."""
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": "hitl_select",
                    "block_id": '{"session":"slack-C123-1","interrupt_id":"int-9"}',
                    "selected_option": {"value": "nginx.internal"},
                }
            ],
        },
    )

    action = extract_interactive_action(req)
    assert action is not None
    assert action.action_id == "hitl_select"
    assert action.value == {
        "session": "slack-C123-1",
        "interrupt_id": "int-9",
        "response": "nginx.internal",
    }


def test_extract_interactive_action_ignores_malformed_action() -> None:
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": ["not-a-dict"],
        },
    )

    assert extract_interactive_action(req) is None


def test_extract_options_request_returns_action_and_value() -> None:
    req = _req(
        "interactive",
        {"type": "block_suggestion", "action_id": "hitl_select", "value": "ngin"},
    )
    options = extract_options_request(req)
    assert options is not None
    assert options.action_id == "hitl_select"
    assert options.value == "ngin"


def test_extract_options_request_ignores_other_types() -> None:
    assert extract_options_request(_req("interactive", {"type": "block_actions"})) is None


def test_event_type_for_log_events_api() -> None:
    req = _req("events_api", {"event": {"type": "app_mention"}})
    assert event_type_for_log(req) == "app_mention"


def test_event_type_for_log_non_events_api() -> None:
    req = _req("interactive", {"type": "block_suggestion"})
    assert event_type_for_log(req) == "interactive"
