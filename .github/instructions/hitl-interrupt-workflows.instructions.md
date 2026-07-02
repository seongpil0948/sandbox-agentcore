---
description: "Use when implementing or modifying human-in-the-loop (HITL) approval flows, interrupt handling, or Slack interactive actions in sandbox-agentcore. Enforces Strands Interventions/Interrupts semantics and Slack ack-first interaction handling."
applyTo: "apps/agents/**/*.py,apps/slack/**/*.py,tests/**/*.py,doc/**/*.md,README.md,AGENTS.md"
---
# HITL Interrupt Workflow Rules

Apply these rules for any approval-gated workflow (certificate renewal, account changes, identity mutations).

## Approval model

- Treat all write-capable operations as HITL-gated by default.
- Split workflow into two phases:
  1. Read/assess phase: gather details and risk context only.
  2. Approved resume phase: execute or record the approved mutation path.
- Never execute mutations during detail/preview actions.
- If approval is denied or cancelled, return a clear "no change executed" status.

## Interrupt semantics (Strands-aligned)

- Use interrupt state to pause the workflow at the decision boundary.
- Interrupt output must include:
  - what is being changed,
  - target principal/resource,
  - risk-relevant details,
  - available actions: resume or cancel.
- Resume must continue only the approved action branch.
- Cancel must terminate the workflow branch without side effects.

## Slack interaction contract

- For interactive actions, acknowledge requests immediately (`ack()` first; within 3 seconds).
- After ack, perform slower detail lookup, status rendering, or orchestration logic.
- Use stable action IDs/constants for lifecycle transitions:
  - request/execute,
  - details,
  - resume,
  - cancel,
  - ignore.
- Keep button payload values minimal and non-secret.
- Always provide user-visible status updates for resumed/cancelled/ignored outcomes.

## Sandbox mutation policy

- In this repo, approved resume should record or simulate mutation intent unless a task explicitly requires real mutation wiring.
- Prefer declarative, reviewable mutation paths (for example, Terraform + PR) over direct ad-hoc runtime changes.
- CLI or operational commands should be read-only verification unless explicitly approved in task scope.

## Observability and auditability

- Log interrupt entry, approval decision, resume/cancel event, and final outcome.
- Keep logs free of secrets and token-like values.
- Preserve enough context to reconstruct who approved what and when.

## Testing expectations

- Add or update smoke tests for:
  - interrupt branch generation,
  - no-mutation behavior before approval,
  - resume path behavior,
  - cancel path behavior,
  - Slack action handling with ack-first behavior.
- Tests must be deterministic and avoid live external calls.

## References

- https://strandsagents.com/docs/user-guide/concepts/agents/interventions/human-in-the-loop/
- https://strandsagents.com/docs/user-guide/concepts/interrupts
- doc/slack-llms-full-python.txt