# Evaluator Proposal Archive

This document archives the evaluator proposal content that was previously embedded in seminar.md.
It is kept for reference and future discussion, while the seminar flow remains focused on the
three stable demos.

## Background Incidents

1. Slack UI not shown: the HR supervisor did not call cert_specialist, so no interrupt was raised.
2. Double-click crash: rapid duplicate approval clicks caused concurrent resume and ConcurrencyException.

These issues motivated adding evaluator checks in CI.

## Design Principles

- Channel-agnostic evaluator design, matching the structured interrupt reason model.
- Deterministic routing gate with Equals evaluator (no judge model required).
- LLM-as-judge quality metrics as non-blocking signal.
- Keep evaluator runs separate from offline make check because Bedrock access is required.

## Components

- evals/__init__.py
- evals/routing_eval.py
- evals/quality_eval.py

## Example Routing Cases

- cert-renew-no-domain -> interrupt:cert_selection
- cert-renew-with-domain -> interrupt:cert_renewal_approval
- cert-status-read -> final
- account-offboard -> interrupt:account_delete_approval
- account-lookup-read -> final

## Commands

```sh
make eval
make eval-quality
```

## Team Proposal (Archived)

- Add routing eval cases whenever a new write tool is introduced.
- Define AI service quality SLAs and track them with evaluators.
- Promote make eval as a PR gate in CI when operationally ready.
