from __future__ import annotations

import re

DOMAIN_PATTERN = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{1,62}\b",
    re.IGNORECASE,
)

KNOWN_PRINCIPALS = (
    "deploy-bot",
    "new.engineer",
    "leaving.contractor",
    "payments-api",
    "batch-runner",
    "sandbox-orchestrator",
)
ACCOUNT_OPERATION_LABELS = {"create": "생성", "update": "수정", "delete": "삭제"}

ACCOUNT_KEYWORDS = (
    "계정",
    "account",
    "access",
    "permission",
    "principal",
    "onboarding",
    "offboarding",
    "service account",
    "stale",
    "deploy-bot",
)
CERTIFICATE_KEYWORDS = ("인증서", "cert", "certificate")
CERTIFICATE_NOTICE_KEYWORDS = ("만료", "expire", "renew", "갱신")

ACCOUNT_OPERATION_KEYWORDS = {
    "create": ("생성", "create", "onboard", "onboarding"),
    "update": ("수정", "변경", "update", "modify"),
    "delete": ("삭제", "비활성", "delete", "disable", "offboard"),
}


def extract_domain(prompt: str, default: str | None = None) -> str | None:
    match = DOMAIN_PATTERN.search(prompt)
    if match:
        return match.group(0).lower()
    return default


def extract_known_principal(prompt: str) -> str | None:
    lower_prompt = prompt.lower()
    for principal in KNOWN_PRINCIPALS:
        if principal in lower_prompt:
            return principal
    return None


def principal_from_prompt(prompt: str, default: str = "deploy-bot") -> str:
    return extract_known_principal(prompt) or default


def is_account_prompt(prompt: str) -> bool:
    return _contains_any(prompt, ACCOUNT_KEYWORDS)


def is_certificate_prompt(prompt: str) -> bool:
    return _contains_any(prompt, CERTIFICATE_KEYWORDS)


def is_certificate_notice_prompt(prompt: str) -> bool:
    return is_certificate_prompt(prompt) and _contains_any(prompt, CERTIFICATE_NOTICE_KEYWORDS)


def account_operation_from_prompt(prompt: str) -> str | None:
    lower_prompt = prompt.lower()
    for operation, keywords in ACCOUNT_OPERATION_KEYWORDS.items():
        if any(keyword in lower_prompt for keyword in keywords):
            return operation
    return None


def account_operation_label(operation: str, default: str = "수정") -> str:
    return ACCOUNT_OPERATION_LABELS.get(operation, default)


def _contains_any(prompt: str, keywords: tuple[str, ...]) -> bool:
    lower_prompt = prompt.lower()
    return any(keyword in lower_prompt for keyword in keywords)
