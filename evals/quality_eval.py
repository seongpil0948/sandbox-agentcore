"""LLM-as-judge helpfulness evaluation for read responses.

Demonstrates a custom :class:`~strands_evals.evaluators.Evaluator` that judges response quality
with the sandbox's *own* Haiku model (instead of the SDK's default Claude-4 judge), so it runs
with the same Bedrock access as the agents. This is informational (not a hard CI gate): read-only
prompts produce final text that a judge can score; write prompts pause for approval and are covered
by the deterministic ``routing_eval`` instead.
"""

from __future__ import annotations

import sys
import uuid

from strands import Agent
from strands.models import BedrockModel
from strands_evals import Case, Experiment
from strands_evals.evaluators import Evaluator
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

from apps.runtime import hitl
from apps.runtime.roles import MODEL_ID

_JUDGE_PROMPT = (
    "You are a strict evaluator for an internal HR/identity ops assistant. "
    "Given a USER request and the ASSISTANT answer, reply with exactly one word: "
    "PASS if the answer is on-topic, accurate to the request, and useful to an ops engineer; "
    "otherwise FAIL."
)


class HaikuHelpfulnessJudge(Evaluator[str, str]):
    """Helpfulness judge backed by the sandbox's Haiku model."""

    def __init__(self, model_id: str = MODEL_ID) -> None:
        super().__init__()
        self._model = BedrockModel(model_id=model_id)

    def evaluate(self, evaluation_case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        judge = Agent(model=self._model, callback_handler=None, system_prompt=_JUDGE_PROMPT)
        verdict = str(
            judge(f"USER: {evaluation_case.input}\nASSISTANT: {evaluation_case.actual_output}")
        ).strip()
        passed = "PASS" in verdict.upper()
        return [
            EvaluationOutput(
                score=1.0 if passed else 0.0,
                test_pass=passed,
                reason=verdict[:300] or "no verdict",
            )
        ]

    async def evaluate_async(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return self.evaluate(evaluation_case)


def run_read_query(case: Case) -> str:
    """Eval task: run a read-only prompt and return the assistant's final text."""
    session_id = f"evalq-{uuid.uuid4().hex}"
    try:
        outcome = hitl.start(session_id, str(case.input))
        return outcome.text or f"[{outcome.status}]"
    finally:
        hitl.forget_session(session_id)


CASES: list[Case] = [
    Case[str, str](
        name="cert-status",
        input="what is the certificate status for api.example.com",
        metadata={"category": "cert"},
    ),
    Case[str, str](
        name="cert-types",
        input="which certificate types do we support",
        metadata={"category": "cert"},
    ),
    Case[str, str](
        name="account-lookup",
        input="who owns the deploy-bot service account and what does it access",
        metadata={"category": "account"},
    ),
    Case[str, str](
        name="stale-accounts",
        input="list stale or risky accounts",
        metadata={"category": "account"},
    ),
]


def main() -> int:
    experiment = Experiment[str, str](cases=CASES, evaluators=[HaikuHelpfulnessJudge()])
    report = experiment.run_evaluations(run_read_query)

    passes = list(report.test_passes)
    pass_rate = sum(passes) / len(passes) if passes else 0.0
    overall = getattr(report, "overall_score", pass_rate)
    print("\nQuality evaluation results (Haiku judge):")
    for case, passed in zip(CASES, passes):
        mark = "✅" if passed else "❌"
        print(f"  {mark} {case.name}")
    print(
        f"\nOverall score: {overall:.2f}  Pass rate: {pass_rate:.0%} ({sum(passes)}/{len(passes)})"
    )
    experiment.to_file("logs/evals/quality")
    print("Saved: logs/evals/quality.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
