from typing import Any

from strands import Agent, tool
from strands.models import BedrockModel
from strands.types.tools import AgentTool

from apps.utils.runtime_invocation import invoke_agent_runtime_text

from .leaf_account_manager import build_account_manager_agent
from .leaf_cert import build_cert_agent
from .principal_lifecycle import verify_principal_lifecycle, verify_principal_types

_CERT_TOOL_DESCRIPTION = (
    "Handle ANY certificate request — status, renewal, or replacement — including when the user "
    "named no domain. Pass the user's message verbatim as the input. The specialist shows a "
    "certificate picker and pauses for human approval; it never needs you to collect the domain "
    "or any details first."
)
_ACCOUNT_TOOL_DESCRIPTION = (
    "Handle ANY account/principal request — lookups, access, onboarding, offboarding, and "
    "account create/update/delete — for any principal type. Pass the user's message verbatim as "
    "the input. The specialist parses the principal and pauses for human approval on writes; it "
    "never needs you to collect details first."
)


def _cert_tool(model: BedrockModel, leaf_arn: str | None) -> AgentTool:
    """Build the cert-specialist tool: a remote runtime call or an in-process sub-agent."""
    if leaf_arn:

        @tool(name="cert_specialist")
        def cert_specialist(query: str) -> str:
            """Delegate certificate management queries to the cert specialist leaf runtime."""
            return invoke_agent_runtime_text(leaf_arn, query)

        return cert_specialist

    cert_agent = build_cert_agent(model)
    return cert_agent.as_tool(
        name="cert_specialist",
        description=_CERT_TOOL_DESCRIPTION,
        preserve_context=True,
    )


def _account_tool(model: BedrockModel, account_leaf_arn: str | None) -> AgentTool:
    """Build the account-manager tool: a remote runtime call or an in-process sub-agent."""
    if account_leaf_arn:

        @tool(name="account_manager")
        def account_manager(query: str) -> str:
            """Delegate account, principal, onboarding, and offboarding queries to account-manager."""
            return invoke_agent_runtime_text(account_leaf_arn, query)

        return account_manager

    account_agent = build_account_manager_agent(model)
    return account_agent.as_tool(
        name="account_manager",
        description=_ACCOUNT_TOOL_DESCRIPTION,
        preserve_context=True,
    )


def build_hr_supervisor(
    model: BedrockModel,
    leaf_arn: str | None = None,
    account_leaf_arn: str | None = None,
    session_manager: Any | None = None,
) -> Agent:
    """Build the HR/identity supervisor.

    In-process children (cert + account leaves) are wrapped with ``Agent.as_tool`` so Strands
    propagates their human-in-the-loop interrupts up to this supervisor natively (and forwards
    the human response back down on resume). When a ``*_arn`` is set the child is a remote
    runtime instead, invoked over ``invoke_agent_runtime``.
    """

    @tool
    def principal_lifecycle_auditor(principal: str) -> str:
        """Verify account + credential/certificate lifecycle coverage for one principal by
        coordinating the account-manager and cert leaves."""
        return verify_principal_lifecycle(principal)

    @tool
    def principal_type_coverage() -> str:
        """Verify whether the hierarchy can manage account + credential lifecycle for each
        principal type (human, service account, application, workload)."""
        return verify_principal_types()

    return Agent(
        model=model,
        name="hr_supervisor",
        session_manager=session_manager,
        tools=[
            _cert_tool(model, leaf_arn),
            _account_tool(model, account_leaf_arn),
            principal_lifecycle_auditor,
            principal_type_coverage,
        ],
        system_prompt=(
            "You are an HR and identity routing supervisor. You do NOT ask the user for details "
            "and you do NOT answer certificate or account questions yourself — you route to "
            "specialists by calling a tool. Rules:\n"
            "- Certificate / TLS / SSL / renew / replace / expiry → immediately call "
            "cert_specialist with the user's message verbatim.\n"
            "- Account / principal / user / onboard / offboard / create / update / delete → "
            "immediately call account_manager with the user's message verbatim.\n"
            "- Principal lifecycle coverage → principal_lifecycle_auditor or "
            "principal_type_coverage.\n"
            "Call the specialist EVEN IF the user named no certificate, domain, or principal — the "
            "specialist presents its own picker and pauses for human approval. NEVER ask the user "
            "for the certificate name, type, expiration, owner, or any other detail. NEVER reply "
            "with a numbered list of questions. After the specialist returns, relay its result "
            "concisely."
        ),
    )
