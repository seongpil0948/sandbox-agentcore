"""Session-manager factory for durable conversation + interrupt (HITL) state.

The HITL engine persists agent state so a Slack approval that arrives seconds or minutes
after the agent paused can resume the *same* conversation and interrupt.

Backend selection (never calls AWS at import time so smoke tests stay offline):

- ``AGENTCORE_MEMORY_ID`` + an AWS region configured -> ``AgentCoreMemorySessionManager``.
- Otherwise (local dev, CI, no creds) -> Strands ``FileSessionManager`` on local disk.

Only the top-level agent per session should receive a session manager; AgentCore Memory
supports one agent per session.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from apps.utils.env import resolve_optional_env

logger = logging.getLogger(__name__)

ENV_MEMORY_ID = "AGENTCORE_MEMORY_ID"
ENV_SESSION_DIR = "SANDBOX_AGENTCORE_SESSION_DIR"
DEFAULT_SESSION_DIR = "logs/sessions"


def slack_session_key(channel: str, thread_ts: str) -> str:
    """Stable, filesystem-safe session id for a Slack channel + thread."""
    raw = f"slack-{channel}-{thread_ts}"
    return "".join(char if char.isalnum() or char == "-" else "-" for char in raw)


def _session_storage_dir() -> str:
    return os.getenv(ENV_SESSION_DIR, DEFAULT_SESSION_DIR)


def build_session_manager(session_id: str, actor_id: str | None = None) -> Any | None:
    """Return a Strands session manager for durable conversation + interrupt state.

    Prefers AgentCore Memory when configured, else the local ``FileSessionManager``.
    Returns ``None`` only if no backend can be constructed (agent then runs stateless).
    """
    memory_id = resolve_optional_env(ENV_MEMORY_ID)
    region = resolve_optional_env("AWS_REGION", "AWS_DEFAULT_REGION")
    if memory_id and region:
        manager = _try_build_agentcore_memory(memory_id, region, session_id, actor_id or session_id)
        if manager is not None:
            logger.info("Using AgentCore Memory session manager: session_id=%s", session_id)
            return manager
        logger.warning("AgentCore Memory unavailable; falling back to file session storage")
    return _build_file_session_manager(session_id)


def _try_build_agentcore_memory(
    memory_id: str, region: str, session_id: str, actor_id: str
) -> Any | None:
    try:
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import (
            AgentCoreMemorySessionManager,
        )
    except ImportError as exc:
        logger.warning("AgentCore Memory integration not importable: %s", exc)
        return None

    try:
        config = AgentCoreMemoryConfig(
            memory_id=memory_id, session_id=session_id, actor_id=actor_id
        )
        return AgentCoreMemorySessionManager(config, region_name=region)
    except Exception as exc:  # noqa: BLE001 - degrade to file storage on any init failure
        logger.warning("AgentCore Memory session manager init failed: %s", exc)
        return None


def _build_file_session_manager(session_id: str) -> Any | None:
    try:
        from strands.session.file_session_manager import FileSessionManager
    except ImportError as exc:
        logger.warning("FileSessionManager not importable; running stateless: %s", exc)
        return None

    storage_dir = _session_storage_dir()
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    logger.info("Using file session storage: dir=%s session_id=%s", storage_dir, session_id)
    return FileSessionManager(session_id=session_id, storage_dir=storage_dir)
