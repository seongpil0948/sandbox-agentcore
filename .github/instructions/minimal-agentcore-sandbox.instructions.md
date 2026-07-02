---
description: "Use when working on sandbox-agentcore files. Enforces a minimal Bedrock AgentCore sandbox scope (Strands + Bedrock + AgentCore Runtime + Terraform), smoke-test-only quality bar, and AgentCore Runtime service contract requirements from the developer guide."
applyTo: "apps/**/*.py,tests/**/*.py,terraform/**/*.tf,pyproject.toml,README.md,AGENTS.md,Makefile"
---
# Minimal AgentCore Sandbox Rules

This is the baseline for the repo. The reference-first and Terraform instructions build on it and do not repeat its scope, contract, or IAM rules.

## Scope guardrails

- Keep this repo a minimal sandbox: Strands, Bedrock model invocation, AgentCore Runtime,
  in-process multi-agent hierarchy (orchestrator → supervisor → leaf), and Terraform scaffold.
- **Allowed**: minimal in-process agent hierarchy using agents-as-tools (parent's `@tool` wraps
  child `Agent.__call__`).
- **Not allowed**: multi-runtime A2A build pipeline (separate ECR/S3/CodeBuild per tier) unless
  explicitly requested; channels, governance, memory wrappers, web frontend.
- Spec convention for agents: `doc/spec_{hierarchy}_{name}-agent.md`
- Prefer direct, simple code over reusable architecture.

## AgentCore Runtime contract (from Bedrock AgentCore guide)

- Runtime code must expose either:
  - `@app.entrypoint` using AgentCore Python SDK, or
  - HTTP endpoints `/invocations` (POST, JSON in/out) and `/ping` (GET) on host `0.0.0.0:8080` (ARM64 container).
- Validate boundary input (`payload` shape) and return clear error strings for invalid requests.
- Keep runtime/invoke payloads JSON-object based, with a `prompt` field unless explicitly changing the contract.
- `runtimeSessionId` must be at least 33 characters when invoking via boto3.

## Security and IAM baseline

- Preserve least-privilege execution-role intent.
- Runtime execution permissions should include model invocation plus observability basics when Terraform is touched:
  - execution-role trust limited to `bedrock-agentcore.amazonaws.com` with `aws:SourceAccount`/`aws:SourceArn` conditions
  - `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`, scoped to `foundation-model/*` ARNs (not `*`)
  - CloudWatch Logs writes scoped to `/aws/bedrock-agentcore/runtimes/*`
  - X-Ray write permissions
- Avoid embedding credentials in code, docs, tests, or examples.

## Testing and quality bar

- Tests are smoke tests only; focus on boundary behavior and local deterministic logic.
- Do not mock model internals to fabricate deep integration behavior.
- Keep checks lightweight and local-first (`ruff`, `pyright`, `pytest -q`, `terraform validate`).

## File conventions

- `apps/agent.py`: AgentCore Runtime entrypoint (`BedrockAgentCoreApp`, `@app.entrypoint`).
- `apps/agents/orchestrator.py`: `build_orchestrator(model)` — root tier.
- `apps/agents/supervisor_hr.py`: `build_hr_supervisor(model)` — HR supervisor tier.
- `apps/agents/leaf_cert.py`: `build_cert_agent(model)` — cert leaf tier + stub tools.
- `apps/client.py`: simple boto3 invoke example with explicit CLI args.
- `terraform/`: scaffold-level resources and variables; avoid production-only complexity.
- `doc/spec_{hierarchy}_{name}-agent.md`: per-agent spec files.
- Docs (`README.md`, `AGENTS.md`) should reflect current minimal scope and runnable commands.

## Change discipline

- Prefer minimal diffs and avoid introducing abstractions unless repeated pain is clear.
- If a requested feature expands beyond sandbox scope, call it out and propose it as a separate repo or optional module.
