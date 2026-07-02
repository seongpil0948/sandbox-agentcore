---
description: "Use when implementing or modifying AI behavior in sandbox-agentcore (Strands tools/agents, Bedrock model invocation, AgentCore runtime payload handling, or Terraform runtime setup). Encourages consulting local sandbox docs and amazon-bedrock-agentcore-samples before coding."
applyTo: "apps/**/*.py,tests/**/*.py,terraform/**/*.tf,README.md,AGENTS.md"
---
# Reference-First AgentCore Workflow

Scope, runtime contract, IAM baseline, and testing rules live in `minimal-agentcore-sandbox.instructions.md`; this file governs how to use references before coding.

- Before writing code, consult local references relevant to the change, in this order:
  1. sandbox guide: `doc/bedrock-agentcore-dg.txt`
  2. sample repo: `../amazon-bedrock-agentcore-samples/README.md`, then `00-getting-started/README.md`
  3. the topic-specific sample subfolder:
     - Terraform: `04-infrastructure-as-code/terraform/basic-runtime/` (minimal runtime + least-privilege IAM template)
     - Multi-agent Terraform: `04-infrastructure-as-code/terraform/multi-agent-runtime/` (A2A pattern)
     - Strands: `03-integrations/agentic-frameworks/strands-agents/` (entrypoint and streaming examples)
     - Runtime hosting/contract: `01-features/02-host-your-agent/01-runtime/`
  4. Strands multi-agent patterns: <https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/>
- Copy patterns, not architectures: take the smallest idiom that solves the task; do not pull in broader sample features.
- When proposing or implementing a change, state which reference source informed it.
- If a reference cannot be read in the environment, say so explicitly and proceed with the closest in-repo source of truth.
