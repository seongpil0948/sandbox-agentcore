## Spec: Leaf Agent — Certificate Management

**Hierarchy:** leaf  
**Parent:** Human Resource supervisor (`spec_supervisor_human-resorce-agent.md`)  
**Spec path:** `doc/spec_leaf_cert-agent.md`  
**Implementation:** `apps/agents/leaf_cert.py` → `build_cert_agent(model, session_manager) -> Agent`

---

## 📊 Request flow with HITL interrupt

The cert agent is exposed to the supervisor via `cert_agent.as_tool(name="cert_specialist",
preserve_context=True)`, so any interrupt it raises surfaces natively as the parent's
`stop_reason == "interrupt"`.

```
Supervisor: tool cert_specialist  (cert_agent.as_tool(preserve_context=True))
└─ cert_agent(query)
   │
   ├─ If read: check_cert_expiry(domain), list_cert_types()
   │  └─ returns text directly (no interrupt)
   │
   └─ If write: request_certificate_renewal(tool_context, domain="")
      │
      ├─ (1) domain empty/unknown → cert_selection interrupt
      │      tool_context.interrupt(
      │        name="cert_selection",
      │        reason={"kind": "cert_selection", "options": [ …every cert… ]}
      │      )
      │      [Slack: external_select picker served by a block_suggestion listener]
      │      → returns the chosen domain
      │
      └─ (2) cert_renewal_approval interrupt
             tool_context.interrupt(
               name="cert_renewal_approval",
               reason={"kind": "cert_renewal", "title": …, "domain": …, "record": {…}}
             )
             [Slack: detail card incl. 관리 방식/managed_via + [승인]/[취소]]
             [Socket Mode: hitl.resume(session_id, interrupt_id, response)]
             → returns the approval decision
                ├─ approved → _execute_renewal(record) records the SSH/ACM path
                └─ cancelled → "… was cancelled. No change executed."
             → returns text; stop_reason bubbles up via as_tool
```

## 💡 Purpose

Manages certificate lifecycle visibility and HITL-gated renewal operations:

- **Read-only tools** (no approval needed):
  - `check_cert_expiry(domain)` → status, days remaining, renewal recommendation
  - `list_cert_types()` → supported cert types (certbot, ACM, ACM imported)

- **Write tools** (approval required via Strands interrupts):
  - `request_certificate_renewal(tool_context, domain="")` → raises a `cert_selection` interrupt
    (when no/unknown domain), then a `cert_renewal_approval` interrupt → awaits human decision

## 📥 Input contract

From supervisor via `Agent.as_tool` (the wrapper tool takes a single string):

| Field | Type | Example |
|-------|------|---------|
| `query` | string | `"Check certificate status for api.example.com"` or `"Renew cert api.example.com"` |

## 📤 Output contract

**Read-only:**
```
domain=api.example.com type=ACM Public Certificate days_remaining=42 status=valid
Recommendation: Renewal within 7-14 days
```

**Write (interrupted):** Interrupt propagates up natively via `as_tool`. Slack renders `reason["kind"]` as Block Kit.

## 🔧 Implementation

**File:** `apps/agents/leaf_cert.py`  
**Model:** Inherits from parent (Claude Haiku 4.5)  
**Pattern:** Strands `@tool` / `@tool(context=True)`; a single write tool raises two sequential interrupts

```python
INTERRUPT_CERT_SELECTION = "cert_selection"
INTERRUPT_CERT_RENEWAL = "cert_renewal_approval"


@tool
def check_cert_expiry(domain: str) -> str:
    """Return the certificate expiry status for a domain (offline stub)."""
    info = get_certificate(domain)
    if not info:
        return f"No certificate record found for domain '{domain}'."
    return f"domain={info.domain} type={info.cert_type} days_remaining={info.days_remaining} status={info.status}"


@tool
def list_cert_types() -> str:
    """List supported certificate types and their renewal characteristics."""
    return "\n".join(f"- {ct}" for ct in CERTIFICATE_TYPE_DESCRIPTIONS)


@tool(context=True)
def request_certificate_renewal(tool_context: ToolContext, domain: str = "") -> str:
    """Write action: pause for human approval and record only (no real mutation).

    If domain is empty/unknown, first pause with a cert_selection interrupt so the human picks
    the certificate, then pause again for the renewal approval.
    """
    record = get_certificate(domain) if domain else None

    if record is None:
        chosen = tool_context.interrupt(name=INTERRUPT_CERT_SELECTION, reason=_selection_reason())
        record = get_certificate(str(chosen).strip())
        if record is None:
            return f"No certificate record found for '{chosen}'. Nothing to renew."

    decision = tool_context.interrupt(name=INTERRUPT_CERT_RENEWAL, reason=_renewal_reason(record))
    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        return f"Certificate renewal for {record.domain} was cancelled. No change executed."
    return _execute_renewal(record)


def build_cert_agent(model: BedrockModel, session_manager: Any | None = None) -> Agent:
    return Agent(
        model=model,
        name="cert_specialist",
        session_manager=session_manager,  # only set when this leaf is the top-level agent
        tools=[check_cert_expiry, list_cert_types, request_certificate_renewal],
        system_prompt=(
            "You are a certificate management specialist. For any renewal or replacement request, "
            "call request_certificate_renewal — even if the user did not name a domain (the tool "
            "presents a picker). Never ask the user to restate the domain; never claim a renewal "
            "happened without approval."
        ),
    )
```

`_selection_reason()` returns `{"kind": "cert_selection", "options": [...]}` (one option per
certificate: `value=domain`, `label`, `status`, `days_remaining`, `cert_type`).
`_renewal_reason(record)` returns `{"kind": "cert_renewal", "title", "domain", "record": {...}}`
where `record` carries `domain, cert_type, arn, account, region, status, expiration,
days_remaining, renewal_eligible, renewal_status, in_use, managed_via, management_endpoint`.
`_execute_renewal(record)` records a method-specific outcome: `managed_via=="ssh"` →
`certbot renew` + `nginx -s reload` over `ssh://…`; `managed_via=="acm_api"` → an ACM
renewal/re-import request via `https://acm.<region>.amazonaws.com`; a non-eligible cert is logged
as a manual re-issue. On cancel: "… was cancelled. No change executed." (sandbox — never a live mutation).

## 📊 Tools

| Tool | Signature | Interrupt? | Status |
|------|-----------|-----------|--------|
| `check_cert_expiry` | `(domain: str) -> str` | ❌ no | ✅ Phase 1 |
| `list_cert_types` | `() -> str` | ❌ no | ✅ Phase 1 |
| `request_certificate_renewal` | `(tool_context: ToolContext, domain: str = "") -> str` | ✅ yes (2-phase: selection + approval) | ✅ Phase 1 |

### check_cert_expiry

**Return format:**
```
domain={domain} type={type} days_remaining={days} status={status}
```

**Example responses:**
- Valid: `domain=api.example.com type=ACM Public Certificate days_remaining=42 status=valid`
- Expiring: `domain=nginx.internal type=Certbot DNS Challenge days_remaining=7 status=expiring_soon`
- Expired: `domain=old.example.com type=ACM Imported Certificate days_remaining=-3 status=expired`

### list_cert_types

Returns a bulleted list of supported certificate types + renewal method for each.

### request_certificate_renewal (Phase 1, two-phase)

**When called:** any renewal/replacement request — even with no domain (the tool presents a picker).

**What happens:**
1. **Selection phase (only if domain empty/unknown):**
   `tool_context.interrupt(name="cert_selection", reason={"kind": "cert_selection", "options": [...]})`.
   Slack renders an `external_select` cert picker (options served by a `block_suggestion`
   listener via `build_hitl_options`). The chosen domain is returned from the interrupt.
2. **Approval phase:**
   `tool_context.interrupt(name="cert_renewal_approval", reason={"kind": "cert_renewal", "record": {...}})`.
   Slack renders a detail card including the `관리 방식`/`managed_via` line + `[승인]`/`[취소]`.
3. On `[승인]` → `_execute_renewal(record)` records the method-specific outcome:
   - `managed_via=="ssh"` → `certbot renew` + `nginx -s reload` over `ssh://…`
   - `managed_via=="acm_api"` → ACM renewal/re-import request via `https://acm.<region>.amazonaws.com`
   - non-eligible cert → logged as a manual re-issue/re-import
4. On `[취소]` → "Certificate renewal for {domain} was cancelled. No change executed."

Sandbox: every outcome is recorded only; no live mutation is ever performed.

## 📋 Mock certificate registry

Centralized in `apps/mock_data.py` (`CertificateRecord`). Each record carries a `managed_via`
method (`ssh` = certbot + `nginx -s reload`, or `acm_api` = HTTPS ACM API) and a
`management_endpoint`, modeling that an owned cert can be renewed via multiple methods:

| Domain | Type | Status | managed_via | management_endpoint |
|--------|------|--------|-------------|---------------------|
| `api.example.com` | ACM public cert | valid | `acm_api` | `https://acm.us-east-1.amazonaws.com` |
| `nginx.internal` | certbot-dns-route53 | expiring_soon | `ssh` | `ssh://deploy@nginx.internal` |
| `payments.example.com` | certbot-dns-route53 | expiring_soon | `ssh` | `ssh://deploy@payments.example.com` |
| `old.example.com` | ACM imported cert | expired | `acm_api` | `https://acm.us-west-2.amazonaws.com` |

**To extend:** add a `CertificateRecord` to the registry in `apps/mock_data.py`.

## 🔄 Interrupt flow in detail

### Step 1: Agent calls interrupt

```python
decision = tool_context.interrupt(
    name="cert_renewal_approval",
    reason={...}
)
# Agent **pauses here** while HITL processes
```

### Step 2: HITL engine receives interrupt

```python
# In hitl.start()
result = agent(prompt)
if result.stop_reason == "interrupt":
    # Extract interrupt name + reason
    interrupt = _first_interrupt(result)
    # Post to Slack + return to client
    return HitlOutcome(
        status=STATUS_INTERRUPT,
        interrupt_id=interrupt.interrupt_id,
        interrupt_name="cert_renewal_approval",
        reason=interrupt.reason
    )
```

### Step 3: Slack posts Block Kit

```python
# In apps/slack/socket_mode.py::_post_outcome()
if outcome.status == STATUS_INTERRUPT:
    blocks = build_interrupt_blocks(
        reason=outcome.reason,
        session_id=session_id,
        interrupt_id=outcome.interrupt_id
    )
    client.chat_postMessage(
        channel=..., thread_ts=..., blocks=blocks
    )
```

Block Kit includes:
- Title: "Certificate renewal approval — {domain}"
- Details: domain, status, days_remaining, type
- Buttons: `[승인]` (action: `ACTION_HITL_APPROVE`) + `[취소]` (action: `ACTION_HITL_CANCEL`)
- Footer: "Sandbox: Approval recorded; no live mutation"

### Step 4: User clicks button (or picks a cert)

```
User clicks [승인] in Slack
│
Socket Mode receives: block_actions event
│
─ button value: {"session": "...", "interrupt_id": "...", "response": "approved"}
```

For the `cert_selection` `external_select`, the chosen option carries no button value, so the
resume context (`session`, `interrupt_id`) is encoded in the select's `block_id`; the chosen
`selected_option.value` (a domain) becomes the response.

### Step 5: Socket Mode calls hitl.resume()

```python
# In apps/slack/socket_mode.py::_handle_hitl_action()
outcome = hitl.resume(
    session_id=session_id,
    interrupt_id=interrupt_id,
    response=response,  # "approved" | "cancelled", or the selected domain for cert_selection
)
```

### Step 6: Agent resumes

```python
# In hitl.py::resume()
agent = _get_or_build_agent(session_id)  # reuses the live orchestrator (keeps nested state warm)
result = agent(interrupt_response)       # feeds [{"interruptResponse": {"interruptId": id, "response": x}}]

# Back in leaf_cert::request_certificate_renewal()
decision = tool_context.interrupt(...)   # returns NOW: "approved"
if str(decision).strip().lower() in _APPROVE_TOKENS:
    return _execute_renewal(record)
```

### Step 7: Response bubbles up

```
cert_agent returns text
│
as_tool(cert_specialist) returns it to the supervisor (stop_reason not "interrupt")
│
as_tool(human_resource_supervisor) returns it to the orchestrator
│
hitl.outcome_from_result() → status=FINAL
│
Socket Mode updates the Slack message with the final text
```

## ⚙️ Status thresholds

| Status | Condition | Typical action |
|--------|-----------|---|
| `valid` | days_remaining > 30 | Monitor; no action |
| `expiring_soon` | 0 < days_remaining ≤ 30 | Schedule renewal |
| `expired` | days_remaining ≤ 0 | Urgent re-issue |

## 🌐 Deployment

### In-process (Phase 1 default)

- Wrapped via `cert_agent.as_tool(preserve_context=True)`; the live instance stays warm across interrupt cycles
- State persists via the top-level orchestrator's session manager (this leaf carries none)
- No AWS cert operations (sandbox only; mocked data)

### Production (Phase 2)

Replace mock data with live AWS calls:

```python
# Instead of the CertificateRecord registry in apps/mock_data.py
def check_cert_expiry_live(domain: str) -> str:
    acm = boto3.client("acm")
    certs = acm.list_certificates()
    # Match domain → get expiry → compute days_remaining
    # Return real status

def request_cert_renewal_live(domain: str) -> str:
    # Real certbot / ACM import logic
    # Call actual AWS APIs or SSH to host
```

## 📚 References

- **Strands interrupts:** <https://strandsagents.com/docs/user-guide/concepts/interrupts/>
- **ToolContext.interrupt() API:** Strands SDK source (`strands/tools/`)
- **Slack Block Kit:** <https://api.slack.com/block-kit>
- **AWS ACM:** <https://docs.aws.amazon.com/acm/>
- **Certbot renewal:** <https://certbot.eff.org/docs/>

- [x] `check_cert_expiry` returns deterministic status for known domains.
- [x] Unknown domain returns the not-found message.
- [x] `list_cert_types` includes `certbot-dns-route53` and `ACM`.
- [x] Slack Block Kit selection + approval flow exists for renewal.
- [x] Covered by smoke tests in `tests/test_agent.py`.
- [x] `request_certificate_renewal` implemented (Phase 1): cert_selection → cert_renewal_approval interrupts.

### References

- Strands `@tool`: <https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/>
- HITL: <https://strandsagents.com/docs/user-guide/concepts/agents/interventions/human-in-the-loop/>
