"""Deterministic routing/behaviour evaluation for the sandbox agent hierarchy.

Runs each prompt through the real orchestrator -> supervisor -> leaf hierarchy (via the HITL
engine) and asserts the *normalised outcome label*:

- ``interrupt:<name>`` when a leaf write-tool paused for human approval, or
- ``final`` when the turn completed without an interrupt (a read/answer), or
- ``busy`` when the session was already processing (should not happen here).

This catches the regression class where an intermediate tier answers in plain text instead of
calling the write tool: no interrupt is raised, so no Slack Block Kit renders. Scoring is
deterministic (``Equals`` — no judge model), but running the agents needs AWS Bedrock, so this is
an online, opt-in CI gate (``make eval``), not part of the offline ``make check``.
"""

from __future__ import annotations

import sys
import uuid

from strands_evals import Case, Experiment
from strands_evals.evaluators import Equals

from apps.runtime import hitl

FINAL = "final"


def _label(outcome: hitl.HitlOutcome) -> str:
    if outcome.status == hitl.STATUS_INTERRUPT:
        return f"interrupt:{outcome.interrupt_name}"
    if outcome.status == hitl.STATUS_BUSY:
        return "busy"
    return FINAL


def run_agent_turn(case: Case) -> str:
    """Eval task: run one prompt through the hierarchy and return its normalised outcome label."""
    session_id = f"eval-{uuid.uuid4().hex}"
    try:
        outcome = hitl.start(session_id, str(case.input))
        return _label(outcome)
    finally:
        hitl.forget_session(session_id)


CASES: list[Case] = [
    Case[str, str](
        name="cert-renew-no-domain",
        input="cert renew",
        expected_output="interrupt:credential_selection",
        metadata={"category": "cert", "intent": "renew"},
    ),
    Case[str, str](
        name="cert-renew-with-domain",
        input="renew the certificate for api.example.com",
        expected_output="interrupt:credential_renewal_approval",
        metadata={"category": "cert", "intent": "renew"},
    ),
    Case[str, str](
        name="cert-status-read",
        input="what is the certificate status for api.example.com",
        expected_output="final",
        metadata={"category": "cert", "intent": "read"},
    ),
    Case[str, str](
        name="secret-rotate-no-target",
        input="rotate the signing key secret",
        expected_output="interrupt:credential_selection",
        metadata={"category": "secret", "intent": "rotate"},
    ),
    Case[str, str](
        name="secret-rotate-with-target",
        input="rotate deploy-bot-signing-key secret",
        expected_output="interrupt:credential_renewal_approval",
        metadata={"category": "secret", "intent": "rotate"},
    ),
    Case[str, str](
        name="password-reset-no-target",
        input="reset the password",
        expected_output="interrupt:credential_selection",
        metadata={"category": "basic", "intent": "reset"},
    ),
    Case[str, str](
        name="account-offboard",
        input="offboard the deploy-bot service account",
        expected_output="interrupt:account_delete_approval",
        metadata={"category": "account", "intent": "delete"},
    ),
    Case[str, str](
        name="account-lookup-read",
        input="which accounts does deploy-bot have",
        expected_output="final",
        metadata={"category": "account", "intent": "read"},
    ),
]


def main() -> int:
    experiment = Experiment[str, str](cases=CASES, evaluators=[Equals()])
    report = experiment.run_evaluations(run_agent_turn)

    passes = list(report.test_passes)
    pass_rate = sum(passes) / len(passes) if passes else 0.0
    overall = getattr(report, "overall_score", pass_rate)
    print("\nRouting evaluation results:")
    for case, passed in zip(CASES, passes):
        mark = "✅" if passed else "❌"
        print(f"  {mark} {case.name}")
    print(
        f"\nOverall score: {overall:.2f}  Pass rate: {pass_rate:.0%} ({sum(passes)}/{len(passes)})"
    )
    experiment.to_file("logs/evals/routing")
    print("Saved: logs/evals/routing.json")
    return 0 if passes and all(passes) else 1


if __name__ == "__main__":
    sys.exit(main())
