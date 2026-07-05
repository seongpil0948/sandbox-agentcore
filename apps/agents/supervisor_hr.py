from typing import Any

from strands import Agent, tool
from strands.models import BedrockModel
from strands.types.tools import AgentTool

from apps.utils.runtime_invocation import invoke_agent_runtime_text

from .leaf_account_manager import build_account_manager_agent
from .leaf_credential import build_credential_agent
from .principal_lifecycle import verify_principal_lifecycle, verify_principal_types

_CREDENTIAL_TOOL_DESCRIPTION = (
    "Handle ANY credential renewal, rotation, or reset — TLS/SSL certificates (certbot/nginx, "
    "ACM), AWS Secrets Manager secrets, and basic passwords/IdP accounts — including when the "
    "user named no target. Pass the user's message verbatim as the input. The specialist shows a "
    "credential picker and pauses for human approval; it never needs you to collect details first."
)
_ACCOUNT_TOOL_DESCRIPTION = (
    "Handle ANY account/principal request — lookups, access, onboarding, offboarding, IAM "
    "permission-gap detection with Terraform proposals, and account create/update/delete — for "
    "any principal type. Pass the user's message verbatim as the input. The specialist parses the "
    "principal and pauses for human approval on writes; it never needs you to collect details first."
)


def _credential_tool(model: BedrockModel, leaf_arn: str | None) -> AgentTool:
    """Return the credential specialist tool for remote or in-process execution."""
    if leaf_arn:

        @tool(name="credential_specialist")
        def credential_specialist(query: str) -> str:
            """Forward credential renewal/rotation/reset to the remote credential specialist runtime."""
            return invoke_agent_runtime_text(leaf_arn, query)

        return credential_specialist

    credential_agent = build_credential_agent(model)
    return credential_agent.as_tool(
        name="credential_specialist",
        description=_CREDENTIAL_TOOL_DESCRIPTION,
        preserve_context=True,
    )


def _account_tool(model: BedrockModel, account_leaf_arn: str | None) -> AgentTool:
    """Return the account manager tool for remote or in-process execution."""
    if account_leaf_arn:

        @tool(name="account_manager")
        def account_manager(query: str) -> str:
            """Forward account and principal requests to the remote account manager runtime."""
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

    In-process children (credential and account leaves) are wrapped with ``Agent.as_tool`` so
    Strands can propagate their human-in-the-loop interrupts to this supervisor and forward human
    resume responses back to the paused leaf. When a ``*_arn`` value is configured, the
    corresponding child is invoked as a remote runtime instead.
    """

    @tool
    def principal_lifecycle_auditor(principal: str) -> str:
        """Verify lifecycle coverage for one principal across account and credential leaves."""
        return verify_principal_lifecycle(principal)

    @tool
    def principal_type_coverage() -> str:
        """Report lifecycle coverage by principal type across the current hierarchy."""
        return verify_principal_types()

    return Agent(
        model=model,
        name="hr_supervisor",
        session_manager=session_manager,
        tools=[
            _credential_tool(model, leaf_arn),
            _account_tool(model, account_leaf_arn),
            principal_lifecycle_auditor,
            principal_type_coverage,
        ],
        system_prompt=(
            "You are an HR and identity routing supervisor. You do NOT ask the user for details "
            "and you do NOT answer certificate, credential, or account questions yourself — you "
            "route to specialists by calling a tool. Rules:\n"
            "- Certificate / TLS / SSL / renew / rotate / reset / replace / expiry / secret / "
            "password / rotation → immediately call credential_specialist with the user's message "
            "verbatim. This includes secret rotation and password resets even when the message "
            "also names a principal.\n"
            "- Account / principal / user / onboard / offboard / create / update / delete / "
            "inventory → immediately call account_manager with the user's message verbatim.\n"
            "- Principal lifecycle coverage → principal_lifecycle_auditor or "
            "principal_type_coverage.\n"
            "Call the specialist EVEN IF the user named no certificate, domain, secret, or "
            "principal — the specialist presents its own picker and pauses for human approval. "
            "NEVER ask the user for details. NEVER reply with a numbered list of questions. "
            "After the specialist returns, relay its result concisely."
        ),
    )
