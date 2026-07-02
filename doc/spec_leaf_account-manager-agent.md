## Spec: Leaf Agent - Account Manager

**Hierarchy:** leaf  
**Parent:** Human Resource supervisor (`spec_supervisor_human-resorce-agent.md`)  
**Spec path:** `doc/spec_leaf_account-manager-agent.md`  
**Implementation:** `apps/agents/leaf_account_manager.py` → `build_account_manager_agent(model, session_manager) -> Agent`

---

## 📊 Request flow

The account agent is exposed to the supervisor via `account_agent.as_tool(name="account_manager",
preserve_context=True)`, so any interrupt it raises surfaces natively as the parent's
`stop_reason == "interrupt"`.

```
Supervisor: tool account_manager  (account_agent.as_tool(preserve_context=True))
└─ account_agent(query)
   │
   ├─ If read: lookup_principal, list_accounts, list_access, list_credentials,
   │  list_principals, list_linked_resources, validate_onboarding,
   │  validate_offboarding, find_stale_accounts
   │  └─ returns text directly (no interrupt)
   │
   └─ If write: request_account_create / request_account_update / request_account_delete
      └─ tool_context.interrupt(name="account_*_approval", reason={"kind": "account_*", ...})
         [Slack: detail card + [승인]/[취소]; delete shows a linked cert/secret checklist]
         [Socket Mode: hitl.resume(session_id, interrupt_id, response)]
         → approved → records the change only; cancelled → "No change executed."
         → returns text; stop_reason bubbles up via as_tool
```

## 💡 Purpose

Manages principal (user / contractor / service_account / application / workload / agent_identity)
lifecycle. Every principal can own certificates and secrets, each with a management method
(`managed_via` SSH/HTTP/api + a `management_endpoint`):

- **Read-only tools** (Phase 1, implemented):
  - `lookup_principal(principal)` → metadata, owner, status, accounts, access, credentials, risks
  - `list_accounts` / `list_access` / `list_credentials` / `list_principals` / `list_linked_resources`
  - `validate_onboarding` / `validate_offboarding` → readiness / offboarding risk
  - `find_stale_accounts()` → idle/ownerless/risky principals

- **Write tools** (Phase 1, implemented — interrupt-based, record-only):
  - `request_account_create(tool_context, principal, principal_type="user", owner="")`
  - `request_account_update(tool_context, principal, change="")`
  - `request_account_delete(tool_context, principal)` → interrupt carries a linked cert/secret checklist

## 📥 Input contract

From supervisor via `Agent.as_tool` (the wrapper tool takes a single string). The model parses the
principal name (and type/owner/change when present) from the natural-language prompt — there is no
modal/form:

| Field | Type | Example |
|-------|------|---------|
| `query` | string | `"What accounts does deploy-bot have?"` or `"Offboard deploy-bot"` |

## 📤 Output contract

**Read-only (Phase 1):**
```
Principal: deploy-bot
Type: service_account
Owner: platform-team
Status: active
Accounts:
  - AWS IAM (role: deploy-bot in 123456789012)
  - GitHub (token: ghp_***** last-rotation: 2025-01-10)
Credentials:
  - nginx.internal certificate (days_remaining=7, expiring_soon)
  - aws_secret: deploy-bot-key (last-rotated: 90d ago)
```

**Write (Phase 1, interrupted):** Interrupt propagates up natively via `as_tool`; Slack renders `reason["kind"]` as Block Kit with approval buttons (delete adds a linked cert/secret checklist).

## 🔧 Implementation

**File:** `apps/agents/leaf_account_manager.py`  
**Model:** Inherits from parent (Claude Haiku 4.5)  
**Pattern:** Strands `@tool` (reads) + `@tool(context=True)` (writes raise approval interrupts)

```python
@tool
def lookup_principal(principal: str) -> str:
    """Return principal metadata, owner, linked accounts, access, and risks (offline stub)."""
    info = get_principal(principal)
    if not info:
        return f"No principal record found for '{principal}'."
    return _format_principal(info)


@tool(context=True)
def request_account_delete(tool_context: ToolContext, principal: str) -> str:
    """Write action: pause for human approval, then record the offboarding only. The interrupt
    surfaces linked certificates and secrets so the human can review offboarding impact."""
    reason = _account_reason("account_delete", f"계정 종료 승인 — {principal}", principal, {})
    decision = tool_context.interrupt(name=INTERRUPT_ACCOUNT_DELETE, reason=reason)
    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        return f"Account deletion for {principal} was cancelled. No change executed."
    # ... records the approved offboarding + linked cert/secret revoke list (sandbox: no real deletion)


def build_account_manager_agent(model: BedrockModel, session_manager: Any | None = None) -> Agent:
    return Agent(
        model=model,
        name="account_manager",
        session_manager=session_manager,  # only set when this leaf is the top-level agent
        tools=[
            lookup_principal, list_accounts, list_access, list_credentials, list_principals,
            list_linked_resources, validate_onboarding, validate_offboarding, find_stale_accounts,
            request_account_create, request_account_update, request_account_delete,
        ],
        system_prompt=(
            "You are an account-manager specialist. People, service accounts, applications, "
            "workloads, and agent identities are all principals, and every principal can own "
            "certificates and secrets. Use the read tools for questions; for a write, call "
            "request_account_create / request_account_update / request_account_delete — each pauses "
            "for human approval. Parse the principal name from the request; never claim a change "
            "happened without approval."
        ),
    )
```

`_account_reason(kind, title, principal, detail)` builds the interrupt reason
`{"kind", "title", "principal", "record": {...}, "linked_resources": {"certificates": [...],
"secrets": [...]}}`. The three write tools use interrupt names `account_create_approval`,
`account_update_approval`, and `account_delete_approval`.

## 📊 Tools

| Tool | Signature | Interrupt? | Status |
|------|-----------|-----------|--------|
| `lookup_principal` | `(principal: str) -> str` | ❌ no | ✅ Phase 1 |
| `list_accounts` | `(principal: str) -> str` | ❌ no | ✅ Phase 1 |
| `list_access` | `(principal: str) -> str` | ❌ no | ✅ Phase 1 |
| `list_credentials` | `(principal: str) -> str` | ❌ no | ✅ Phase 1 |
| `list_principals` | `(principal_type: str = "") -> str` | ❌ no | ✅ Phase 1 |
| `list_linked_resources` | `(principal: str) -> str` | ❌ no | ✅ Phase 1 |
| `validate_onboarding` | `(principal: str) -> str` | ❌ no | ✅ Phase 1 |
| `validate_offboarding` | `(principal: str) -> str` | ❌ no | ✅ Phase 1 |
| `find_stale_accounts` | `() -> str` | ❌ no | ✅ Phase 1 |
| `request_account_create` | `(tool_context, principal, principal_type="user", owner="")` | ✅ yes | ✅ Phase 1 |
| `request_account_update` | `(tool_context, principal, change="")` | ✅ yes | ✅ Phase 1 |
| `request_account_delete` | `(tool_context, principal)` | ✅ yes | ✅ Phase 1 |

### lookup_principal

Returns metadata for a named principal.

**Example:**
```
Principal: deploy-bot
Type: service_account
Owner: platform-team
Status: active
Systems: AWS IAM, GitHub, Slack
```

### list_accounts

Lists linked accounts across systems (AWS IAM, GitHub, etc.).

**Example:**
```
Accounts for deploy-bot:
  - AWS IAM: arn:aws:iam::123456789012:role/deploy-bot
  - GitHub: token: ghp_***** (last-rotated: 90d ago)
  - Slack: bot_id: B****
```

### list_credentials

Lists known credential material for a principal (keys, tokens, certificates).

**Example:**
```
Credentials for deploy-bot:
  - aws_access_key_id (last-rotated: 60d ago)
  - nginx.internal certificate (days_remaining=7, expiring_soon)
  - aws_secret: deploy-bot-key (created: 2024-01-01)
```

### find_stale_accounts

Identifies principals idle > 90 days or without an owner.

**Example:**
```
Stale principals (idle > 90d or no owner):
  - contractor.old: No owner assigned
  - batch-test: Last login: 180d ago
  - legacy-app: Last token rotation: 200d ago
```

## 📋 Mock principal registry

Centralized in `apps/mock_data.py`:

| Principal | Type | Owner | Status | Credentials linked | Notes |
|-----------|------|-------|--------|-------------------|-------|
| `new.engineer` | user | hr-team | onboarding | — | New joiner |
| `alice.prod` | user | engineering | active | aws_secret: alice-key | Active user |
| `leaving.contractor` | contractor | hr-team | offboarding | — | Exit in progress |
| `deploy-bot` | service_account | platform-team | active | `nginx.internal` cert (expiring_soon), aws_access_key | CI/CD bot |
| `payments-api` | application | payments-team | active | `api.example.com` cert (valid) | Production app |
| `batch-runner` | workload | data-team | active | `old.example.com` cert (expired) | Batch job |
| `sandbox-orchestrator` | agent_identity | ai-team | active | — | AgentCore runtime |

**To extend:** add a principal entry to the registry in `apps/mock_data.py`.

## 🔄 Principal model (ℹ️ reference)

Each principal carries:

| Field | Type | Example |
|-------|------|---------|
| `name` | str | `"deploy-bot"` |
| `type` | enum | `"service_account"` ∈ {user, contractor, service_account, application, workload, agent_identity} |
| `owner` | str | `"platform-team"` |
| `status` | enum | `"active"` ∈ {onboarding, active, stale, expiring, offboarding, disabled} |
| `systems` | list | `["AWS IAM", "GitHub", "Slack"]` |
| `accounts` | dict | `{"AWS IAM": "arn:...", "GitHub": "ghp_..."}` |
| `credentials` | list | `["aws_access_key_id (60d)", "nginx.internal cert (7d)", ...]` |

### Credential types

- **Certificate:** Linked to cert-leaf; format `{domain} certificate ({days_remaining}d, {status})`
- **AWS key:** `aws_access_key_id (last-rotated: {age})`
- **Token:** `{system}_token (last-rotated: {age})`
- **Secret:** `aws_secret: {secret_name} (created: {date})`

## ⚙️ Write tools (Phase 1, interrupt-based)

All three are `@tool(context=True)`, raise an approval interrupt, and on approval record only
(sandbox — no real provisioning/deletion); on cancel they return "… No change executed." They
apply to **all** principal types, not just AWS accounts.

### request_account_create

```python
@tool(context=True)
def request_account_create(
    tool_context: ToolContext, principal: str, principal_type: str = "user", owner: str = ""
) -> str:
    """Request creation of a new principal/account of any type. Pauses for human approval."""
    reason = _account_reason(
        "account_create", f"계정 생성 승인 — {principal}", principal,
        {"type": principal_type, "owner": owner or "(unassigned)"},
    )
    decision = tool_context.interrupt(name=INTERRUPT_ACCOUNT_CREATE, reason=reason)
    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        return f"Account creation for {principal} was cancelled. No change executed."
    return f"Account creation approved and recorded for {principal} ... Sandbox: no live change."
```

### request_account_update

`request_account_update(tool_context, principal, change="")` → interrupt `account_update_approval`,
reason kind `account_update`. Records the approved change only.

### request_account_delete

`request_account_delete(tool_context, principal)` → interrupt `account_delete_approval`, reason
kind `account_delete`. The reason includes `linked_resources = {"certificates": [...],
"secrets": [...]}` so the Slack UI can show an offboarding checklist of certs/secrets to revoke.

## 🌐 Deployment

### In-process (Phase 1 default)

- Wrapped via `account_agent.as_tool(preserve_context=True)`; the live instance stays warm across interrupt cycles
- State persists via the top-level orchestrator's session manager (this leaf carries none)
- No AWS API calls (mock data only)

### Production (Phase 2+)

Replace mock data with live lookups:

```python
def lookup_principal_live(principal: str) -> str:
    # AWS IAM: iam.get_user() / iam.get_role()
    # AWS Identity Center: identity-store.describe_user()
    # GitHub: github API
    # Combine results + return formatted summary
```

## 📚 References

- **Strands interrupts:** <https://strandsagents.com/docs/user-guide/concepts/interrupts/>
- **AWS IAM:** <https://docs.aws.amazon.com/iam/>
- **AWS Identity Center:** <https://docs.aws.amazon.com/singlesignon/>
- **Agents-as-tools + interrupts:** `Agent.as_tool(..., preserve_context=True)` (native bubble + resume)
