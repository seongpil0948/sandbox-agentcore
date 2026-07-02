from __future__ import annotations

from apps.utils.prompt import (
    account_operation_from_prompt,
    account_operation_label,
    extract_domain,
    extract_known_principal,
    is_account_prompt,
    is_certificate_notice_prompt,
    is_certificate_prompt,
    principal_from_prompt,
)


def test_extract_domain_normalizes_domain() -> None:
    assert extract_domain("Check API.Example.COM certificate") == "api.example.com"


def test_certificate_prompt_helpers_support_korean_notice() -> None:
    prompt = "api.example.com 인증서가 7일 후 만료됩니다."

    assert is_certificate_prompt(prompt)
    assert is_certificate_notice_prompt(prompt)


def test_account_prompt_helpers_find_principal_and_operation() -> None:
    prompt = "deploy-bot 계정 삭제 요청"

    assert is_account_prompt(prompt)
    assert extract_known_principal(prompt) == "deploy-bot"
    assert principal_from_prompt("unknown 계정 생성 요청") == "deploy-bot"
    assert account_operation_from_prompt(prompt) == "delete"
    assert account_operation_label("delete") == "삭제"
