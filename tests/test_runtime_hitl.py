from __future__ import annotations

from typing import Any

import pytest
from strands.interrupt import Interrupt

from apps.agents.leaf_account_manager import _account_reason
from apps.agents.leaf_cert import (
    _execute_renewal,
    _renewal_reason,
    _selection_reason,
)
from apps.mock_data import get_certificate
from apps.runtime import hitl
from apps.runtime.session import build_session_manager, slack_session_key


# --------------------------------------------------------------------------------------
# session factory
# --------------------------------------------------------------------------------------
def test_slack_session_key_is_filesystem_safe() -> None:
    assert slack_session_key("C123", "1700000000.0001") == "slack-C123-1700000000-0001"


def test_build_session_manager_falls_back_to_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.delenv("AGENTCORE_MEMORY_ID", raising=False)
    monkeypatch.setenv("SANDBOX_AGENTCORE_SESSION_DIR", str(tmp_path))

    manager = build_session_manager("session-abc")

    assert manager is not None
    assert type(manager).__name__ == "FileSessionManager"


# --------------------------------------------------------------------------------------
# HITL engine outcome mapping + start/resume glue
# --------------------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, stop_reason: str, interrupts: list[Interrupt] | None = None) -> None:
        self.stop_reason = stop_reason
        self.interrupts = interrupts


class _FakeAgent:
    def __init__(self, result: _FakeResult) -> None:
        self.result = result
        self.calls: list[Any] = []

    def __call__(self, prompt: Any) -> _FakeResult:
        self.calls.append(prompt)
        return self.result


@pytest.fixture(autouse=True)
def _reset_hitl_state() -> Any:
    """Clear per-session HITL globals so lock/dedup state can't leak across tests."""
    hitl._agents.clear()
    hitl._session_locks.clear()
    hitl._resolved_interrupts.clear()
    yield
    hitl._agents.clear()
    hitl._session_locks.clear()
    hitl._resolved_interrupts.clear()


def test_outcome_from_result_maps_interrupt() -> None:
    result = _FakeResult(
        "interrupt", [Interrupt(id="int-1", name="cert_renewal_approval", reason={"domain": "x"})]
    )
    outcome = hitl.outcome_from_result(result)
    assert outcome.status == hitl.STATUS_INTERRUPT
    assert outcome.interrupt_id == "int-1"
    assert outcome.interrupt_name == "cert_renewal_approval"
    assert outcome.reason == {"domain": "x"}


def test_outcome_from_result_maps_final(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hitl, "extract_text", lambda result: "final answer")
    outcome = hitl.outcome_from_result(_FakeResult("end_turn"))
    assert outcome.status == hitl.STATUS_FINAL
    assert outcome.text == "final answer"


def test_start_returns_final_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent = _FakeAgent(_FakeResult("end_turn"))
    monkeypatch.setattr(hitl, "_get_or_build_agent", lambda session_id, role: fake_agent)
    monkeypatch.setattr(hitl, "extract_text", lambda result: "hello")

    outcome = hitl.start("s1", "cert renew")

    assert outcome.status == hitl.STATUS_FINAL
    assert outcome.text == "hello"
    assert fake_agent.calls == ["cert renew"]


def test_resume_sends_interrupt_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent = _FakeAgent(_FakeResult("end_turn"))
    monkeypatch.setattr(hitl, "_get_or_build_agent", lambda session_id, role: fake_agent)
    monkeypatch.setattr(hitl, "extract_text", lambda result: "done")

    outcome = hitl.resume("s1", "int-1", "approve")

    assert outcome.status == hitl.STATUS_FINAL
    assert fake_agent.calls == [
        [{"interruptResponse": {"interruptId": "int-1", "response": "approve"}}]
    ]


def test_resume_dedups_already_answered_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent = _FakeAgent(_FakeResult("end_turn"))
    monkeypatch.setattr(hitl, "_get_or_build_agent", lambda session_id, role: fake_agent)
    monkeypatch.setattr(hitl, "extract_text", lambda result: "done")

    first = hitl.resume("dedup-s", "int-dup", "approve")
    second = hitl.resume("dedup-s", "int-dup", "approve")

    assert first.status == hitl.STATUS_FINAL
    assert second.status == hitl.STATUS_BUSY  # duplicate click ignored
    assert len(fake_agent.calls) == 1  # agent invoked only once


def test_resume_returns_busy_when_session_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _should_not_run(session_id: str, role: str) -> Any:
        nonlocal called
        called = True
        raise AssertionError("agent must not be invoked while the session is locked")

    monkeypatch.setattr(hitl, "_get_or_build_agent", _should_not_run)

    lock = hitl._session_lock("busy-s")
    lock.acquire()
    try:
        outcome = hitl.resume("busy-s", "int-x", "approve")
    finally:
        lock.release()

    assert outcome.status == hitl.STATUS_BUSY
    assert called is False


# --------------------------------------------------------------------------------------
# cert leaf write-tool interrupt payloads (rendered by the Slack layer)
# --------------------------------------------------------------------------------------
def test_cert_selection_reason_lists_all_certificates() -> None:
    reason = _selection_reason()
    assert reason["kind"] == "cert_selection"
    values = {opt["value"] for opt in reason["options"]}
    assert "nginx.internal" in values
    assert "api.example.com" in values


def test_cert_renewal_reason_carries_management_method() -> None:
    record = get_certificate("nginx.internal")
    assert record is not None
    reason = _renewal_reason(record)
    assert reason["kind"] == "cert_renewal"
    assert reason["record"]["managed_via"] == "ssh"
    assert reason["record"]["management_endpoint"] == "ssh://deploy@nginx.internal"


def test_execute_renewal_records_ssh_path() -> None:
    record = get_certificate("nginx.internal")
    assert record is not None
    result = _execute_renewal(record)
    assert "nginx -s reload" in result
    assert "ssh://deploy@nginx.internal" in result
    assert "no live change" in result


def test_execute_renewal_records_acm_api_path() -> None:
    record = get_certificate("api.example.com")
    assert record is not None
    result = _execute_renewal(record)
    assert "ACM renewal" in result
    assert "https://acm.us-east-1.amazonaws.com" in result


def test_execute_renewal_flags_non_eligible_cert() -> None:
    record = get_certificate("old.example.com")
    assert record is not None
    result = _execute_renewal(record)
    assert "not auto-renewable" in result


# --------------------------------------------------------------------------------------
# account-manager write-tool interrupt payloads
# --------------------------------------------------------------------------------------
def test_account_delete_reason_includes_linked_resources() -> None:
    reason = _account_reason("account_delete", "계정 종료 승인 — deploy-bot", "deploy-bot", {})
    assert reason["kind"] == "account_delete"
    assert reason["record"]["type"] == "service_account"
    assert reason["linked_resources"]["certificates"] == ["nginx.internal"]
    assert reason["linked_resources"]["secrets"] == ["deploy-bot-signing-key"]


def test_account_create_reason_carries_type_and_owner() -> None:
    reason = _account_reason(
        "account_create",
        "계정 생성 승인 — new-runner",
        "new-runner",
        {"type": "workload", "owner": "data-platform"},
    )
    assert reason["kind"] == "account_create"
    assert reason["record"]["type"] == "workload"
    assert reason["record"]["owner"] == "data-platform"
