# sandbox-agentcore

Minimal sandbox for **Strands agents** + **Bedrock** + **AgentCore Runtime** + **Terraform**.

Phase 1 architecture: in-process multi-agent hierarchy with **Strands interrupts** for human-in-the-loop (HITL) workflows.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  @sandbox-ai-app cert renew   ◄─────────────────────────┐      │
│  (mention/DM)                                            │      │
│         │                                                │      │
│         ▼                                                │      │
│  ┌─────────────────────────────────────────────────┐    │      │
│  │  AgentCore Runtime (long-lived)                 │    │      │
│  │  - Slack Socket Mode thread (in-process)       │    │      │
│  │  - agents-as-tools hierarchy                   │    │      │
│  │  - durable session + interrupt state           │    │      │
│  │                                                  │    │      │
│  │  orchestrator (root)                            │    │      │
│  │  └── supervisor: human-resource                │    │      │
│  │      ├── leaf: cert                            │    │      │
│  │      │   └── request_certificate_renewal       │    │      │
│  │      │       raises interrupt                  │    │      │
│  │      └── leaf: account-manager                │    │      │
│  └─────────────────────────────────────────────────┘    │      │
│         │                                                │      │
│         │ outcome: final_text | interrupt               │      │
│         ▼                                                │      │
│  chat_postMessage (Block Kit)                          │      │
│         │                                                │      │
│         │ [승인] [취소] buttons                        │      │
│         └────────────────────────────────────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Core components

| Component | Purpose | Status |
|-----------|---------|--------|
| `apps/runtime/session.py` | Session-manager factory (FileSessionManager offline / AgentCore Memory online) | ✅ Phase 1 |
| `apps/runtime/hitl.py` | Interrupt-based HITL engine (`start`/`resume`); in-process agent registry | ✅ Phase 1 |
| `apps/agents/orchestrator.py` + `supervisor_hr.py` | Wrap children with `Agent.as_tool(preserve_context=True)` — native interrupt propagation | ✅ Phase 1 |
| `apps/agents/leaf_cert.py` | `request_certificate_renewal` → `cert_selection` then `cert_renewal_approval` interrupts | ✅ Phase 1 |
| `apps/agents/leaf_account_manager.py` | `request_account_create/update/delete` approval interrupts | ✅ Phase 1 |
| `apps/slack/workflows.py` | `build_interrupt_blocks` renders per `reason["kind"]`; `build_hitl_options` for external_select | ✅ Phase 1 |
| `apps/slack/socket_mode.py` | Socket Mode daemon thread; @mention/DM → `hitl.start`, button/select → `hitl.resume` | ✅ Phase 1 |

### Mock data & resources

All agent registries centralized in `apps/mock_data.py`:

- **User principals:** deployer-alice, platform-admin, contractor-bob
- **Service accounts:** deploy-bot, github-service
- **Certificates:** api.example.com (42d), nginx.internal (7d), old.example.com (expired)
- **AWS accounts:** 111122223333 (prod), 222233334444 (staging)

The same ARM64 container can be promoted to multi-runtime in the future (keep `terraform apply` functional); the sandbox default keeps the hierarchy in-process for local dev.

`terraform apply` is self-contained: packages `apps/` + `Dockerfile`, builds ARM64 image with CodeBuild, pushes to ECR, provisions runtimes — no manual Docker steps.

## References used for Terraform shape

The Terraform flow was aligned with patterns from:

- `../amazon-bedrock-agentcore-samples/04-infrastructure-as-code/terraform/end-to-end-weather-agent` (CodeBuild + S3 + ECR auto-build)
- `../amazon-bedrock-agentcore-samples/04-infrastructure-as-code/terraform/multi-agent-runtime` (build trigger + IAM-propagation wait)
- `../amazon-bedrock-agentcore-samples/04-infrastructure-as-code/terraform/mcp-server-agentcore-runtime`


## Types of agents

#### Supervisor
- HR resource manager

#### Leaf
- Cert Operator
- Account manager



## Project structure

- `apps/agent.py`: AgentCore Runtime entrypoint (`BedrockAgentCoreApp`, `@app.entrypoint`)
- `apps/agents/orchestrator.py`: root orchestrator builder
- `apps/agents/supervisor_hr.py`: HR/identity supervisor builder
- `apps/agents/leaf_cert.py`: cert specialist builder + offline stub tools
- `apps/agents/leaf_account_manager.py`: account-manager builder + offline stub tools
- `apps/utils/runtime_invocation.py`: helper for runtime-to-runtime calls
- `apps/client.py`: boto3 invoke client for deployed runtime
- `apps/slack/socket_mode.py`: Slack Socket Mode listener (in-process daemon thread) that routes
  mentions/DMs through the HITL interrupt engine; `apps/agent.py` starts it (token-gated)
- `apps/runtime/hitl.py`: interrupt-based HITL engine; `apps/runtime/session.py`: session-manager
  factory (FileSessionManager offline / AgentCore Memory online)
- `tests/test_agent.py`: smoke tests
- `tests/test_slack_socket_mode.py`: Slack bridge smoke tests (env aliasing + message filtering)
- `terraform/`: orchestrator, supervisor, leaf runtimes + memory + execution roles + shared ECR repo
- `terraform/s3.tf` + `codebuild.tf` + `build.tf` + `buildspec.yml` + `scripts/build-image.sh`: automated image build pipeline
- `doc/`: agent spec docs

Spec files:

- `doc/spec_orchestrator_root-agent.md`
- `doc/spec_supervisor_human-resorce-agent.md`
- `doc/spec_leaf_cert-agent.md`
- `doc/spec_leaf_account-manager-agent.md`

## Prerequisites

- Python 3.11+
- `uv`
- AWS CLI v2 + credentials (`AWS_PROFILE` or env vars)
- Bedrock model access for `global.anthropic.claude-haiku-4-5-20251001-v1:0`
- Docker is only needed for the optional local run; the cloud deploy builds the ARM64 image with CodeBuild

## Local run

```sh
make sync
make check
make run
```

## 🚀 Quick start: Local development

```sh
# Setup
make sync
make check

# Terminal 1: AgentCore runtime (includes in-process Slack Socket Mode thread)
make run

# Terminal 2 (optional): test direct invocation
curl -X POST http://127.0.0.1:8080/invocations \
  -H 'content-type: application/json' \
  -d '{"prompt":"Check the certificate status for api.example.com"}'
```

**Local demo without Slack:** runs the full agent hierarchy offline (mock data, no AWS creds needed).

**With Slack:** set tokens (see below), then mention the app in Slack:
```
@sandbox-ai-app cert renew api.example.com
```

## 🔌 Slack Socket Mode integration (Phase 1)

### Workflow

1. **Mention/DM the app** in Slack (e.g., `@sandbox-ai-app cert renew`)
2. **Socket Mode thread** (running in-process) → `hitl.start(session_id, prompt)`
3. **Leaf write-tool** (e.g., `request_certificate_renewal`) → `context.interrupt(name, reason={Block Kit data})`
4. **HITL engine** pauses and posts Block Kit to Slack with **[승인] [취소]** buttons
5. **User clicks button** → Socket Mode → `hitl.resume(session_id, interrupt_id, decision)`
6. **Agent resumes** in the same session (durable state via session manager)
7. **Final result** posted to thread

### Setup

#### 1) Create Slack app (api.slack.com/apps)

Minimum configuration:

- **Socket Mode**: Enable
- **App-level token**: Create with `connections:write` scope (copy the `xapp-...` token)
- **Install app** to workspace (get bot token `xoxb-...`)
- **Event Subscriptions**: Subscribe to `app_mention` and `message.im`
- **Interactivity**: Enable (for button actions)
- **Bot token scopes**: `chat:write`, `app_mentions:read`, `im:history`
- **Reinstall** after changes to scopes/events

#### 2) Environment variables

**Required:**

```bash
export SLACK_APP_SOCKET_TOKEN="xapp-..."
export SLACK_BOT_USER_OAUTH_TOKEN="xoxb-..."
```

**Optional aliases:**

```bash
export SLACK_APP_TOKEN="xapp-..."                    # alias for SLACK_APP_SOCKET_TOKEN
export SLACK_BOT_TOKEN="xoxb-..."                    # alias for SLACK_BOT_USER_OAUTH_TOKEN
export SLACK_NOTIFICATION_CHANNEL_ID="C..."           # for runtime workflow notices
```

#### 3) Run

```bash
# In-process Socket Mode starts automatically when tokens present
make run

# Mention the app in Slack
@sandbox-ai-app cert renew nginx.internal
```

**To disable in-process Socket Mode** (e.g., for CI/unit tests):
```bash
export SLACK_SOCKET_MODE_INPROCESS=0
make run  # no Socket Mode thread started
```

### Behavior

| Event | Handler | Output |
|-------|---------|--------|
| `@app_mention` / DM | `_handle_agent_turn` | Posts agent response + [승인/취소] if interrupted |
| Button click (approve/cancel) | `_handle_hitl_action` | Resumes session, updates message |
| AWS creds missing | Offline fallback | Posts fallback response (no model call) |

**Important:** Slash commands (`/cert`, `/acc`) are **removed** as of Phase 1. All workflows now drive through agent mentions + interrupts.

### Example workflows

#### Workflow 1: Check cert (no interruption)

```bash
# In Slack
@sandbox-ai-app cert status api.example.com

# Output (posted in thread)
✅ Status: VALID
42 days remaining
Recommendation: Renewal within 7-14 days
```

#### Workflow 2: Renew cert (with interruption)

```bash
# In Slack — a domain is optional
@sandbox-ai-app cert renew

# 1) Bot pauses at cert_selection (no domain given):
#    an external_select "갱신할 인증서를 선택하세요" lists api.example.com / nginx.internal / ...
#    User picks nginx.internal

# 2) Bot pauses at cert_renewal_approval with the record detail:
#    - Title: "인증서 갱신 승인 — nginx.internal"
#    - status / expiry / cert type / ARN / account·region / renewal eligibility
#    - 관리 방식: ssh (ssh://deploy@nginx.internal)
#    - Buttons: [승인] [취소]

# 3) User clicks [승인]
#    Agent resumes and records the SSH path:
#    "certbot renew + nginx -s reload recorded via ssh://deploy@nginx.internal. Sandbox: no live change."
```

Certificates managed over ACM instead record `ACM renewal/re-import request via https://acm.<region>.amazonaws.com`.
Passing the domain up front (`cert renew api.example.com`) skips the selection step.

#### Workflow 3: Account offboarding (any principal type)

```bash
# In Slack
@sandbox-ai-app offboard deploy-bot

# Bot pauses at account_delete with an offboarding review:
# - Principal: deploy-bot (service_account, owner platform-team)
# - 오프보딩 체크리스트 — 회수 대상 리소스:
#     • 인증서 nginx.internal
#     • 시크릿 deploy-bot-signing-key
# - Buttons: [승인] [취소]

# [승인] records the approved offboarding (no live deletion).
```

`request_account_create` / `request_account_update` follow the same approve/cancel pattern. The
account manager parses the principal (and type/owner/change when present) from the prompt.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Tokens not loaded | Set `SLACK_APP_SOCKET_TOKEN` + `SLACK_BOT_USER_OAUTH_TOKEN` |
| No Socket Mode logs | Check `SLACK_SOCKET_MODE_INPROCESS` is not `0` |
| Button clicks not working | Confirm Interactivity is enabled in app config |
| Repeated events | Socket Mode ack is automatic; check runtime logs for exceptions |
| No Slack message | Verify bot is installed + `app_mention` subscription active |

### Security

- Never commit real Slack secrets to git.
- Use `.env` or CI secrets manager for token rotation.
- Sandbox records HITL approvals but does **not** execute mutations (certificates/accounts are mocked).

## 📁 Project structure

```
apps/
├── agent.py                    # AgentCore Runtime entrypoint (@app.entrypoint invoke)
├── runtime/
│   ├── hitl.py                 # Strands interrupt HITL engine (start/resume)
│   ├── session.py              # Session-manager factory (File/AgentCore Memory)
│   ├── roles.py                # Agent builder dispatch (orchestrator/supervisor/leaf)
│   └── local_fallback.py       # Offline fallback when no AWS creds
├── agents/
│   ├── orchestrator.py         # Root agent (wraps human_resource_supervisor via Agent.as_tool)
│   ├── supervisor_hr.py        # HR agent (wraps cert_specialist, account_manager via Agent.as_tool)
│   ├── leaf_cert.py            # Cert agent (check_cert_expiry, request_certificate_renewal)
│   └── leaf_account_manager.py # Account agent (lookup_principal, request_account_create/update/delete)
├── slack/
│   ├── socket_mode.py          # Socket Mode listener (in-process thread); HITL handlers
│   ├── workflows.py            # Block Kit builders (interrupt_blocks, agent_response_blocks)
│   ├── events.py               # Event/action extraction
│   └── commands.py             # Command builders (kept for reference; dispatch removed)
├── utils/
│   ├── env.py                  # Environment variable resolution
│   ├── logging_config.py       # Structured logging setup
│   ├── response.py             # Text extraction from AgentResult
│   └── ...
├── client.py                   # boto3 client for deployed runtime testing
└── mock_data.py                # Offline registries (principals, certs, accounts)

tests/
├── test_agent.py               # Smoke tests (invoke contract, offline fallback)
├── test_slack_socket_mode.py   # Socket Mode + HITL handler tests
├── test_slack_commands.py      # Block Kit builder tests (modals/buttons)
├── test_runtime_hitl.py        # Session factory + HITL engine + leaf write-tool payload tests
└── test_slack_events.py        # Event extraction tests

terraform/
├── main.tf                     # Orchestrator/supervisor/leaf runtime definitions
├── iam.tf                      # Execution role + inline policies
├── memory.tf                   # AgentCore Memory resource (optional)
├── ecr.tf                      # ECR repo for built image
├── codebuild.tf                # CodeBuild project (S3 → build → ECR)
├── s3.tf                       # Source bucket for build context
├── outputs.tf                  # ARNs + invoke command
└── scripts/build-image.sh      # Docker build helper

doc/
├── spec_orchestrator_root-agent.md         # Root agent behavior
├── spec_supervisor_human-resorce-agent.md  # HR supervisor + as_tool interrupt bubbling
├── spec_leaf_cert-agent.md                 # Cert agent + interrupt tool
├── spec_leaf_account-manager-agent.md      # Account agent + tools
├── bedrock-agentcore-dg.txt                # AWS reference (cached)
├── slack-llms-full-python.txt              # Slack SDK reference (cached)
└── seminar.md                              # Architecture seminar notes

.github/instructions/
├── minimal-agentcore-sandbox.instructions.md    # Scope + quality bar
├── reference-first-agentcore.instructions.md    # Consult docs before coding
├── hitl-interrupt-workflows.instructions.md     # HITL semantics
├── slack-python-sdk.instructions.md             # Slack SDK patterns
└── terraform-sandbox.instructions.md            # Terraform rules
```

## 🧪 Testing

```bash
# Unit + smoke tests (128 tests, no AWS creds needed)
make check          # ruff + format-check + pyright + pytest

# Individual test types
make test           # pytest only
uv run ruff check . # lint
uv run ruff format .  # format
```

Example offline test (cert status check):
```bash
pytest tests/test_agent.py::test_run_prompt_falls_back_to_local_cert_stub_without_credentials -v
```

## 🚀 Deploy to AWS (Terraform)

### Prerequisites

- Terraform >= 1.0
- AWS CLI v2 + credentials configured
- Docker (local build only; cloud build uses CodeBuild)
- Bedrock model access: `global.anthropic.claude-haiku-4-5-20251001-v1:0`

### One-command deploy

```bash
# Validate
make tf-validate

# Apply (builds image, provisions runtimes, creates memory)
terraform -chdir=terraform init
terraform -chdir=terraform apply
```

**What apply does:**

1. Creates ECR repo, S3 build bucket, CodeBuild project
2. Uploads `apps/` + `Dockerfile` + `pyproject.toml` to S3
3. Waits ~30s for IAM propagation, triggers CodeBuild
4. CodeBuild builds ARM64 image, pushes to ECR
5. Creates `leaf` → `supervisor` → `orchestrator` runtimes (cascade: each waits for previous)
6. Creates AgentCore Memory (optional, if `AGENTCORE_MEMORY_ID` env var set later)
7. Outputs runtime ARNs + invoke command

### Outputs

```bash
terraform -chdir=terraform output

# Key outputs:
agent_runtime_arn                      # orchestrator ARN (use this)
supervisor_runtime_arn                 # supervisor ARN
leaf_runtime_arn                       # leaf ARN
effective_runtime_image_uri            # ECR image pushed
codebuild_project                      # CodeBuild project name
invoke_command                         # copy-paste test command
```

### Test deployed runtime

```bash
# Use generated command
eval "$(terraform -chdir=terraform output -raw invoke_command)"

# Or manually
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$(terraform -chdir=terraform output -raw agent_runtime_arn)" \
  --runtime-session-id "test-session-$(date +%s)-$(openssl rand -hex 12)" \
  --payload '{"prompt":"cert status api.example.com"}'
```

Session ID must be ≥33 characters (generated command handles this).

### Clean up

```bash
terraform -chdir=terraform destroy
```

## 📚 References

### AWS Samples

- [amazon-bedrock-agentcore-samples/terraform/end-to-end-weather-agent](../amazon-bedrock-agentcore-samples) — CodeBuild + ECR auto-build pattern
- [amazon-bedrock-agentcore-samples/terraform/multi-agent-runtime](../amazon-bedrock-agentcore-samples) — Multi-tier runtime cascade

### Strands SDK

- [Strands Agents Python SDK docs](https://strandsagents.com/)
- Interrupts: [https://strandsagents.com/docs/user-guide/concepts/interrupts/](https://strandsagents.com/)
- Session managers: [https://strandsagents.com/docs/user-guide/concepts/agents/session-management/](https://strandsagents.com/)

### Slack SDK

- [slack-sdk Python documentation](https://slack.dev/python-slack-sdk/)
- Socket Mode: [https://api.slack.com/socket-mode](https://api.slack.com/)

## 📝 Development notes

### Code style

- Python 3.11+ with full type annotations (mypy strict)
- ruff format + lint (line length 120)
- pyright type checking
- Google-style docstrings
- Logging: structured format `key1=<val1>, key2=<val2> | message`
- Agents: use Strands SDK patterns (hooks, tools, agents-as-tools)

### Phase 1 scope (completed ✅)

✅ In-process Socket Mode thread (token-gated)  
✅ Strands interrupts for HITL workflows  
✅ Session durability (FileSessionManager offline / AgentCore Memory online)  
✅ Interrupt bubbling across agents-as-tools hierarchy  
✅ Cert renewal tool + Block Kit approval UI  

### Phase 2 (future)

🔲 Account create/delete interrupt tools  
🔲 Per-tier session managers (cross-restart deep interrupt resume)  
🔲 Terraform AgentCore Memory wiring + outputs  
🔲 Advanced metrics + observability

Or invoke the orchestrator directly:

```sh
uv run python apps/client.py \
  --agent-runtime-arn "$(terraform -chdir=terraform output -raw agent_runtime_arn)" \
  --region us-east-1 \
  --session-id demo-session-00000000000000000000000000000000 \
  --prompt "List the certificate types we support"
```

## Notes

- `AGENT_ROLE=orchestrator` uses `SUPERVISOR_ARN`
- `AGENT_ROLE=supervisor` uses `LEAF_ARN`
- `AGENT_ROLE=leaf` runs the certificate specialist directly
- Slack bridge follows `.envrc` variable names first (`SLACK_APP_SOCKET_TOKEN`, `SLACK_BOT_USER_OAUTH_TOKEN`) with alias fallback
