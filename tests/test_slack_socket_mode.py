from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from slack_sdk.errors import SlackApiError

from apps.runtime.hitl import STATUS_BUSY, STATUS_FINAL, STATUS_INTERRUPT, HitlOutcome
from apps.slack import socket_mode as slack_socket_mode
from apps.slack.workflows import (
    ACTION_CERT_DETAILS,
    ACTION_CERT_RENEW,
    ACTION_HITL_APPROVE,
    ACTION_WORKFLOW_RESUME,
)


@dataclass
class _FakeRequest:
    type: str
    payload: dict[str, Any]
    envelope_id: str = "env-1"


class _FakeWebClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.opened_views: list[dict[str, Any]] = []
        self.updated_views: list[dict[str, Any]] = []

    def auth_test(self) -> dict[str, Any]:
        return {"team": "sandbox-aigroup", "user_id": "U123", "bot_id": "B123"}

    def chat_postMessage(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    def chat_update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def views_open(self, **kwargs: Any) -> None:
        self.opened_views.append(kwargs)

    def views_update(self, **kwargs: Any) -> None:
        self.updated_views.append(kwargs)


@dataclass
class _FakeClient:
    web_client: Any
    responses: list[Any] | None = None

    def send_socket_mode_response(self, response: Any) -> None:
        if self.responses is None:
            self.responses = []
        self.responses.append(response)


def _req(req_type: str, payload: dict[str, Any]) -> _FakeRequest:
    return _FakeRequest(type=req_type, payload=payload)


def test_resolve_env_prefers_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_APP_SOCKET_TOKEN", "xapp-primary")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-alias")
    assert (
        slack_socket_mode.resolve_env("SLACK_APP_SOCKET_TOKEN", "SLACK_APP_TOKEN") == "xapp-primary"
    )


def test_resolve_env_falls_back_to_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_APP_SOCKET_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-alias")
    assert (
        slack_socket_mode.resolve_env("SLACK_APP_SOCKET_TOKEN", "SLACK_APP_TOKEN") == "xapp-alias"
    )


def test_verify_bot_identity_logs_success(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        slack_socket_mode.verify_bot_identity(_FakeClient(web_client=_FakeWebClient()))

    assert "Slack bot identity verified" in caplog.text


def test_verify_bot_identity_raises_on_slack_error() -> None:
    class _FailingWebClient:
        def auth_test(self):
            raise SlackApiError(message="fail", response={"error": "invalid_auth"})

    fake_client = _FakeClient(web_client=_FailingWebClient())

    with pytest.raises(SlackApiError):
        slack_socket_mode.verify_bot_identity(fake_client)


def test_process_request_mention_posts_agent_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "events_api",
        {
            "event": {
                "type": "app_mention",
                "channel": "C123",
                "text": "<@U999> cert renew nginx.internal",
                "ts": "1700000000.0001",
            }
        },
    )

    captured: list[tuple[str, str]] = []

    def fake_start(session_id: str, prompt: str, role: str = "orchestrator") -> HitlOutcome:
        captured.append((session_id, prompt))
        return HitlOutcome(status=STATUS_FINAL, text="Certificate nginx.internal is valid.")

    monkeypatch.setattr(slack_socket_mode.hitl, "start", fake_start)

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    assert fake_client.responses
    assert captured and captured[0][1] == "cert renew nginx.internal"
    assert fake_web_client.messages[0]["thread_ts"] == "1700000000.0001"
    assert fake_web_client.messages[0]["blocks"][0]["type"] == "header"


def test_process_request_mention_posts_interrupt_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "events_api",
        {
            "event": {
                "type": "app_mention",
                "channel": "C123",
                "text": "<@U999> renew nginx.internal",
                "ts": "1700000000.0001",
            }
        },
    )

    def fake_start(session_id: str, prompt: str, role: str = "orchestrator") -> HitlOutcome:
        return HitlOutcome(
            status=STATUS_INTERRUPT,
            interrupt_id="int-1",
            interrupt_name="cert_renewal_approval",
            reason={"title": "Cert renewal", "summary": "nginx.internal"},
        )

    monkeypatch.setattr(slack_socket_mode.hitl, "start", fake_start)

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    message = fake_web_client.messages[0]
    action_ids = [
        element["action_id"]
        for block in message["blocks"]
        if block["type"] == "actions"
        for element in block["elements"]
    ]
    assert ACTION_HITL_APPROVE in action_ids


def test_process_request_handles_certificate_detail_action() -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": ACTION_CERT_DETAILS,
                    "value": '{"kind":"cert","target":"nginx.internal","days":"7"}',
                }
            ],
        },
    )

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    assert fake_client.responses
    update = fake_web_client.updates[0]
    assert update["channel"] == "C123"
    assert update["ts"] == "1700000000.0001"
    assert "승인 필요" in update["text"]
    assert any(
        element["action_id"] == ACTION_WORKFLOW_RESUME
        for block in update["blocks"]
        if block["type"] == "actions"
        for element in block["elements"]
    )


def test_process_request_handles_certificate_renew_action() -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": ACTION_CERT_RENEW,
                    "value": '{"kind":"cert","target":"nginx.internal","days":"7"}',
                }
            ],
        },
    )

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    update = fake_web_client.updates[0]
    assert "HITL interrupt" in update["blocks"][1]["text"]["text"]


@pytest.mark.parametrize(
    ("action_id", "expected_text"),
    [
        ("workflow_ignore", "무시"),
        ("workflow_cancel", "취소"),
        ("workflow_resume", "재개"),
    ],
)
def test_process_request_handles_terminal_workflow_actions(
    action_id: str,
    expected_text: str,
) -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": action_id,
                    "value": '{"kind":"cert","target":"nginx.internal","days":"7"}',
                }
            ],
        },
    )

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    assert expected_text in fake_web_client.updates[0]["text"]


def test_process_request_handles_account_execute_action() -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": "account_execute_request",
                    "value": '{"kind":"account","operation":"delete","target":"leaving.contractor"}',
                }
            ],
        },
    )

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    update = fake_web_client.updates[0]
    assert "계정 삭제 승인 필요" in update["text"]
    assert "legacy-repo-access" in update["blocks"][2]["text"]["text"]


def test_process_request_hitl_approve_resumes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": ACTION_HITL_APPROVE,
                    "value": (
                        '{"session":"slack-C123-1700000000-0001",'
                        '"interrupt_id":"int-1","response":"approve"}'
                    ),
                }
            ],
        },
    )

    captured: list[tuple[str, str, str]] = []

    def fake_resume(
        session_id: str, interrupt_id: str, response: str, role: str = "orchestrator"
    ) -> HitlOutcome:
        captured.append((session_id, interrupt_id, response))
        return HitlOutcome(status=STATUS_FINAL, text="Renewal approved and recorded.")

    monkeypatch.setattr(slack_socket_mode.hitl, "resume", fake_resume)

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    assert captured == [("slack-C123-1700000000-0001", "int-1", "approve")]
    update = fake_web_client.updates[0]
    assert update["channel"] == "C123"
    assert update["ts"] == "1700000000.0001"


def test_process_request_hitl_duplicate_click_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "interactive",
        {
            "type": "block_actions",
            "channel": {"id": "C123"},
            "message": {"ts": "1700000000.0001"},
            "actions": [
                {
                    "action_id": ACTION_HITL_APPROVE,
                    "value": (
                        '{"session":"slack-C123-1700000000-0001",'
                        '"interrupt_id":"int-1","response":"approve"}'
                    ),
                }
            ],
        },
    )
    monkeypatch.setattr(
        slack_socket_mode.hitl,
        "resume",
        lambda *args, **kwargs: HitlOutcome(status=STATUS_BUSY),
    )

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    # A busy (duplicate/concurrent) outcome must NOT touch the Slack message.
    assert fake_web_client.updates == []


def test_process_request_hitl_select_resumes_with_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
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

    captured: list[tuple[str, str, str]] = []

    def fake_resume(
        session_id: str, interrupt_id: str, response: str, role: str = "orchestrator"
    ) -> HitlOutcome:
        captured.append((session_id, interrupt_id, response))
        return HitlOutcome(
            status=STATUS_INTERRUPT,
            interrupt_id="int-9",
            interrupt_name="cert_renewal_approval",
            reason={"kind": "cert_renewal", "record": {"domain": "nginx.internal"}},
        )

    monkeypatch.setattr(slack_socket_mode.hitl, "resume", fake_resume)

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    assert captured == [("slack-C123-1", "int-9", "nginx.internal")]
    # A follow-up interrupt (renewal approval) is re-rendered as an update.
    assert fake_web_client.updates


def test_process_request_serves_hitl_select_options() -> None:
    fake_web_client = _FakeWebClient()
    fake_client = _FakeClient(web_client=fake_web_client)
    req = _req(
        "interactive",
        {"type": "block_suggestion", "action_id": "hitl_select", "value": "nginx"},
    )

    slack_socket_mode.process_request(fake_client, req)  # type: ignore[arg-type]

    assert fake_client.responses
    payload = fake_client.responses[0].payload
    assert "options" in payload
    values = {opt["value"] for opt in payload["options"]}
    assert "nginx.internal" in values


def test_start_in_thread_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_SOCKET_MODE_INPROCESS", "0")
    assert slack_socket_mode.start_in_thread() is None


def test_start_in_thread_skips_without_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_SOCKET_MODE_INPROCESS", raising=False)
    for var in (
        "SLACK_APP_SOCKET_TOKEN",
        "SLACK_APP_TOKEN",
        "SLACK_BOT_USER_OAUTH_TOKEN",
        "SLACK_BOT_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    assert slack_socket_mode.start_in_thread() is None
