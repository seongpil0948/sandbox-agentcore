"""In-process human-in-the-loop (HITL) engine built on Strands interrupts.

Both entry points — the Slack Socket Mode thread and the AgentCore ``/invocations``
endpoint — call :func:`start` / :func:`resume` here, so mentions and direct prompts share
one orchestrator -> supervisor -> leaf hierarchy and one interrupt/session lifecycle.

Flow:

1. :func:`start` runs a prompt on the session's agent. If a leaf write-tool raised an
   interrupt (``AgentResult.stop_reason == "interrupt"``), the outcome carries the
   interrupt id/name/reason (a Block Kit payload) instead of final text.
2. The caller renders the reason to Slack with approve/cancel controls.
3. :func:`resume` feeds the human decision back into the *same* live agent via an
   ``interruptResponse`` and returns the next outcome (final text or another interrupt).

The live agent per session is cached in-process so a resume reuses the exact instance
(and its nested leaf agents) that paused. The session manager adds cross-restart
durability for the top-level conversation and interrupt state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any

from strands import Agent
from strands.models import BedrockModel

from apps.runtime.roles import AGENT_ROLE_ORCHESTRATOR, MODEL_ID, build_agent
from apps.runtime.session import build_session_manager
from apps.utils.response import extract_text

logger = logging.getLogger(__name__)

STATUS_FINAL = "final"
STATUS_INTERRUPT = "interrupt"
STATUS_BUSY = "busy"

_STOP_REASON_INTERRUPT = "interrupt"

_agents: dict[str, Agent] = {}
_agents_lock = Lock()
# Serializes turns per session so a rapid double-click (two Socket Mode envelopes) can't invoke
# the same cached agent concurrently (Strands raises ConcurrencyException). Also dedups an
# already-answered interrupt id so a late duplicate click is ignored rather than reprocessed.
_session_locks: dict[str, Lock] = {}
_resolved_interrupts: dict[str, set[str]] = {}


@dataclass(frozen=True)
class HitlOutcome:
    """Result of a HITL turn: either final text or a pending interrupt to render."""

    status: str  # STATUS_FINAL | STATUS_INTERRUPT | STATUS_BUSY
    text: str = ""
    interrupt_id: str = ""
    interrupt_name: str = ""
    reason: Any = None


def _model() -> BedrockModel:
    return BedrockModel(model_id=MODEL_ID)


def _session_lock(session_id: str) -> Lock:
    with _agents_lock:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = Lock()
            _session_locks[session_id] = lock
        return lock


def _get_or_build_agent(session_id: str, role: str) -> Agent:
    with _agents_lock:
        agent = _agents.get(session_id)
        if agent is None:
            agent = build_agent(role, _model(), session_manager=build_session_manager(session_id))
            _agents[session_id] = agent
        return agent


def outcome_from_result(result: Any) -> HitlOutcome:
    """Map a Strands ``AgentResult`` onto a :class:`HitlOutcome`."""
    interrupts = getattr(result, "interrupts", None)
    if getattr(result, "stop_reason", None) == _STOP_REASON_INTERRUPT and interrupts:
        pending = interrupts[0]
        logger.info("HITL interrupt raised: name=%s id=%s", pending.name, pending.id)
        return HitlOutcome(
            status=STATUS_INTERRUPT,
            interrupt_id=pending.id,
            interrupt_name=pending.name,
            reason=pending.reason,
        )
    return HitlOutcome(status=STATUS_FINAL, text=extract_text(result))


def start(session_id: str, prompt: str, role: str = AGENT_ROLE_ORCHESTRATOR) -> HitlOutcome:
    """Run ``prompt`` on the session's agent and return final text or a pending interrupt.

    Returns a ``STATUS_BUSY`` outcome (no agent call) if the session is already processing a turn.
    """
    lock = _session_lock(session_id)
    if not lock.acquire(blocking=False):
        logger.info("Turn ignored; session busy: session=%s", session_id)
        return HitlOutcome(status=STATUS_BUSY)
    try:
        agent = _get_or_build_agent(session_id, role)
        result = agent(prompt)
        return outcome_from_result(result)
    finally:
        lock.release()


def resume(
    session_id: str,
    interrupt_id: str,
    response: Any,
    role: str = AGENT_ROLE_ORCHESTRATOR,
) -> HitlOutcome:
    """Resume a paused session by answering an interrupt with the human ``response``.

    Serializes per session and ignores a duplicate click on an already-answered interrupt,
    returning ``STATUS_BUSY`` instead of invoking the agent concurrently.
    """
    lock = _session_lock(session_id)
    if not lock.acquire(blocking=False):
        logger.info(
            "Resume ignored; session busy: session=%s interrupt=%s", session_id, interrupt_id
        )
        return HitlOutcome(status=STATUS_BUSY)
    try:
        if interrupt_id in _resolved_interrupts.get(session_id, set()):
            logger.info(
                "Resume ignored; interrupt already answered: session=%s interrupt=%s",
                session_id,
                interrupt_id,
            )
            return HitlOutcome(status=STATUS_BUSY)
        agent = _get_or_build_agent(session_id, role)
        result = agent([{"interruptResponse": {"interruptId": interrupt_id, "response": response}}])
        _resolved_interrupts.setdefault(session_id, set()).add(interrupt_id)
        return outcome_from_result(result)
    finally:
        lock.release()


def forget_session(session_id: str) -> None:
    """Drop the cached live agent for a session (state still persists via session manager)."""
    with _agents_lock:
        _agents.pop(session_id, None)
        _session_locks.pop(session_id, None)
        _resolved_interrupts.pop(session_id, None)
