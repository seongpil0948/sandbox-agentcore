import logging
from typing import Any

from strands import Agent, tool
from strands.models import BedrockModel
from strands.types.tools import ToolContext

from apps.mock_data import (
    CERTIFICATE_TYPE_DESCRIPTIONS,
    CREDENTIAL_RENEWAL_METHODS,
    BasicCredentialRecord,
    CertificateRecord,
    SecretRecord,
    get_basic_credential,
    get_certificate,
    get_secret,
    list_basic_credentials,
    list_certificates,
    list_secrets,
)

logger = logging.getLogger(__name__)

INTERRUPT_CREDENTIAL_SELECTION = "credential_selection"
INTERRUPT_CREDENTIAL_RENEWAL = "credential_renewal_approval"

_APPROVE_TOKENS = frozenset(
    {"approve", "approved", "yes", "y", "renew", "rotate", "reset", "confirm"}
)

# Typed value prefixes used in selection option values and for parsing resume responses.
_PREFIX_CERT = "cert:"
_PREFIX_SECRET = "secret:"
_PREFIX_BASIC = "basic:"


@tool
def check_cert_expiry(domain: str) -> str:
    """Return the certificate expiry status for a domain name (offline stub)."""
    info = get_certificate(domain)
    if not info:
        return f"No certificate record found for domain '{domain}'."
    return (
        f"domain={info.domain} type={info.cert_type} "
        f"days_remaining={info.days_remaining} status={info.status}"
    )


@tool
def check_credential_status(name: str) -> str:
    """Return the status of any credential — certificate domain, secret name, or basic credential
    name. Searches all three registries in order."""
    cert = get_certificate(name)
    if cert:
        return (
            f"type={cert.resource_type} domain={cert.domain} cert_type={cert.cert_type} "
            f"status={cert.status} days_remaining={cert.days_remaining} "
            f"managed_via={cert.managed_via}"
        )
    secret = get_secret(name)
    if secret:
        return (
            f"type={secret.resource_type} name={secret.name} status={secret.status} "
            f"rotation_enabled={secret.rotation_enabled} "
            f"days_since_rotation={secret.days_since_rotation} managed_via={secret.managed_via}"
        )
    basic = get_basic_credential(name)
    if basic:
        return (
            f"type={basic.resource_type} name={basic.name} principal={basic.principal} "
            f"idp={basic.idp} status={basic.status} "
            f"days_since_change={basic.days_since_change} managed_via={basic.managed_via}"
        )
    return f"No credential record found for '{name}'."


@tool
def list_credential_types() -> str:
    """List all supported credential types and their renewal/rotation methods."""
    lines = [f"- {ct}" for ct in CERTIFICATE_TYPE_DESCRIPTIONS]
    lines.append("\nRenewal methods by type:")
    lines.extend(f"  {rt}: {method}" for rt, method in CREDENTIAL_RENEWAL_METHODS.items())
    return "\n".join(lines)


def _resolve_credential(
    value: str,
) -> CertificateRecord | SecretRecord | BasicCredentialRecord | None:
    """Resolve a typed or bare credential name to a registry record.

    Accepts typed values (``cert:<domain>``, ``secret:<name>``, ``basic:<name>``) from selection
    resume payloads and bare names by searching all three registries in order.
    """
    stripped = value.strip()
    if stripped.startswith(_PREFIX_CERT):
        return get_certificate(stripped[len(_PREFIX_CERT) :])
    if stripped.startswith(_PREFIX_SECRET):
        return get_secret(stripped[len(_PREFIX_SECRET) :])
    if stripped.startswith(_PREFIX_BASIC):
        return get_basic_credential(stripped[len(_PREFIX_BASIC) :])
    # Bare name: try each registry in order.
    return get_certificate(stripped) or get_secret(stripped) or get_basic_credential(stripped)


def _selection_reason(scope: str = "") -> dict[str, Any]:
    """Build a channel-agnostic payload for credential selection interrupts.

    Args:
        scope: Optional hint to narrow the picker — ``"cert"``, ``"secret"``,
            ``"basic"``, or ``""`` for all.
    """
    options: list[dict[str, Any]] = []
    if not scope or scope == "cert":
        options.extend(
            {
                "value": f"{_PREFIX_CERT}{record.domain}",
                "label": f"[cert] {record.domain} ({record.status}, {record.days_remaining}d)",
                "status": record.status,
                "resource_type": record.resource_type,
            }
            for record in list_certificates()
        )
    if not scope or scope == "secret":
        options.extend(
            {
                "value": f"{_PREFIX_SECRET}{record.name}",
                "label": f"[secret] {record.name} ({record.status})",
                "status": record.status,
                "resource_type": record.resource_type,
            }
            for record in list_secrets()
        )
    if not scope or scope == "basic":
        options.extend(
            {
                "value": f"{_PREFIX_BASIC}{record.name}",
                "label": f"[password] {record.name} ({record.principal}, {record.status})",
                "status": record.status,
                "resource_type": record.resource_type,
            }
            for record in list_basic_credentials()
        )
    return {
        "kind": "credential_selection",
        "action": "credential_renewal",
        "scope": scope,
        "prompt": "갱신/회전/초기화할 크레덴셜을 선택하세요.",
        "options": options,
    }


def _renewal_reason(
    record: CertificateRecord | SecretRecord | BasicCredentialRecord,
) -> dict[str, Any]:
    """Build the structured payload for renewal approval rendering."""
    renewal_method = CREDENTIAL_RENEWAL_METHODS.get(record.resource_type, "manual intervention")
    if isinstance(record, CertificateRecord):
        fields: dict[str, Any] = {
            "domain": record.domain,
            "cert_type": record.cert_type,
            "arn": record.arn,
            "account": record.account,
            "region": record.region,
            "status": record.status,
            "expiration": record.expiration,
            "days_remaining": record.days_remaining,
            "renewal_eligible": record.renewal_eligible,
            "renewal_status": record.renewal_status,
            "in_use": record.in_use,
        }
        target = record.domain
    elif isinstance(record, SecretRecord):
        fields = {
            "name": record.name,
            "arn": record.arn,
            "account": record.account,
            "region": record.region,
            "status": record.status,
            "rotation_enabled": record.rotation_enabled,
            "last_rotated": record.last_rotated,
            "days_since_rotation": record.days_since_rotation,
        }
        target = record.name
    else:
        fields = {
            "name": record.name,
            "principal": record.principal,
            "idp": record.idp,
            "status": record.status,
            "last_changed": record.last_changed,
            "days_since_change": record.days_since_change,
        }
        target = record.name

    return {
        "kind": "credential_renewal",
        "action": "credential_renewal",
        "title": f"크레덴셜 갱신 승인 — {target}",
        "target": target,
        "resource_type": record.resource_type,
        "record": {
            **fields,
            "resource_type": record.resource_type,
            "managed_via": record.managed_via,
            "management_endpoint": record.management_endpoint,
            "renewal_method": renewal_method,
        },
    }


def _execute_credential_renewal(
    record: CertificateRecord | SecretRecord | BasicCredentialRecord,
) -> str:
    """Record the approved renewal path without executing a live mutation."""
    if isinstance(record, CertificateRecord):
        if not record.renewal_eligible:
            return (
                f"Certificate renewal approved for {record.domain}, but it is not auto-renewable "
                f"({record.renewal_status}). Logged as a manual re-issue/re-import request only. "
                "Sandbox: no live change executed."
            )
        if record.managed_via == "ssh":
            return (
                f"Certificate renewal approved for {record.domain}. "
                f"Recorded `certbot renew` + `nginx -s reload` over {record.management_endpoint}. "
                "Sandbox: no live change executed."
            )
        if record.managed_via == "acm_api":
            return (
                f"Certificate renewal approved for {record.domain}. "
                f"Recorded ACM renewal/re-import request via {record.management_endpoint}. "
                "Sandbox: no live change executed."
            )
        return (
            f"Certificate renewal approved and recorded for {record.domain} "
            f"({record.cert_type}, {record.renewal_status}). Sandbox: no live change executed."
        )
    if isinstance(record, SecretRecord):
        return (
            f"Secret rotation approved for {record.name}. "
            f"Recorded Secrets Manager rotation request via {record.management_endpoint}. "
            "Sandbox: no live change executed."
        )
    # BasicCredentialRecord
    return (
        f"Password reset approved for {record.name} (principal={record.principal}, idp={record.idp}). "
        f"Recorded password reset + MFA re-enrollment request via {record.management_endpoint}. "
        "Sandbox: no live change executed."
    )


@tool(context=True)
def request_credential_renewal(
    tool_context: ToolContext, credential: str = "", kind: str = ""
) -> str:
    """Renew, rotate, or reset ANY credential — certificate, secret, or password.

    Call this IMMEDIATELY for any renewal/rotation/reset request, even when no target is
    provided. Pass ``credential=""`` and the tool presents a picker. ``kind`` can hint the
    scope: ``"cert"``, ``"secret"``, or ``"basic"`` (password). The flow pauses for human
    approval via Slack and records only the approved outcome (no live mutation). Do NOT ask
    the user for credential details before calling this tool.
    """
    record = _resolve_credential(credential) if credential else None

    if record is None:
        logger.info(
            "Credential selection interrupt: credential=<%s> kind=<%s>",
            credential or "<none>",
            kind or "<none>",
        )
        chosen = tool_context.interrupt(
            name=INTERRUPT_CREDENTIAL_SELECTION,
            reason=_selection_reason(kind.strip().lower()),
        )
        record = _resolve_credential(str(chosen).strip())
        if record is None:
            return f"No credential record found for '{chosen}'. Nothing to renew."

    logger.info(
        "Credential renewal interrupt: type=<%s> target=<%s>",
        record.resource_type,
        getattr(record, "domain", getattr(record, "name", "unknown")),
    )
    decision = tool_context.interrupt(
        name=INTERRUPT_CREDENTIAL_RENEWAL,
        reason=_renewal_reason(record),
    )

    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        target = getattr(record, "domain", getattr(record, "name", "unknown"))
        logger.info("Credential renewal cancelled by human: target=<%s>", target)
        return f"Credential renewal for {target} was cancelled. No change executed."

    target = getattr(record, "domain", getattr(record, "name", "unknown"))
    logger.info("Credential renewal approved by human: target=<%s>", target)
    return _execute_credential_renewal(record)


def build_credential_agent(model: BedrockModel, session_manager: Any | None = None) -> Agent:
    """Build the credential specialist agent (certificates, secrets, passwords)."""
    return Agent(
        model=model,
        name="credential_specialist",
        session_manager=session_manager,
        tools=[
            check_cert_expiry,
            check_credential_status,
            list_credential_types,
            request_credential_renewal,
        ],
        system_prompt=(
            "You are a credential specialist. You manage ALL credential types: TLS/SSL certificates "
            "(certbot/nginx, ACM), AWS Secrets Manager secrets, and basic passwords/IdP accounts. Rules:\n"
            "- Status or expiry check for a certificate domain → call check_cert_expiry.\n"
            "- Status check for any credential (cert, secret, password) → call check_credential_status.\n"
            "- List supported credential types → call list_credential_types.\n"
            "- ANY renewal, rotation, or reset request for a certificate, secret, or password → "
            "immediately call request_credential_renewal, even when no target is named. Pass "
            "credential='' and the tool shows a picker. NEVER ask the user to name the credential "
            "or provide any details; the tool collects everything and pauses for human approval.\n"
            "Never claim a renewal or rotation happened without approval. Be concise."
        ),
    )


# Backwards-compatible alias so existing callers (local_fallback, principal_lifecycle tests)
# that import check_cert_expiry from this module continue to work.
build_cert_agent = build_credential_agent
