from typing import Any

from strands import Agent, tool
from strands.models import BedrockModel
from strands.types.tools import AgentTool

from apps.utils.runtime_invocation import invoke_agent_runtime_text

from .supervisor_hr import build_hr_supervisor

_SUPERVISOR_TOOL_DESCRIPTION = (
    "Delegate HR, identity, and principal lifecycle work to the HR supervisor: certificates, "
    "credentials, user/service/application/workload/agent principals, and account "
    "create/update/delete. Pass the user's natural language request. Write actions pause for "
    "human approval (Slack) before anything is recorded."
)


def _supervisor_tool(model: BedrockModel, supervisor_arn: str | None) -> AgentTool:
    """Return the HR supervisor tool for the active deployment mode.

    If ``supervisor_arn`` is provided, calls the remote supervisor runtime.
    Otherwise, wraps the in-process HR supervisor agent as a tool.
    """
    if supervisor_arn:

        @tool(name="human_resource_supervisor")
        def human_resource_supervisor(query: str) -> str:
            """Forward HR and identity requests to the remote HR supervisor runtime."""
            return invoke_agent_runtime_text(supervisor_arn, query)

        return human_resource_supervisor

    hr_supervisor = build_hr_supervisor(model)
    return hr_supervisor.as_tool(
        name="human_resource_supervisor",
        description=_SUPERVISOR_TOOL_DESCRIPTION,
        preserve_context=True,
    )


def build_orchestrator(
    model: BedrockModel,
    supervisor_arn: str | None = None,
    session_manager: Any | None = None,
) -> Agent:
    """Build the root orchestrator.

    When the supervisor runs in-process, it is wrapped with ``Agent.as_tool`` so Strands can
    propagate nested human-in-the-loop interrupts from leaf agents to this top-level agent and
    forward the human response back down on resume. Only the orchestrator carries the
    ``session_manager`` (one durable session per conversation); nested agents remain in-process
    across resume cycles.
    """
    return Agent(
        model=model,
        name="orchestrator",
        session_manager=session_manager,
        tools=[_supervisor_tool(model, supervisor_arn)],
        system_prompt=(
            "You are a routing orchestrator. You do NOT answer questions yourself and you do NOT "
            "ask the user for details. For ANY request about HR, identity, users, "
            "service/application/workload/agent principals, credentials, certificates "
            "(status/renew/replace), or accounts (create/update/delete/offboard), you MUST "
            "immediately call the human_resource_supervisor tool, passing the user's message "
            "verbatim as the query. Do this even if the request names no specific target — the "
            "specialists collect the target and human approval themselves. NEVER ask the user "
            "clarifying questions and NEVER reply with a list of questions. After the tool "
            "returns, relay its result concisely."
        ),
    )
