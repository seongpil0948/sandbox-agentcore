from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from slack_sdk.errors import SlackApiError
from slack_sdk.web import WebClient

from apps.agents.leaf_account_manager import (
    list_access,
    list_accounts,
    lookup_principal,
    validate_offboarding,
    validate_onboarding,
)
from apps.agents.leaf_cert import check_cert_expiry
from apps.mock_data import search_certificates
from apps.slack.blockkit import button as _button
from apps.slack.blockkit import mrkdwn as _mrkdwn
from apps.slack.blockkit import option as _option
from apps.slack.blockkit import plain_text as _plain_text
from apps.utils.env import resolve_optional_env
from apps.utils.prompt import (
    account_operation_from_prompt,
    account_operation_label,
    extract_domain,
    is_account_prompt,
    is_certificate_notice_prompt,
    principal_from_prompt,
)

logger = logging.getLogger(__name__)

ENV_BOT_TOKEN = "SLACK_BOT_USER_OAUTH_TOKEN"
ENV_NOTIFICATION_CHANNEL = "SLACK_NOTIFICATION_CHANNEL_ID"

ACTION_CERT_RENEW = "cert_renew_request"
ACTION_CERT_DETAILS = "cert_details"
ACTION_ACCOUNT_EXECUTE = "account_execute_request"
ACTION_ACCOUNT_DETAILS = "account_details"
ACTION_WORKFLOW_IGNORE = "workflow_ignore"
ACTION_WORKFLOW_CANCEL = "workflow_cancel"
ACTION_WORKFLOW_RESUME = "workflow_resume"

# Agent-driven HITL (Strands interrupt) approve/cancel/select controls.
ACTION_HITL_APPROVE = "hitl_approve"
ACTION_HITL_CANCEL = "hitl_cancel"
ACTION_HITL_SELECT = "hitl_select"
HITL_ACTION_IDS = frozenset({ACTION_HITL_APPROVE, ACTION_HITL_CANCEL, ACTION_HITL_SELECT})

# external_select options served for HITL selection interrupts (block_suggestion listener).
HITL_OPTIONS_ACTION_IDS = frozenset({ACTION_HITL_SELECT})

INTERRUPT_ACTION_IDS = frozenset(
    {
        ACTION_CERT_RENEW,
        ACTION_CERT_DETAILS,
        ACTION_ACCOUNT_EXECUTE,
        ACTION_ACCOUNT_DETAILS,
    }
)
DETAIL_ACTION_IDS = frozenset({ACTION_CERT_DETAILS, ACTION_ACCOUNT_DETAILS})

DAY_PATTERN = re.compile(r"(\d+)\s*(?:일|day|days)", re.IGNORECASE)
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
MARKDOWN_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")


class SlackWebClientLike(Protocol):
    def chat_postMessage(self, **kwargs: Any) -> Any: ...

    def chat_update(self, **kwargs: Any) -> Any: ...


def build_web_client() -> WebClient | None:
    token = resolve_optional_env(ENV_BOT_TOKEN, "SLACK_BOT_TOKEN")
    if not token:
        return None
    return WebClient(token=token)


def notification_channel() -> str | None:
    return resolve_optional_env(
        ENV_NOTIFICATION_CHANNEL, "SLACK_ALERT_CHANNEL_ID", "SLACK_CHANNEL_ID"
    )


def _chunk_text(text: str, size: int = 2800) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return ["No details available."]
    return [stripped[index : index + size] for index in range(0, len(stripped), size)]


def _strip_markdown_for_fallback(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading_match = MARKDOWN_HEADING_PATTERN.match(line)
        if heading_match:
            line = heading_match.group(1)
        line = MARKDOWN_BOLD_PATTERN.sub(r"\1", line)
        line = MARKDOWN_INLINE_CODE_PATTERN.sub(r"\1", line)
        lines.append(line)
    return "\n".join(lines) or "Agent response"


def _slackify_mrkdwn(line: str) -> str:
    line = MARKDOWN_BOLD_PATTERN.sub(r"*\1*", line.strip())
    line = MARKDOWN_INLINE_CODE_PATTERN.sub(r"`\1`", line)
    if line.startswith("- "):
        line = "• " + line[2:]
    return line


def _append_section_blocks(blocks: list[dict[str, Any]], lines: list[str]) -> None:
    if not lines:
        return
    section_text = "\n".join(lines)
    for chunk in _chunk_text(section_text):
        blocks.append({"type": "section", "text": _mrkdwn(chunk)})


def build_agent_response_text(answer: str) -> str:
    return _strip_markdown_for_fallback(answer)


def build_agent_response_blocks(answer: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    pending_lines: list[str] = []
    header_added = False

    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading_match = MARKDOWN_HEADING_PATTERN.match(line)
        if heading_match:
            _append_section_blocks(blocks, pending_lines)
            pending_lines = []
            heading = heading_match.group(1).strip()
            if not header_added:
                blocks.append({"type": "header", "text": _plain_text(heading[:150])})
                header_added = True
            else:
                blocks.append({"type": "section", "text": _mrkdwn(f"*{heading}*")})
            continue

        pending_lines.append(_slackify_mrkdwn(line))

    if not header_added:
        blocks.append({"type": "header", "text": _plain_text("Agent response")})
    _append_section_blocks(blocks, pending_lines)

    if len(blocks) == 1:
        blocks.append({"type": "section", "text": _mrkdwn("No details available.")})
    return blocks


def _cert_status_from_prompt(prompt: str) -> tuple[str, str]:
    domain = extract_domain(prompt) or "api.example.com"
    day_match = DAY_PATTERN.search(prompt)
    if day_match:
        return domain, day_match.group(1)

    status = check_cert_expiry(domain)
    status_match = re.search(r"days_remaining=(-?\d+)", status)
    return domain, status_match.group(1) if status_match else "unknown"


def _account_notice_from_prompt(prompt: str) -> tuple[str, str] | None:
    operation = account_operation_from_prompt(prompt)
    if not operation:
        return None
    if not is_account_prompt(prompt):
        return None
    return operation, principal_from_prompt(prompt)


def build_certificate_notice_blocks(
    domain: str, days_remaining: str
) -> tuple[str, list[dict[str, Any]]]:
    value = {"kind": "cert", "target": domain, "days": days_remaining}
    text = f"{domain} 인증서가 {days_remaining}일 후 만료됩니다."
    blocks = [
        {"type": "header", "text": _plain_text("Certificate expiration notice")},
        {
            "type": "section",
            "text": _mrkdwn(f"*{domain}* 인증서가 *{days_remaining}일 후* 만료됩니다."),
        },
        {
            "type": "actions",
            "elements": [
                _button("갱신 실행", ACTION_CERT_RENEW, value, "primary"),
                _button("무시", ACTION_WORKFLOW_IGNORE, value),
                _button("상세 보기", ACTION_CERT_DETAILS, value),
            ],
        },
    ]
    return text, blocks


def build_account_notice_blocks(operation: str, principal: str) -> tuple[str, list[dict[str, Any]]]:
    operation_label = account_operation_label(operation)
    value = {"kind": "account", "operation": operation, "target": principal}
    text = f"{principal} 계정 {operation_label} 요청이 접수되었습니다."
    blocks = [
        {"type": "header", "text": _plain_text("Account workflow request")},
        {
            "type": "section",
            "text": _mrkdwn(f"*{principal}* 계정 *{operation_label}* 요청이 접수되었습니다."),
        },
        {
            "type": "actions",
            "elements": [
                _button(f"{operation_label} 실행", ACTION_ACCOUNT_EXECUTE, value, "primary"),
                _button("무시", ACTION_WORKFLOW_IGNORE, value),
                _button("상세 보기", ACTION_ACCOUNT_DETAILS, value),
            ],
        },
    ]
    return text, blocks


def maybe_send_invocation_notification(
    prompt: str, client: SlackWebClientLike | None = None
) -> str | None:
    channel = notification_channel()
    if not channel:
        logger.info(
            "Slack notification skipped: missing %s (aliases: SLACK_ALERT_CHANNEL_ID, "
            "SLACK_CHANNEL_ID)",
            ENV_NOTIFICATION_CHANNEL,
        )
        return None

    slack_client = client or build_web_client()
    if slack_client is None:
        logger.info(
            "Slack notification skipped: missing %s (alias: SLACK_BOT_TOKEN)",
            ENV_BOT_TOKEN,
        )
        return None

    if is_certificate_notice_prompt(prompt):
        domain, days_remaining = _cert_status_from_prompt(prompt)
        text, blocks = build_certificate_notice_blocks(domain, days_remaining)
    else:
        account_notice = _account_notice_from_prompt(prompt)
        if account_notice is None:
            logger.debug("Slack notification skipped: prompt did not match a workflow notice")
            return None
        operation, principal = account_notice
        text, blocks = build_account_notice_blocks(operation, principal)

    try:
        slack_client.chat_postMessage(channel=channel, text=text, blocks=blocks)
    except SlackApiError as exc:
        logger.error("Slack notification failed (code=%s)", exc.response.get("error", "unknown"))
        return None
    logger.info("Slack notification posted: channel=%s text=%s", channel, text)
    return text


def build_interrupt_blocks(
    reason: Any, session_id: str, interrupt_id: str
) -> tuple[str, list[dict[str, Any]]]:
    """Render a Strands interrupt (raised by a leaf write-tool) as a Block Kit prompt.

    ``reason`` is the JSON-serializable payload the tool passed to ``tool_context.interrupt``.
    Dispatch on ``reason["kind"]`` so each interrupt type gets a purpose-built UI; button/select
    payloads carry only session + interrupt id + response (non-secret).
    """
    detail = reason if isinstance(reason, dict) else {}
    kind = str(detail.get("kind", ""))
    if kind == "cert_selection":
        return _cert_selection_blocks(detail, session_id, interrupt_id)
    if kind == "cert_renewal":
        return _cert_renewal_blocks(detail, session_id, interrupt_id)
    if kind in {"account_create", "account_update", "account_delete"}:
        return _account_write_blocks(kind, detail, session_id, interrupt_id)
    return _generic_interrupt_blocks(reason, detail, session_id, interrupt_id)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _approve_cancel_actions(session_id: str, interrupt_id: str) -> dict[str, Any]:
    base = {"session": session_id, "interrupt_id": interrupt_id}
    return {
        "type": "actions",
        "elements": [
            _button("승인", ACTION_HITL_APPROVE, {**base, "response": "approve"}, "primary"),
            _button("취소", ACTION_HITL_CANCEL, {**base, "response": "cancel"}, "danger"),
        ],
    }


def _sandbox_context() -> dict[str, Any]:
    return {
        "type": "context",
        "elements": [
            _mrkdwn("Sandbox: 승인 시 변경 의도만 기록되며 실제 인프라 변경은 수행되지 않습니다.")
        ],
    }


def _cert_selection_blocks(
    detail: dict[str, Any], session_id: str, interrupt_id: str
) -> tuple[str, list[dict[str, Any]]]:
    prompt = str(detail.get("prompt") or "갱신할 인증서를 선택하세요.")
    options = _as_list(detail.get("options"))
    select_options: list[dict[str, Any]] = []
    for entry in options:
        if isinstance(entry, dict) and entry.get("value"):
            select_options.append(
                _option(str(entry.get("label") or entry["value"]), str(entry["value"]))
            )
    text = "인증서 선택 필요"
    accessory: dict[str, Any] = {
        "type": "external_select",
        "action_id": ACTION_HITL_SELECT,
        "min_query_length": 0,
        "placeholder": _plain_text("도메인으로 인증서 검색"),
    }
    blocks = [
        {"type": "header", "text": _plain_text("인증서 갱신 — 대상 선택")},
        {
            "type": "section",
            "block_id": _hitl_block_id(session_id, interrupt_id),
            "text": _mrkdwn(prompt),
            "accessory": accessory,
        },
    ]
    if select_options:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    _mrkdwn("후보: " + ", ".join(f"`{opt['value']}`" for opt in select_options))
                ],
            }
        )
    return text, blocks


def _cert_renewal_blocks(
    detail: dict[str, Any], session_id: str, interrupt_id: str
) -> tuple[str, list[dict[str, Any]]]:
    record = _as_dict(detail.get("record"))
    domain = str(record.get("domain") or detail.get("domain") or "unknown")
    title = str(detail.get("title") or f"인증서 갱신 승인 — {domain}")
    lines = [
        f"*도메인:* `{domain}`",
        f"*상태:* {record.get('status', 'n/a')}  ·  *만료:* {record.get('expiration', 'n/a')} "
        f"({record.get('days_remaining', 'n/a')}일)",
        f"*인증서 유형:* {record.get('cert_type', 'n/a')}",
        f"*ARN:* `{record.get('arn', 'n/a')}`",
        f"*계정 / 리전:* {record.get('account', 'n/a')} / {record.get('region', 'n/a')}",
        f"*갱신 가능:* {'예' if record.get('renewal_eligible') else '아니오'}"
        f"  ·  *갱신 상태:* {record.get('renewal_status', 'n/a')}",
        f"*관리 방식:* {record.get('managed_via', 'n/a')} (`{record.get('management_endpoint', 'n/a')}`)",
    ]
    blocks = [
        {"type": "header", "text": _plain_text(title[:150])},
        {"type": "section", "text": _mrkdwn("\n".join(lines))},
        _approve_cancel_actions(session_id, interrupt_id),
        _sandbox_context(),
    ]
    return f"{title} — 승인 필요", blocks


def _account_write_blocks(
    kind: str, detail: dict[str, Any], session_id: str, interrupt_id: str
) -> tuple[str, list[dict[str, Any]]]:
    record = _as_dict(detail.get("record"))
    principal = str(record.get("principal") or detail.get("principal") or "unknown")
    labels = {
        "account_create": "계정 생성 승인",
        "account_update": "계정 변경 승인",
        "account_delete": "계정 종료 승인",
    }
    title = str(detail.get("title") or f"{labels.get(kind, '계정 작업 승인')} — {principal}")
    lines = [
        f"*Principal:* `{principal}`",
        f"*유형:* {record.get('type', 'n/a')}  ·  *소유자:* {record.get('owner', 'n/a')}",
        f"*현재 상태:* {record.get('status', 'n/a')}",
    ]
    if record.get("change"):
        lines.append(f"*변경 내용:* {record['change']}")
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": _plain_text(title[:150])},
        {"type": "section", "text": _mrkdwn("\n".join(lines))},
    ]
    linked = _as_dict(detail.get("linked_resources"))
    certs = linked.get("certificates") or []
    secrets = linked.get("secrets") or []
    if kind == "account_delete" and (certs or secrets):
        checklist = [
            "*오프보딩 체크리스트 — 회수 대상 리소스:*",
            *(f"• 인증서 `{domain}`" for domain in certs),
            *(f"• 시크릿 `{name}`" for name in secrets),
        ]
        blocks.append({"type": "section", "text": _mrkdwn("\n".join(checklist))})
    blocks.append(_approve_cancel_actions(session_id, interrupt_id))
    blocks.append(_sandbox_context())
    return f"{title} — 승인 필요", blocks


def _generic_interrupt_blocks(
    reason: Any, detail: dict[str, Any], session_id: str, interrupt_id: str
) -> tuple[str, list[dict[str, Any]]]:
    title = str(detail.get("title") or "승인 필요")
    summary = str(
        detail.get("summary") or (reason if isinstance(reason, str) else "승인이 필요합니다.")
    )
    text = f"{title} — 승인 필요"
    blocks = [
        {"type": "header", "text": _plain_text(title[:150])},
        {"type": "section", "text": _mrkdwn(summary)},
        _approve_cancel_actions(session_id, interrupt_id),
        _sandbox_context(),
    ]
    return text, blocks


def _hitl_block_id(session_id: str, interrupt_id: str) -> str:
    """Encode HITL resume context into a select block_id (external_select carries no value)."""
    return json.dumps({"session": session_id, "interrupt_id": interrupt_id}, separators=(",", ":"))


def build_hitl_options(action_id: str, query: str) -> list[dict[str, Any]]:
    """Serve external_select options for HITL selection interrupts (block_suggestion listener)."""
    if action_id != ACTION_HITL_SELECT:
        return []
    return [
        _option(f"{record.domain} ({record.status}, {record.days_remaining}d)", record.domain)
        for record in search_certificates(query)
    ]


def parse_action_value(raw_value: str | None) -> dict[str, str]:
    if not raw_value:
        return {}
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(key): str(value) for key, value in decoded.items()}


def build_action_response(
    action_id: str, value: dict[str, str]
) -> tuple[str, list[dict[str, Any]]] | None:
    if action_id in INTERRUPT_ACTION_IDS:
        return build_interrupted_detail_blocks(action_id, value)
    if action_id == ACTION_WORKFLOW_IGNORE:
        return build_ignored_blocks(value)
    if action_id == ACTION_WORKFLOW_CANCEL:
        return build_cancelled_blocks(value)
    if action_id == ACTION_WORKFLOW_RESUME:
        return build_resumed_blocks(value)
    return None


def build_interrupted_detail_blocks(
    action_id: str, value: dict[str, str]
) -> tuple[str, list[dict[str, Any]]]:
    kind = value.get("kind", "")
    target = value.get("target", "unknown")
    if kind == "cert":
        details = check_cert_expiry(target)
        title = f"{target} 인증서 갱신 승인 필요"
        description = (
            "HITL interrupt 상태입니다. 아래 상세 정보를 확인한 뒤 승인 후 재개하거나 취소하세요."
        )
        resume_value = {**value, "resume": "renew"}
    elif kind == "account":
        operation = value.get("operation", "update")
        details = _account_details(target, operation)
        operation_label = account_operation_label(operation)
        title = f"{target} 계정 {operation_label} 승인 필요"
        description = "HITL interrupt 상태입니다. 계정 상세와 위험 항목을 확인한 뒤 승인 후 재개하거나 취소하세요."
        resume_value = {**value, "resume": operation}
    else:
        details = "Unsupported Slack action payload."
        title = "승인 필요"
        description = "HITL interrupt 상태입니다."
        resume_value = value

    text = f"{title} - 상세 조회 후 승인 대기"
    blocks = [
        {"type": "header", "text": _plain_text(title[:150])},
        {"type": "section", "text": _mrkdwn(description)},
        {"type": "section", "text": _mrkdwn(f"```{details}```")},
        {
            "type": "actions",
            "elements": [
                _button("승인 후 재개", ACTION_WORKFLOW_RESUME, resume_value, "primary"),
                _button("취소", ACTION_WORKFLOW_CANCEL, value, "danger"),
            ],
        },
    ]
    if action_id in DETAIL_ACTION_IDS:
        blocks.insert(
            2,
            {
                "type": "context",
                "elements": [_mrkdwn("상세 조회만 수행되었으며 변경은 아직 실행되지 않았습니다.")],
            },
        )
    return text, blocks


def build_ignored_blocks(value: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    target = value.get("target", "unknown")
    text = f"{target} 요청이 무시되었습니다."
    return text, _workflow_status_blocks("Workflow ignored", f"*{target}* 요청이 무시되었습니다.")


def build_cancelled_blocks(value: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    target = value.get("target", "unknown")
    text = f"{target} 요청이 취소되었습니다."
    return text, _workflow_status_blocks(
        "Workflow cancelled",
        f"*{target}* 요청이 취소되었습니다. 변경은 수행되지 않았습니다.",
    )


def build_resumed_blocks(value: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    kind = value.get("kind", "")
    target = value.get("target", "unknown")
    if kind == "cert":
        text = f"{target} 인증서 갱신 workflow가 승인되어 재개되었습니다."
        summary = (
            f"*{target}* 인증서 갱신 workflow가 승인되어 재개되었습니다.\n"
            "Sandbox에서는 실제 갱신 대신 Terraform PR 생성 단계로 기록합니다."
        )
    elif kind == "account":
        operation = value.get("operation", "update")
        operation_label = account_operation_label(operation)
        text = f"{target} 계정 {operation_label} workflow가 승인되어 재개되었습니다."
        summary = (
            f"*{target}* 계정 *{operation_label}* workflow가 승인되어 재개되었습니다.\n"
            "Sandbox에서는 실제 계정 변경 대신 승인된 변경 요청으로 기록합니다."
        )
    else:
        text = f"{target} workflow가 재개되었습니다."
        summary = f"*{target}* workflow가 재개되었습니다."

    return text, _workflow_status_blocks("Workflow resumed", summary)


def _workflow_status_blocks(header: str, summary: str) -> list[dict[str, Any]]:
    return [
        {"type": "header", "text": _plain_text(header)},
        {"type": "section", "text": _mrkdwn(summary)},
    ]


def _account_details(principal: str, operation: str) -> str:
    if operation == "create":
        return validate_onboarding(principal)
    if operation == "delete":
        return validate_offboarding(principal)
    return "\n".join(
        [
            lookup_principal(principal),
            list_accounts(principal),
            list_access(principal),
        ]
    )
