from __future__ import annotations

import os
from typing import Any, Final

from strands import Agent
from strands.models import BedrockModel

from apps.agents.leaf_account_manager import build_account_manager_agent
from apps.agents.leaf_cert import build_cert_agent
from apps.agents.orchestrator import build_orchestrator
from apps.agents.supervisor_hr import build_hr_supervisor

MODEL_ID: Final = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

AGENT_ROLE_ORCHESTRATOR: Final = "orchestrator"
AGENT_ROLE_SUPERVISOR: Final = "supervisor"
AGENT_ROLE_LEAF: Final = "leaf"
AGENT_ROLE_ACCOUNT_MANAGER: Final = "account-manager"

ACCOUNT_MANAGER_ALIASES: Final = frozenset({AGENT_ROLE_ACCOUNT_MANAGER, "account_manager"})


def selected_agent_role() -> str:
    return os.getenv("AGENT_ROLE", AGENT_ROLE_ORCHESTRATOR).strip().lower()


def build_agent(role: str, model: BedrockModel, session_manager: Any | None = None) -> Agent:
    normalized_role = role.strip().lower()

    if normalized_role == AGENT_ROLE_SUPERVISOR:
        return build_hr_supervisor(
            model,
            leaf_arn=os.getenv("LEAF_ARN"),
            account_leaf_arn=os.getenv("ACCOUNT_LEAF_ARN"),
            session_manager=session_manager,
        )
    if normalized_role == AGENT_ROLE_LEAF:
        return build_cert_agent(model, session_manager=session_manager)
    if normalized_role in ACCOUNT_MANAGER_ALIASES:
        return build_account_manager_agent(model, session_manager=session_manager)
    if normalized_role == AGENT_ROLE_ORCHESTRATOR:
        return build_orchestrator(
            model, supervisor_arn=os.getenv("SUPERVISOR_ARN"), session_manager=session_manager
        )

    raise ValueError(f"unsupported AGENT_ROLE: {role}")
