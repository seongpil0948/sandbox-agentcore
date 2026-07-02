# AGENTS.md

Guide for coding assistants working on sandbox-agentcore. This repository implements Phase 1 of
a minimal Strands + Bedrock + AgentCore Runtime sandbox for HR/identity management.

**Slack APP Name:** `sandbox-ai-app`  
**Current Phase:** Phase 1 complete (HITL via native Strands interrupts, cert + account write tools)

---

## 🎯 Project intent

Minimal sandbox demonstrating:

1. **Strands + Bedrock + AgentCore Runtime** — multi-agent hierarchy (orchestrator → supervisor → leaves)
2. **Strands interrupts** — HITL (human-in-the-loop) approval flows for write operations
3. **Session durability** — state persists across interrupt/resume cycles (File or AWS AgentCore Memory)
4. **In-process Socket Mode** — Slack integration as a daemon thread within the runtime process
5. **Terraform scaffolding** — CodeBuild auto-build + cascade runtime deployment + IAM least-privilege

All running in a single AgentCore runtime (not cross-runtime A2A — that's Phase 2).

## 🔄 Phase 1 architecture (completed ✅)

```
Entry: /invocations (local) or Slack mention
  │
  ├─ Build session manager (File or AgentCore Memory) — orchestrator only
  │
  ├─ hitl.start(session_id, prompt)
  │  └─ orchestrator(prompt)
  │     └─ tool: human_resource_supervisor  (hr_supervisor.as_tool)
  │        └─ hr_supervisor(query)
  │           ├─ tool: cert_specialist  (cert_agent.as_tool)
  │           │  └─ cert_agent(query)
  │           │     ├─ check_cert_expiry() → text (no interrupt)
  │           │     └─ request_certificate_renewal(tool_context, domain="")
  │           │        ├─ context.interrupt("cert_selection", …)  ← if no/unknown domain
  │           │        └─ context.interrupt("cert_renewal_approval", …)
  │           │           ← PAUSES; Strands bubbles the interrupt up via as_tool
  │           │
  │           └─ tool: account_manager  (account_agent.as_tool)
  │              └─ account_agent(query)
  │                 ├─ lookup_principal() → text (read-only)
  │                 └─ request_account_create/update/delete(tool_context, …)
  │                    └─ context.interrupt("account_*_approval", …)  ← write, HITL-gated
  │
  ├─ result = AgentResult with stop_reason="interrupt"
  │
  ├─ outcome = hitl.outcome_from_result(result)
  │  └─ status=INTERRUPT, interrupt_id, interrupt_name, reason (structured dict)
  │
  └─ Slack renders reason["kind"] → Block Kit (external_select or [승인]/[취소])
     User selects/clicks → hitl.resume(session_id, interrupt_id, response)
     Strands forwards the response back down to the paused leaf tool → resumes
```

Interrupt propagation is **native**: each parent wraps its child with `Agent.as_tool(...)`, so
Strands surfaces a leaf interrupt as the parent's `stop_reason == "interrupt"` and, on resume,
forwards the human response back to the paused sub-agent. There is no custom delegation code.

## 🏗️ Core components

| Component | File | Purpose |
|-----------|------|---------|
| **Entry point** | `apps/agent.py` | AgentCore `@app.entrypoint invoke(payload)` + Socket Mode thread start |
| **HITL engine** | `apps/runtime/hitl.py` | `start()/resume()` + per-session live-agent cache + interrupt tracking |
| **Session factory** | `apps/runtime/session.py` | FileSessionManager (offline) or AgentCoreMemorySessionManager (online) |
| **Socket Mode** | `apps/slack/socket_mode.py` | In-process daemon thread; `@mention` → `hitl.start()`, button/select → `hitl.resume()`, `block_suggestion` → options |
| **Workflows** | `apps/slack/workflows.py` | Block Kit builders; `build_interrupt_blocks` dispatches on `reason["kind"]`; `build_hitl_options` |
| **Events** | `apps/slack/events.py` | Extract mention prompts, button/select actions, external_select options |
| **Orchestrator** | `apps/agents/orchestrator.py` | Root agent; wraps `human_resource_supervisor` via `Agent.as_tool` |
| **Supervisor** | `apps/agents/supervisor_hr.py` | HR agent; wraps `cert_specialist`, `account_manager` via `Agent.as_tool` |
| **Cert leaf** | `apps/agents/leaf_cert.py` | Cert agent; tools: `check_cert_expiry`, `list_cert_types`, `request_certificate_renewal` (selection + approval interrupts) |
| **Account leaf** | `apps/agents/leaf_account_manager.py` | Account agent; read tools + `request_account_create/update/delete` (approval interrupts) |

## 📚 Key patterns

### Agents-as-tools (native, in-process)

Each parent wraps a child `Agent` with `Agent.as_tool(...)`; Strands runs the child and returns
its text — and propagates any interrupt the child raised:

```python
return Agent(
    model=model,
    tools=[cert_agent.as_tool(name="cert_specialist", description=..., preserve_context=True)],
    ...,
)
```

`preserve_context=True` keeps the sub-agent's conversation/interrupt state alive across the
pause/resume (only the orchestrator carries a `session_manager`).

### Interrupt bubbling (native)

A leaf write-tool raises an interrupt with a **structured, channel-agnostic** reason:

```python
# In cert leaf tool
decision = tool_context.interrupt(
    name="cert_renewal_approval",
    reason={"kind": "cert_renewal", "record": {"domain": domain, "managed_via": "ssh", ...}},
)
```

Strands' `as_tool` wrapper surfaces this as the parent's `stop_reason == "interrupt"` up the whole
hierarchy. The HITL engine catches the top-level interrupt, the Slack layer renders `reason["kind"]`
to Block Kit, and `hitl.resume()` forwards the human response back to the paused leaf tool.

### Two-phase write tools

A single write tool can raise interrupts sequentially. `request_certificate_renewal` first raises
`cert_selection` (when no domain was given) so the human picks a certificate via an
`external_select`, then raises `cert_renewal_approval` for the final [승인]/[취소] decision.

### Session persistence

State persists across interrupt cycles via session manager:

- **Offline (local dev):** `FileSessionManager(session_id, "logs/sessions/")`
- **Online (deployed):** `AgentCoreMemorySessionManager(config, region_name)`

Both store Agent state, conversation history, and interrupt metadata.

### HITL workflow

1. Leaf calls `context.interrupt(name, reason)` → pauses agent loop (bubbles up via `as_tool`)
2. HITL engine extracts interrupt, Slack renders `reason["kind"]` as Block Kit
3. User clicks a button or picks an `external_select` option → Socket Mode calls `hitl.resume(session_id, interrupt_id, response)`
4. Strands forwards `response` to the paused sub-agent tool; `context.interrupt()` returns it
5. Agent continues; final result (or the next interrupt) propagates back up

## 🔌 Slack integration (in-process thread)

**Setup:** Set `SLACK_APP_SOCKET_TOKEN` + `SLACK_BOT_USER_OAUTH_TOKEN`

**Behavior:**
- `@app_mention` or DM → `_handle_agent_turn()` → `hitl.start()`
- Agent returns final text or raises interrupt
- If final: post response to thread
- If interrupt: render `reason["kind"]` as Block Kit (an `external_select` for `cert_selection`,
  otherwise [승인]/[취소] buttons)
- Button click or select → `_handle_hitl_action()` → `hitl.resume(session_id, interrupt_id, response)`
- `block_suggestion` (external_select typing) → ack with `build_hitl_options(...)`
- Message updates with the final result (or the next interrupt)

**Disable:** Set `SLACK_SOCKET_MODE_INPROCESS=0` → no thread started (test/CI mode)

> Slash commands (`/cert`, `/acc`) and the standalone `make run-slack` listener were removed. All
> interaction is agent-driven via mentions/DMs + Strands interrupts, running in-process only.

## 📋 Specs

Detailed agent specifications live in `doc/`:

- `spec_orchestrator_root-agent.md` — root agent, routing logic
- `spec_supervisor_human-resorce-agent.md` — HR supervisor, delegation rules, interrupt bubbling
- `spec_leaf_cert-agent.md` — cert agent, read/write tools, HITL flow in detail
- `spec_leaf_account-manager-agent.md` — account agent, read-only Phase 1, Phase 2 write design

## 📏 Rules

- **Single in-process runtime** (Phase 1 default) — no cross-runtime A2A until Phase 2
- **Locally runnable** — `uv run` + no AWS creds required for offline tests
- **Smoke tests only** — no strict coverage; validate core flows + HITL interrupt path
- **Validate at boundaries** — CLI args, Slack payloads, model inputs
- **No secrets in git** — use env vars or `.env` (git-ignored)
- **Refer to specs before coding** — agent behavior defined in `doc/spec_*.md`

## 🔧 Dev workflow

### Setup
```bash
make sync          # Install + setup .venv
make check         # ruff + format-check + pyright + pytest (92 tests pass)
```

### Local run
```bash
# Terminal 1: Runtime + Socket Mode thread
make run

# Terminal 2: Test direct invocation
curl -X POST http://127.0.0.1:8080/invocations \
  -H 'content-type: application/json' \
  -d '{"prompt":"cert status api.example.com"}'

# Terminal 3 (optional): With Slack tokens
make run  # (Socket Mode thread starts automatically)
# Then: @sandbox-ai-app cert status api.example.com
```

### Deploy
```bash
make tf-validate
terraform -chdir=terraform init
terraform -chdir=terraform apply
# (CodeBuild builds ARM64 image, pushes to ECR, deploys runtimes)
```

## 🧪 Testing

```bash
# All tests (111 pass; no AWS creds needed)
make test

# Specific test
pytest tests/test_runtime_hitl.py::test_execute_renewal_records_ssh_path -v

# With coverage
make test -c
```

## 📝 Code style

- Python 3.11+ with full type annotations (mypy strict)
- ruff format + lint (line length 120)
- pyright type checking
- Google-style docstrings
- Structured logging: `logger.info("key1=<%s>, key2=<%s> | message", val1, val2)`
- All public functions raise documented exceptions in their docstring `Raises:` section

## ✅ Phase 1 completion checklist

✅ Session factory (File + AgentCore Memory backends)  
✅ HITL engine (`start` / `resume` + agent instance cache)  
✅ Native interrupt propagation via `Agent.as_tool(preserve_context=True)` (no custom delegation)  
✅ In-process Socket Mode thread (token-gated)  
✅ Cert renewal: `cert_selection` (external_select) → `cert_renewal_approval` interrupts + Block Kit UI  
✅ Account read tools + `request_account_create/update/delete` approval interrupts  
✅ Management methods on records (`managed_via` SSH/HTTP + `management_endpoint`)  
✅ Full test coverage (92 tests pass) + end-to-end HITL smoke  
✅ Documentation (README + specs)  

## 🔮 Phase 2 (future)

🔲 Per-tier session managers (cross-restart deep resumption of nested interrupts)  
🔲 Terraform AgentCore Memory wiring  
🔲 Advanced observability (metrics, traces)  
🔲 Real read-only integrations (IAM Identity Center, Organizations, ACM, Secrets Manager)  
🔲 Cross-runtime A2A promotion (separate runtimes for each tier)

## 📚 References

- **Strands Python SDK:** <https://strandsagents.com/>
- **Strands interrupts:** <https://strandsagents.com/docs/user-guide/concepts/interrupts/>
- **AWS AgentCore:** <https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html>
- **Slack Socket Mode:** <https://api.slack.com/socket-mode>
- **Sandbox samples:** `../amazon-bedrock-agentcore-samples/`
