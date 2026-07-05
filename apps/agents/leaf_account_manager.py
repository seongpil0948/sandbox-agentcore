from typing import Any

from strands import Agent, tool
from strands.models import BedrockModel
from strands.types.tools import ToolContext

from apps.agents.iam_terraform import render_iam_terraform
from apps.mock_data import (
    PRINCIPAL_TYPES as MOCK_PRINCIPAL_TYPES,
    PRINCIPALS,
    basic_credential_names,
    certificate_domains,
    get_certificate,
    get_principal,
    get_secret,
    iam_access_gaps,
    select_principals,
    secret_names,
)

PRINCIPAL_TYPES = MOCK_PRINCIPAL_TYPES

INTERRUPT_ACCOUNT_CREATE = "account_create_approval"
INTERRUPT_ACCOUNT_UPDATE = "account_update_approval"
INTERRUPT_ACCOUNT_DELETE = "account_delete_approval"

_APPROVE_TOKENS = frozenset({"approve", "approved", "yes", "y", "confirm", "execute"})


def _format_list(values: list[str]) -> str:
    """Render a deterministic bracketed list for compact text responses."""
    return "[" + ", ".join(values) + "]"


def _format_principal(info: dict[str, Any]) -> str:
    """Render one principal record in a compact key=value format."""
    return (
        f"principal={info['principal']} type={info['type']} owner={info['owner']} "
        f"status={info['status']} accounts={_format_list(info['accounts'])} "
        f"access={_format_list(info['access'])} credentials={_format_list(info['credentials'])} "
        f"risks={_format_list(info['risks'])}"
    )


@tool
def lookup_principal(principal: str) -> str:
    """Return principal metadata, owner, linked accounts, access, and risks (offline stub)."""
    info = get_principal(principal)
    if not info:
        return f"No principal record found for '{principal}'."
    return _format_principal(info)


@tool
def list_accounts(principal: str) -> str:
    """List accounts linked to a principal across identity and collaboration systems."""
    info = get_principal(principal)
    if not info:
        return f"No account records found for principal '{principal}'."
    return f"principal={info['principal']} accounts={_format_list(info['accounts'])}"


@tool
def list_access(principal: str) -> str:
    """List access grants linked to a principal."""
    info = get_principal(principal)
    if not info:
        return f"No access records found for principal '{principal}'."
    return f"principal={info['principal']} access={_format_list(info['access'])}"


@tool
def validate_onboarding(principal: str) -> str:
    """Validate onboarding readiness for a principal, including IAM permission gaps."""
    info = get_principal(principal)
    if not info:
        return f"No onboarding record found for principal '{principal}'."
    if info["status"] != "onboarding":
        return f"principal={info['principal']} onboarding_status=not_applicable current_status={info['status']}"
    gaps = iam_access_gaps(principal)
    if gaps:
        iam_part = (
            f" iam_gaps={_format_list([gap.name for gap in gaps])} "
            "iam_next_action=call propose_iam_terraform to generate the Terraform that closes them"
        )
    else:
        iam_part = " iam_gaps=none"
    return (
        f"principal={info['principal']} onboarding_status=blocked "
        f"missing={_format_list(info['risks'])}{iam_part} "
        "next_action=complete required account setup"
    )


@tool
def propose_iam_terraform(principal: str) -> str:
    """Detect a principal's IAM permission gaps and propose Terraform to close them.

    Read-only advisory: emits ``terraform-aws-modules/iam/aws`` module blocks for every missing
    IAM access requirement (read-only policies, custom policies, assume-role grants). The agent
    performs no live change — a human reviews and applies the proposal."""
    info = get_principal(principal)
    if not info:
        return f"No principal record found for '{principal}'."
    gaps = iam_access_gaps(principal)
    if not gaps:
        return (
            f"principal={principal} iam_gaps=none — no IAM permission gap detected; "
            "no Terraform needed."
        )
    hcl = render_iam_terraform(gaps)
    return (
        f"principal={principal} iam_gaps={len(gaps)} "
        f"gaps={_format_list([gap.name for gap in gaps])} "
        "module=terraform-aws-modules/iam/aws\n\n"
        f"```hcl\n{hcl}```\n"
        "Advisory only — review and apply via your IaC pipeline. Sandbox: no live change executed."
    )


@tool
def validate_offboarding(principal: str) -> str:
    """Validate offboarding risk for a principal."""
    info = get_principal(principal)
    if not info:
        return f"No offboarding record found for principal '{principal}'."
    if info["status"] != "offboarding":
        return f"principal={info['principal']} offboarding_status=not_applicable current_status={info['status']}"
    return (
        f"principal={info['principal']} offboarding_status=action_required "
        f"accounts={_format_list(info['accounts'])} access={_format_list(info['access'])} "
        f"risks={_format_list(info['risks'])}"
    )


@tool
def find_stale_accounts() -> str:
    """List known stale or risky accounts from the offline sample registry."""
    risky = [
        info
        for info in PRINCIPALS.values()
        if info["status"] in {"stale", "offboarding"} or info["risks"]
    ]
    if not risky:
        return "No stale account records found."
    return "\n".join(
        f"principal={info['principal']} status={info['status']} risks={_format_list(info['risks'])}"
        for info in risky
    )


@tool
def list_credentials(principal: str) -> str:
    """List credential material (keys, tokens, certificates) linked to a principal."""
    info = get_principal(principal)
    if not info:
        return f"No credential records found for principal '{principal}'."
    return (
        f"principal={info['principal']} type={info['type']} "
        f"credentials={_format_list(info['credentials'])}"
    )


@tool
def list_principals(principal_type: str = "") -> str:
    """List principals across all types, or filtered by a principal type such as user,
    service_account, application, workload, agent_identity, or contractor."""
    selected = select_principals(principal_type or None)
    if not selected:
        return f"No principals found for type '{principal_type}'."
    return "\n".join(
        f"principal={info['principal']} type={info['type']} status={info['status']}"
        for info in selected
    )


@tool
def list_linked_resources(principal: str) -> str:
    """List certificate, secret, and basic credential resources linked to a principal."""
    certs = certificate_domains(principal)
    secrets = secret_names(principal)
    basics = basic_credential_names(principal)
    if not certs and not secrets and not basics:
        return f"principal={principal} linked_resources=[]"
    resources: list[str] = []
    for domain in certs:
        record = get_certificate(domain)
        rtype = record.resource_type if record else "certificate"
        resources.append(f"{rtype}:{domain}")
    for name in secrets:
        record2 = get_secret(name)
        rtype2 = record2.resource_type if record2 else "aws_secret"
        resources.append(f"{rtype2}:{name}")
    for name in basics:
        resources.append(f"basic_credential:{name}")
    return f"principal={principal} linked_resources={_format_list(resources)}"


def _linked_resources(principal: str) -> dict[str, list[str]]:
    """Return linked resource names grouped by certificates, secrets, and basic credentials."""
    return {
        "certificates": certificate_domains(principal),
        "secrets": secret_names(principal),
        "basic_credentials": basic_credential_names(principal),
    }


def _account_reason(
    kind: str, title: str, principal: str, detail: dict[str, Any]
) -> dict[str, Any]:
    """Build the structured payload for account write-approval interrupts."""
    info = get_principal(principal)
    return {
        "kind": kind,
        "action": kind,
        "title": title,
        "principal": principal,
        "record": {
            "principal": principal,
            "type": (info or {}).get("type", detail.get("type", "unknown")),
            "owner": (info or {}).get("owner", detail.get("owner", "(unassigned)")),
            "status": (info or {}).get("status", "n/a"),
            **detail,
        },
        "linked_resources": _linked_resources(principal),
    }


@tool(context=True)
def request_account_create(
    tool_context: ToolContext, principal: str, principal_type: str = "user", owner: str = ""
) -> str:
    """Request creation of a new principal/account of any type (user, service_account,
    application, workload, agent_identity). Write action: pauses for human approval and records
    the approved request only (no real provisioning)."""
    reason = _account_reason(
        "account_create",
        f"계정 생성 승인 — {principal}",
        principal,
        {"type": principal_type, "owner": owner or "(unassigned)"},
    )
    decision = tool_context.interrupt(name=INTERRUPT_ACCOUNT_CREATE, reason=reason)
    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        return f"Account creation for {principal} was cancelled. No change executed."
    return (
        f"Account creation approved and recorded for {principal} "
        f"(type={principal_type}, owner={owner or 'unassigned'}). Sandbox: no live change executed."
    )


@tool(context=True)
def request_account_update(tool_context: ToolContext, principal: str, change: str = "") -> str:
    """Request an update to an existing principal/account (status, access, owner, credentials).
    Write action: pauses for human approval and records the approved change only (no live
    mutation)."""
    reason = _account_reason(
        "account_update",
        f"계정 변경 승인 — {principal}",
        principal,
        {"change": change or "(unspecified)"},
    )
    decision = tool_context.interrupt(name=INTERRUPT_ACCOUNT_UPDATE, reason=reason)
    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        return f"Account update for {principal} was cancelled. No change executed."
    return (
        f"Account update approved and recorded for {principal} "
        f"(change={change or 'unspecified'}). Sandbox: no live change executed."
    )


@tool(context=True)
def request_account_delete(tool_context: ToolContext, principal: str) -> str:
    """Request deletion/offboarding of a principal/account of any type. Write action: pauses for
    human approval and records the approved offboarding only (no real deletion). The interrupt
    surfaces linked certificates and secrets so the human can review offboarding impact."""
    reason = _account_reason(
        "account_delete",
        f"계정 종료 승인 — {principal}",
        principal,
        {},
    )
    decision = tool_context.interrupt(name=INTERRUPT_ACCOUNT_DELETE, reason=reason)
    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        return f"Account deletion for {principal} was cancelled. No change executed."
    linked = _linked_resources(principal)
    revoke = [
        *(f"certificate:{d}" for d in linked["certificates"]),
        *(f"secret:{s}" for s in linked["secrets"]),
        *(f"basic_credential:{b}" for b in linked["basic_credentials"]),
    ]
    revoke_note = f" Linked resources to revoke: {_format_list(revoke)}." if revoke else ""
    return (
        f"Account deletion/offboarding approved and recorded for {principal}.{revoke_note} "
        "Sandbox: no live change executed."
    )


def build_account_manager_agent(model: BedrockModel, session_manager: Any | None = None) -> Agent:
    """Build the account manager specialist agent."""
    return Agent(
        model=model,
        name="account_manager",
        session_manager=session_manager,
        tools=[
            lookup_principal,
            list_accounts,
            list_access,
            list_credentials,
            list_principals,
            list_linked_resources,
            validate_onboarding,
            validate_offboarding,
            find_stale_accounts,
            propose_iam_terraform,
            request_account_create,
            request_account_update,
            request_account_delete,
        ],
        system_prompt=(
            "You are an account-manager specialist. People, service accounts, applications, "
            "workloads, and agent identities are all principals, and each can own certificates, "
            "secrets, and basic credentials. Rules:\n"
            "- Read questions (who owns what, access, onboarding/offboarding status, stale "
            "accounts) → call the matching read tool (lookup_principal, list_accounts, "
            "list_access, list_credentials, list_principals, list_linked_resources, "
            "validate_onboarding, validate_offboarding, find_stale_accounts).\n"
            "- Onboarding readiness → call validate_onboarding; it reports missing MFA/Slack "
            "AND any IAM permission gaps.\n"
            "- Missing IAM permissions / access gaps / 'grant access' / 'generate terraform' / "
            "'fix IAM' → immediately call propose_iam_terraform; it emits "
            "terraform-aws-modules/iam/aws code to close the gaps (advisory, no live change).\n"
            "- Create a principal/account → immediately call request_account_create.\n"
            "- Update/modify a principal/account → immediately call request_account_update.\n"
            "- Delete/offboard/close a principal/account → immediately call request_account_delete.\n"
            "- Credential renewal, secret rotation, or password reset → these belong to the "
            "credential_specialist (the supervisor routes there); do NOT handle them here.\n"
            "Parse the principal name (and type/owner/change when present) from the user's "
            "message. Call the write tool EVEN IF some details are missing — it pauses for human "
            "approval. NEVER ask the user to restate the principal or provide details in plain "
            "text. Never claim a change happened without approval. Be concise."
        ),
    )
