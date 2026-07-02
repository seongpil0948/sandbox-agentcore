from __future__ import annotations

from typing import Any

import pytest

from apps.slack.workflows import (
    ACTION_CERT_DETAILS,
    ACTION_CERT_RENEW,
    ACTION_HITL_APPROVE,
    ACTION_HITL_CANCEL,
    ACTION_HITL_SELECT,
    ACTION_WORKFLOW_CANCEL,
    ACTION_WORKFLOW_IGNORE,
    ACTION_WORKFLOW_RESUME,
    build_account_notice_blocks,
    build_action_response,
    build_agent_response_blocks,
    build_agent_response_text,
    build_certificate_notice_blocks,
    build_hitl_options,
    build_interrupt_blocks,
    maybe_send_invocation_notification,
)


class _FakeSlackClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def chat_postMessage(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    def chat_update(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


def test_certificate_notice_uses_block_kit_buttons() -> None:
    text, blocks = build_certificate_notice_blocks("api.example.com", "7")

    assert text == "api.example.com 인증서가 7일 후 만료됩니다."
    action_block = blocks[-1]
    action_ids = [element["action_id"] for element in action_block["elements"]]
    assert action_ids == [ACTION_CERT_RENEW, ACTION_WORKFLOW_IGNORE, ACTION_CERT_DETAILS]


def test_account_notice_uses_operation_specific_button() -> None:
    text, blocks = build_account_notice_blocks("delete", "deploy-bot")

    assert "deploy-bot 계정 삭제 요청" in text
    assert blocks[-1]["elements"][0]["text"]["text"] == "삭제 실행"


def test_build_action_response_routes_supported_actions() -> None:
    value = {"kind": "cert", "target": "nginx.internal", "days": "7"}

    detail_text, detail_blocks = build_action_response(ACTION_CERT_DETAILS, value) or ("", [])
    cancel_text, _ = build_action_response(ACTION_WORKFLOW_CANCEL, value) or ("", [])
    resume_text, _ = build_action_response(ACTION_WORKFLOW_RESUME, value) or ("", [])

    assert "승인 필요" in detail_text
    assert "nginx.internal" in detail_blocks[0]["text"]["text"]
    assert "취소" in cancel_text
    assert "재개" in resume_text
    assert build_action_response("unsupported", value) is None


# --------------------------------------------------------------------------------------
# Agent-driven interrupt (HITL) rendering, dispatched on reason["kind"]
# --------------------------------------------------------------------------------------
def _action_ids(blocks: list[dict[str, Any]]) -> list[str]:
    return [
        element["action_id"]
        for block in blocks
        if block["type"] == "actions"
        for element in block["elements"]
    ]


def test_interrupt_blocks_cert_selection_renders_external_select() -> None:
    reason = {
        "kind": "cert_selection",
        "prompt": "갱신할 인증서를 선택하세요.",
        "options": [{"value": "nginx.internal", "label": "nginx.internal (expiring_soon, 7d)"}],
    }
    text, blocks = build_interrupt_blocks(reason, "slack-C123-1", "int-9")

    assert text
    select_block = next(b for b in blocks if b.get("accessory"))
    accessory = select_block["accessory"]
    assert accessory["type"] == "external_select"
    assert accessory["action_id"] == ACTION_HITL_SELECT
    # resume context is encoded in the block_id so the select choice can be routed back.
    assert '"session":"slack-C123-1"' in select_block["block_id"]
    assert '"interrupt_id":"int-9"' in select_block["block_id"]


def test_interrupt_blocks_cert_renewal_shows_management_method() -> None:
    reason = {
        "kind": "cert_renewal",
        "title": "인증서 갱신 승인 — nginx.internal",
        "record": {
            "domain": "nginx.internal",
            "cert_type": "certbot-dns-route53",
            "status": "expiring_soon",
            "managed_via": "ssh",
            "management_endpoint": "ssh://deploy@nginx.internal",
            "renewal_eligible": True,
        },
    }
    text, blocks = build_interrupt_blocks(reason, "slack-C123-1", "int-1")

    assert "nginx.internal" in text
    body = "\n".join(b["text"]["text"] for b in blocks if b.get("type") == "section")
    assert "ssh" in body
    assert "ssh://deploy@nginx.internal" in body
    assert _action_ids(blocks) == [ACTION_HITL_APPROVE, ACTION_HITL_CANCEL]


def test_interrupt_blocks_account_delete_lists_linked_resources() -> None:
    reason = {
        "kind": "account_delete",
        "title": "계정 종료 승인 — deploy-bot",
        "record": {"principal": "deploy-bot", "type": "service_account", "owner": "platform-team"},
        "linked_resources": {
            "certificates": ["nginx.internal"],
            "secrets": ["deploy-bot-signing-key"],
        },
    }
    text, blocks = build_interrupt_blocks(reason, "slack-C123-1", "int-2")

    body = "\n".join(b["text"]["text"] for b in blocks if b.get("type") == "section")
    assert "deploy-bot" in body
    assert "nginx.internal" in body
    assert "deploy-bot-signing-key" in body
    assert _action_ids(blocks) == [ACTION_HITL_APPROVE, ACTION_HITL_CANCEL]


def test_interrupt_blocks_approve_button_carries_response_key() -> None:
    reason = {"kind": "cert_renewal", "record": {"domain": "nginx.internal"}}
    _text, blocks = build_interrupt_blocks(reason, "slack-C123-1", "int-1")
    approve = next(
        element
        for block in blocks
        if block["type"] == "actions"
        for element in block["elements"]
        if element["action_id"] == ACTION_HITL_APPROVE
    )
    assert '"response":"approve"' in approve["value"]
    assert '"session":"slack-C123-1"' in approve["value"]


def test_build_hitl_options_returns_certificate_choices() -> None:
    options = build_hitl_options(ACTION_HITL_SELECT, "nginx")
    values = {opt["value"] for opt in options}
    assert "nginx.internal" in values
    assert build_hitl_options("other_action", "nginx") == []


def test_maybe_send_invocation_notification_posts_certificate_notice(
    monkeypatch,
) -> None:
    fake_client = _FakeSlackClient()
    monkeypatch.setenv("SLACK_NOTIFICATION_CHANNEL_ID", "C123")

    result = maybe_send_invocation_notification(
        "api.example.com 인증서가 7일 후 만료됩니다.",
        client=fake_client,
    )

    assert result == "api.example.com 인증서가 7일 후 만료됩니다."
    assert fake_client.messages[0]["channel"] == "C123"
    assert fake_client.messages[0]["blocks"][-1]["type"] == "actions"


def test_maybe_send_invocation_notification_posts_account_notice(monkeypatch) -> None:
    fake_client = _FakeSlackClient()
    monkeypatch.setenv("SLACK_NOTIFICATION_CHANNEL_ID", "C123")

    result = maybe_send_invocation_notification(
        "deploy-bot 계정 삭제 요청",
        client=fake_client,
    )

    assert result == "deploy-bot 계정 삭제 요청이 접수되었습니다."
    assert fake_client.messages[0]["text"] == result


def test_maybe_send_invocation_notification_logs_missing_channel(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_client = _FakeSlackClient()
    monkeypatch.delenv("SLACK_NOTIFICATION_CHANNEL_ID", raising=False)
    monkeypatch.delenv("SLACK_ALERT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)

    with caplog.at_level("INFO"):
        result = maybe_send_invocation_notification(
            "api.example.com 인증서가 7일 후 만료됩니다.",
            client=fake_client,
        )

    assert result is None
    assert fake_client.messages == []
    assert "missing SLACK_NOTIFICATION_CHANNEL_ID" in caplog.text


def test_maybe_send_invocation_notification_logs_missing_bot_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SLACK_NOTIFICATION_CHANNEL_ID", "C123")
    monkeypatch.delenv("SLACK_BOT_USER_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    with caplog.at_level("INFO"):
        result = maybe_send_invocation_notification("api.example.com 인증서가 7일 후 만료됩니다.")

    assert result is None
    assert "missing SLACK_BOT_USER_OAUTH_TOKEN" in caplog.text


def test_agent_response_markdown_is_normalized_for_slack() -> None:
    answer = """## Certificate Status for nginx.internal

The certificate for **nginx.internal** is in a **critical state**.

- **Status**: Expiring Soon
- **Days Remaining**: 7 days

### Recommended Next Steps
1. **Proceed with renewal**
"""

    fallback = build_agent_response_text(answer)
    blocks = build_agent_response_blocks(answer)
    rendered = "\n".join(
        block["text"]["text"]
        for block in blocks
        if block["type"] in {"header", "section"} and "text" in block
    )

    assert "##" not in fallback
    assert "**" not in fallback
    assert "##" not in rendered
    assert "**" not in rendered
    assert "Certificate Status for nginx.internal" in rendered
    assert "• *Status*: Expiring Soon" in rendered
