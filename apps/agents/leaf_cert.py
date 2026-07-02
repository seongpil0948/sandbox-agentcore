import logging
from typing import Any

from strands import Agent, tool
from strands.models import BedrockModel
from strands.types.tools import ToolContext

from apps.mock_data import (
    CERTIFICATE_TYPE_DESCRIPTIONS,
    CertificateRecord,
    get_certificate,
    list_certificates,
)

logger = logging.getLogger(__name__)

INTERRUPT_CERT_SELECTION = "cert_selection"
INTERRUPT_CERT_RENEWAL = "cert_renewal_approval"

_APPROVE_TOKENS = frozenset({"approve", "approved", "yes", "y", "renew", "confirm"})


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
def list_cert_types() -> str:
    """List supported certificate types and their renewal characteristics."""
    return "\n".join(f"- {ct}" for ct in CERTIFICATE_TYPE_DESCRIPTIONS)


def _selection_reason() -> dict[str, Any]:
    """Block-Kit-agnostic payload describing the certificate choices for a selection interrupt."""
    return {
        "kind": "cert_selection",
        "action": "cert_renewal",
        "prompt": "갱신할 인증서를 선택하세요.",
        "options": [
            {
                "value": record.domain,
                "label": f"{record.domain} ({record.status}, {record.days_remaining}d)",
                "status": record.status,
                "days_remaining": record.days_remaining,
                "cert_type": record.cert_type,
            }
            for record in list_certificates()
        ],
    }


def _renewal_reason(record: CertificateRecord) -> dict[str, Any]:
    """Structured payload for the renewal-approval interrupt (rendered by the Slack layer)."""
    return {
        "kind": "cert_renewal",
        "action": "cert_renewal",
        "title": f"인증서 갱신 승인 — {record.domain}",
        "domain": record.domain,
        "record": {
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
            "managed_via": record.managed_via,
            "management_endpoint": record.management_endpoint,
        },
    }


def _execute_renewal(record: CertificateRecord) -> str:
    """Record the approved renewal along the certificate's management path (no live mutation)."""
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


@tool(context=True)
def request_certificate_renewal(tool_context: ToolContext, domain: str = "") -> str:
    """Renew (or replace) a certificate. Call this IMMEDIATELY for any renewal/replacement
    request, even when no domain is given — pass ``domain=""`` and the tool presents a picker.
    It pauses for human approval via Slack and only records the approved outcome (no real
    mutation). Do NOT ask the user for the domain or any other detail before calling this.
    """
    record = get_certificate(domain) if domain else None

    if record is None:
        logger.info("Cert selection interrupt requested: domain=%s", domain or "<none>")
        chosen = tool_context.interrupt(name=INTERRUPT_CERT_SELECTION, reason=_selection_reason())
        record = get_certificate(str(chosen).strip())
        if record is None:
            return f"No certificate record found for '{chosen}'. Nothing to renew."

    logger.info("Cert renewal interrupt requested: domain=%s", record.domain)
    decision = tool_context.interrupt(name=INTERRUPT_CERT_RENEWAL, reason=_renewal_reason(record))

    if str(decision).strip().lower() not in _APPROVE_TOKENS:
        logger.info("Cert renewal cancelled by human: domain=%s", record.domain)
        return f"Certificate renewal for {record.domain} was cancelled. No change executed."

    logger.info("Cert renewal approved by human: domain=%s", record.domain)
    return _execute_renewal(record)


def build_cert_agent(model: BedrockModel, session_manager: Any | None = None) -> Agent:
    return Agent(
        model=model,
        name="cert_specialist",
        session_manager=session_manager,
        tools=[check_cert_expiry, list_cert_types, request_certificate_renewal],
        system_prompt=(
            "You are a certificate specialist. Rules:\n"
            "- Status lookup → call check_cert_expiry. Explain types → call list_cert_types.\n"
            "- ANY renewal or replacement request → immediately call request_certificate_renewal. "
            "If the user named no domain, still call it with domain empty — the tool shows a "
            "picker. NEVER ask the user to name or restate the domain, and NEVER ask for "
            "certificate details; the tool collects everything and pauses for human approval.\n"
            "Never claim a renewal happened without approval. Be concise."
        ),
    )
