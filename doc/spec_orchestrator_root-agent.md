## Spec: Orchestrator — Root Agent

**Hierarchy:** orchestrator (root)  
**Parent:** None (entry point)  
**Spec path:** `doc/spec_orchestrator_root-agent.md`  
**Implementation:** `apps/agents/orchestrator.py` → `build_orchestrator(model, session_manager) -> Agent`

---

## 📊 Request flow

```
┌─────────────────────────────────────────────────────────┐
│ Entry point (local `invoke` or deployed `/invocations`) │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│ apps/agent.py::run_prompt()                             │
│ ├─ Session mgr factory: File (offline) / AgentCore Mem  │
│ └─ build_agent(..., session_manager=mgr)               │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│ Orchestrator Agent                                       │
│                                                          │
│ tools=[                                                  │
│   hr_supervisor.as_tool(                                 │
│     name="human_resource_supervisor",                    │
│     preserve_context=True)                               │
│ ]                                                        │
│   → Strands runs the child and returns its text,         │
│     or surfaces its interrupt as this agent's            │
│     stop_reason == "interrupt"                            │
└──────────────────────┬─────────────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
         ▼ (no interrupt)            ▼ (child interrupt bubbles up)
    final text                  stop_reason == "interrupt"
    returned                     (orchestrator pauses)
         │                           │
         ▼                           ▼
    hitl.outcome_from_result()
    status=FINAL | status=INTERRUPT
         │
         ▼
    Slack posted (mention → message,
    or button/select → message update)
```

## 💡 Purpose

Routes incoming queries to the appropriate supervisor based on intent. Serves as the single
AgentCore Runtime entrypoint; all external `invoke_agent_runtime` calls land here and delegate
down the hierarchy via agents-as-tools + Strands interrupts.

- **Local run:** `make run` + prompt via `curl` or Slack mention
- **Deployed:** runtime ARN + payload `{"prompt": "..."}`
- **Session persistence:** durable state via session manager (FileSessionManager offline,
  AgentCoreMemorySessionManager online)

## 📥 Input contract

| Field | Type | Required | Example |
|-------|------|----------|---------|
| `prompt` | string | yes | `"Check certificate status for api.example.com"` |

### Prompt routing logic

| Intent keywords | Route to | Handler |
|-----------------|----------|---------|
| cert, certificate, renew, expir | HR supervisor | `human_resource_supervisor` |
| account, principal, user, onboard, offboard | HR supervisor | `human_resource_supervisor` |
| lifecycle, coverage, verify | HR supervisor | `human_resource_supervisor` |
| (anything else) | HR supervisor | orchestrator passes to model for intent detection |

## 📤 Output contract

**Final (no interrupt):** Plain string response (model output)

```
Certificate status for api.example.com:
- Type: AWS Certificate Manager (ACM)
- Expiration: 42 days
- Recommendation: Renewal within 7-14 days
```

**Interrupted (awaiting human):** Slack message with Block Kit

```
Certificate renewal approval — api.example.com

✅ Valid (42 days remaining)
🔄 Auto-renewal: eligible

[승인] [취소]
Sandbox: Approval recorded; no live mutation
```

## 🔧 Implementation

**File:** `apps/agents/orchestrator.py`  
**Model:** Claude Haiku 4.5 (configurable via `MODEL_ID`)  
**Pattern:** Strands agents-as-tools (in-process)

```python
def build_orchestrator(
    model: BedrockModel,
    supervisor_arn: str | None = None,
    session_manager: Any | None = None,
) -> Agent:
    """Root agent: routes to the HR supervisor (in-process) or a remote runtime."""
    return Agent(
        model=model,
        name="orchestrator",
        session_manager=session_manager,  # only the top-level agent is session-managed
        tools=[_supervisor_tool(model, supervisor_arn)],
        system_prompt=(
            "You are a root orchestrator. Route HR, identity, credential, certificate, and "
            "account create/update/delete tasks to human_resource_supervisor — even when the "
            "user did not name a specific target; the specialist collects the target and human "
            "approval. Summarize results clearly for the end user."
        ),
    )


def _supervisor_tool(model: BedrockModel, supervisor_arn: str | None) -> AgentTool:
    # Remote runtime (future multi-runtime) — a plain @tool over invoke_agent_runtime.
    if supervisor_arn:
        @tool(name="human_resource_supervisor")
        def human_resource_supervisor(query: str) -> str:
            return invoke_agent_runtime_text(supervisor_arn, query)
        return human_resource_supervisor

    # In-process default — native agents-as-tools with interrupt propagation.
    return build_hr_supervisor(model).as_tool(
        name="human_resource_supervisor",
        description="Delegate HR/identity/cert/account work to the HR supervisor.",
        preserve_context=True,
    )
```

## 🔄 Interrupt propagation

When a leaf write-tool raises an interrupt (e.g., `context.interrupt("cert_renewal_approval", ...)`):

1. **Leaf raises:** `request_certificate_renewal` → `context.interrupt(...)`
2. **Propagate (native):** each `Agent.as_tool` wrapper surfaces the child interrupt as its parent's `stop_reason == "interrupt"`, up cert leaf → supervisor → orchestrator
3. **Pause:** Orchestrator stops; HITL engine captures the interrupt + posts `reason["kind"]` to Slack
4. **Resume:** User approves/selects in Slack → `hitl.resume(session_id, interrupt_id, response)`
5. **Continue:** Strands forwards `response` back down to the paused leaf tool (same session, same live agents)

This ensures deep interrupts bubble to the top without any custom delegation code.

## 🌐 Deployment

### In-process (local/sandbox default)

- Single AgentCore runtime, orchestrator + hierarchy in-process
- Session manager: FileSessionManager (local logs dir) or AgentCore Memory (AWS-backed)
- No cross-runtime latency

### Multi-runtime (future, Phase 2)

Each tier becomes its own runtime. Orchestrator invokes supervisor via:

```python
# In terraform/variables.tf
variable "supervisor_arn" {
  type    = string
  default = "arn:aws:bedrock-agentcore:..."
}

# In orchestrator builder
supervisor_arn = var.supervisor_arn
# → invoke_agent_runtime_text(supervisor_arn, query) instead of in-process delegate
```

Requirements:
- Terraform: pass `supervisor_arn` to orchestrator env
- IAM: `bedrock-agentcore:InvokeAgentRuntime` on child runtime ARNs
- Payload format: `{"prompt": "..."}`

## 📚 References

- **Strands agents-as-tools pattern:**
  <https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/>
- **Strands interrupts (HITL):**
  <https://strandsagents.com/docs/user-guide/concepts/interrupts/>
- **Session management:**
  <https://strandsagents.com/docs/user-guide/concepts/agents/session-management/>
- **AWS multi-agent runtime reference:**
  `../amazon-bedrock-agentcore-samples/04-infrastructure-as-code/terraform/multi-agent-runtime/`
