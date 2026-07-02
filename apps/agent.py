import logging
import uuid
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from botocore.exceptions import NoCredentialsError, ProfileNotFound
from strands.models import BedrockModel

from apps.runtime.hitl import STATUS_INTERRUPT, outcome_from_result
from apps.runtime.local_fallback import run_local_fallback
from apps.runtime.roles import MODEL_ID, build_agent, selected_agent_role
from apps.runtime.session import build_session_manager
from apps.slack.workflows import maybe_send_invocation_notification
from apps.utils.logging_config import AGENT_RUNTIME_LOG_FILE, configure_logging

app = BedrockAgentCoreApp()
logger = logging.getLogger(__name__)


def _should_notify_slack(payload: dict[str, Any]) -> bool:
    value = payload.get("notify_slack", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _describe_interrupt(reason: Any) -> str:
    detail = reason if isinstance(reason, dict) else {}
    title = str(detail.get("title") or "Human approval required")
    summary = str(detail.get("summary") or "")
    return (
        f"{title}\n{summary}\n\n"
        "Approval required — respond in Slack (Approve/Cancel) to continue this workflow."
    ).strip()


def run_prompt(payload: dict[str, Any]) -> str:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return "prompt is required"

    session_id = str(payload.get("session_id") or f"invocations-{uuid.uuid4().hex}")
    try:
        model = BedrockModel(model_id=MODEL_ID)
        agent = build_agent(
            selected_agent_role(), model, session_manager=build_session_manager(session_id)
        )
        response = agent(prompt)
    except (NoCredentialsError, ProfileNotFound):
        result = run_local_fallback(prompt)
    else:
        outcome = outcome_from_result(response)
        result = (
            _describe_interrupt(outcome.reason)
            if outcome.status == STATUS_INTERRUPT
            else outcome.text
        )

    if _should_notify_slack(payload):
        notification_text = maybe_send_invocation_notification(prompt)
        if notification_text:
            logger.info("Slack workflow notification triggered: %s", notification_text)
    return result


@app.entrypoint
def invoke(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    return run_prompt(payload)


if __name__ == "__main__":
    configure_logging("agent-runtime", AGENT_RUNTIME_LOG_FILE)
    # Connect to Slack via Socket Mode from within the runtime process (token-gated).
    from apps.slack.socket_mode import start_in_thread

    start_in_thread()
    app.run()
