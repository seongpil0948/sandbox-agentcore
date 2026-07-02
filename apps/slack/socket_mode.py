from __future__ import annotations

import logging
import os
import threading
from threading import Event
from typing import Any, Protocol

from botocore.exceptions import NoCredentialsError, ProfileNotFound
from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.client import BaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from apps.runtime import hitl
from apps.runtime.local_fallback import run_local_fallback
from apps.runtime.session import slack_session_key
from apps.slack.events import (
    SlackMessagePrompt,
    SlackRequestLike,
    event_type_for_log,
    extract_interactive_action,
    extract_message_prompt,
    extract_options_request,
)
from apps.slack.workflows import (
    HITL_ACTION_IDS,
    build_action_response,
    build_agent_response_blocks,
    build_agent_response_text,
    build_hitl_options,
    build_interrupt_blocks,
)
from apps.utils.env import resolve_optional_env
from apps.utils.env import resolve_required_env as resolve_env

logger = logging.getLogger(__name__)

ENV_APP_TOKEN = "SLACK_APP_SOCKET_TOKEN"
ENV_BOT_TOKEN = "SLACK_BOT_USER_OAUTH_TOKEN"
ENV_INPROCESS = "SLACK_SOCKET_MODE_INPROCESS"


class _SlackWebClientLike(Protocol):
    def auth_test(self) -> Any: ...


class _SlackIdentityClientLike(Protocol):
    @property
    def web_client(self) -> _SlackWebClientLike: ...


def _update_interactive_message(
    client: BaseSocketModeClient,
    channel: str,
    message_ts: str,
    text: str,
    blocks: list[dict[str, Any]],
) -> None:
    client.web_client.chat_update(
        channel=channel,
        ts=message_ts,
        text=text,
        blocks=blocks,
    )


def _handle_interactive_action(client: BaseSocketModeClient, req: SlackRequestLike) -> bool:
    action = extract_interactive_action(req)
    if action is None:
        return False

    logger.info(
        "Handling Slack action: action_id=%s target=%s channel=%s",
        action.action_id,
        action.value.get("target", "unknown"),
        action.channel,
    )
    response = build_action_response(action.action_id, action.value)
    if response is None:
        logger.debug("Unsupported Slack action ignored: %s", action.action_id)
        return True

    text, blocks = response
    _update_interactive_message(client, action.channel, action.message_ts, text, blocks)
    logger.info("Slack action update sent: action_id=%s ts=%s", action.action_id, action.message_ts)
    return True


def _send_ack(
    client: BaseSocketModeClient,
    req: SocketModeRequest,
    payload: dict[str, Any] | None = None,
) -> None:
    client.send_socket_mode_response(
        SocketModeResponse(envelope_id=req.envelope_id, payload=payload)
    )


def _handle_agent_turn(client: BaseSocketModeClient, message: SlackMessagePrompt) -> None:
    """Route a Slack mention/DM through the in-process HITL engine and post the outcome."""
    session_id = slack_session_key(message.channel, message.thread_ts)
    try:
        outcome = hitl.start(session_id, message.prompt)
    except (NoCredentialsError, ProfileNotFound):
        text = run_local_fallback(message.prompt)
        client.web_client.chat_postMessage(
            channel=message.channel,
            thread_ts=message.thread_ts,
            text=build_agent_response_text(text),
            blocks=build_agent_response_blocks(text),
        )
        return
    _post_outcome(client, message.channel, message.thread_ts, session_id, outcome)


def _post_outcome(
    client: BaseSocketModeClient,
    channel: str,
    thread_ts: str,
    session_id: str,
    outcome: hitl.HitlOutcome,
) -> None:
    if outcome.status == hitl.STATUS_BUSY:
        logger.info("Skipping post; session already processing a turn: session=%s", session_id)
        return
    if outcome.status == hitl.STATUS_INTERRUPT:
        text, blocks = build_interrupt_blocks(outcome.reason, session_id, outcome.interrupt_id)
    else:
        text = build_agent_response_text(outcome.text)
        blocks = build_agent_response_blocks(outcome.text)
    client.web_client.chat_postMessage(
        channel=channel, thread_ts=thread_ts, text=text, blocks=blocks
    )


def _handle_hitl_action(client: BaseSocketModeClient, req: SlackRequestLike) -> bool:
    """Resume a paused agent session from a HITL approve/cancel/select control."""
    action = extract_interactive_action(req)
    if action is None or action.action_id not in HITL_ACTION_IDS:
        return False

    session_id = action.value.get("session", "")
    interrupt_id = action.value.get("interrupt_id", "")
    response = action.value.get("response", "cancel")
    logger.info(
        "Handling HITL decision: action_id=%s response=%s session=%s",
        action.action_id,
        response,
        session_id,
    )
    try:
        outcome = hitl.resume(session_id, interrupt_id, response)
    except (NoCredentialsError, ProfileNotFound):
        fallback = "AWS 자격 증명이 없어 승인 워크플로를 재개할 수 없습니다."
        _update_interactive_message(
            client,
            action.channel,
            action.message_ts,
            fallback,
            [{"type": "section", "text": {"type": "mrkdwn", "text": fallback}}],
        )
        return True

    if outcome.status == hitl.STATUS_BUSY:
        # A rapid duplicate/concurrent click: the in-flight turn owns the message update.
        logger.info(
            "Ignoring duplicate HITL action: session=%s interrupt=%s", session_id, interrupt_id
        )
        return True
    if outcome.status == hitl.STATUS_INTERRUPT:
        text, blocks = build_interrupt_blocks(outcome.reason, session_id, outcome.interrupt_id)
    else:
        text = build_agent_response_text(outcome.text)
        blocks = build_agent_response_blocks(outcome.text)
    _update_interactive_message(client, action.channel, action.message_ts, text, blocks)
    return True


def process_request(client: BaseSocketModeClient, req: SocketModeRequest) -> None:
    logger.info("Received Slack envelope type=%s", event_type_for_log(req))

    if req.type == "interactive":
        payload_type = (req.payload or {}).get("type")
        # external_select options for HITL selection interrupts: ack with the option list.
        if payload_type == "block_suggestion":
            options_req = extract_options_request(req)
            options = (
                build_hitl_options(options_req.action_id, options_req.value)
                if options_req is not None
                else []
            )
            _send_ack(client, req, {"options": options})
            return
        # Only agent-driven HITL controls (buttons + selects) and legacy notification buttons
        # are handled now; slash-command modals were removed for the interrupt-based agent flow.
        if payload_type != "block_actions":
            _send_ack(client, req)
            return
        _send_ack(client, req)
        try:
            if _handle_hitl_action(client, req):
                return
            _handle_interactive_action(client, req)
        except SlackApiError as exc:
            logger.error(
                "Slack interactive action failed (code=%s)",
                exc.response.get("error", "unknown"),
            )
        return

    # events_api and everything else: ack for each envelope to avoid retries, then process.
    _send_ack(client, req)
    message = extract_message_prompt(req)
    if message is None:
        logger.debug("Event ignored by filter")
        return

    try:
        _handle_agent_turn(client, message)
    except SlackApiError as exc:
        logger.error(
            "Slack API call failed (code=%s)",
            exc.response.get("error", "unknown"),
        )


def build_client() -> SocketModeClient:
    app_token = resolve_env(ENV_APP_TOKEN, "SLACK_APP_TOKEN")
    bot_token = resolve_env(ENV_BOT_TOKEN, "SLACK_BOT_TOKEN")

    return SocketModeClient(
        app_token=app_token,
        web_client=WebClient(token=bot_token),
    )


def verify_bot_identity(client: _SlackIdentityClientLike) -> None:
    try:
        auth = client.web_client.auth_test()
    except SlackApiError as exc:
        logger.error(
            "Slack auth_test failed; verify bot token/workspace install (code=%s)",
            exc.response.get("error", "unknown"),
        )
        raise

    logger.info(
        "Slack bot identity verified: team=%s user=%s bot_id=%s",
        auth.get("team", "unknown"),
        auth.get("user_id", "unknown"),
        auth.get("bot_id", "unknown"),
    )


def _inprocess_enabled() -> bool:
    return os.getenv(ENV_INPROCESS, "1").strip().lower() not in {"0", "false", "no", "off"}


def start_in_thread() -> threading.Thread | None:
    """Start the Slack Socket Mode listener as a daemon thread inside the agent process.

    No-op (returns ``None``) when disabled via ``SLACK_SOCKET_MODE_INPROCESS=0`` or when the
    Slack tokens are not configured, so offline/CI runs and token-less deploys stay quiet.
    """
    if not _inprocess_enabled():
        logger.info("In-process Slack Socket Mode disabled (%s=0)", ENV_INPROCESS)
        return None
    app_token = resolve_optional_env(ENV_APP_TOKEN, "SLACK_APP_TOKEN")
    bot_token = resolve_optional_env(ENV_BOT_TOKEN, "SLACK_BOT_TOKEN")
    if not (app_token and bot_token):
        logger.info("In-process Slack Socket Mode skipped: Slack tokens not configured")
        return None

    def _run() -> None:
        try:
            client = build_client()
            verify_bot_identity(client)
            client.socket_mode_request_listeners.append(process_request)
            client.connect()
            logger.info("In-process Slack Socket Mode connected; listening for events")
            Event().wait()
        except Exception as exc:  # noqa: BLE001 - keep the runtime alive if Slack fails
            logger.error("In-process Slack Socket Mode thread stopped: %s", exc)

    thread = threading.Thread(target=_run, name="slack-socket-mode", daemon=True)
    thread.start()
    logger.info("Slack Socket Mode thread started")
    return thread
