from __future__ import annotations

from apps.agents.leaf_account_manager import (
    find_stale_accounts,
    list_access,
    list_accounts,
    lookup_principal,
    validate_offboarding,
    validate_onboarding,
)
from apps.agents.leaf_cert import check_cert_expiry, list_cert_types
from apps.agents.principal_lifecycle import (
    verify_principal_lifecycle,
    verify_principal_types,
)
from apps.utils.prompt import (
    extract_domain,
    extract_known_principal,
    is_account_prompt,
    is_certificate_prompt,
)


def run_local_fallback(prompt: str) -> str:
    lower_prompt = prompt.lower()

    if _is_lifecycle_prompt(lower_prompt):
        return _run_lifecycle_fallback(lower_prompt)

    if is_certificate_prompt(prompt):
        return _run_certificate_fallback(prompt, lower_prompt)

    if is_account_prompt(prompt):
        return _run_account_fallback(lower_prompt)

    return (
        "AWS credentials are required for Bedrock-backed agent routing. "
        "Set AWS_PROFILE or AWS credential environment variables and try again."
    )


def _is_lifecycle_prompt(lower_prompt: str) -> bool:
    if "lifecycle" in lower_prompt:
        return True
    if "principal" in lower_prompt and (
        "type" in lower_prompt or "verify" in lower_prompt or "coverage" in lower_prompt
    ):
        return True
    return False


def _run_lifecycle_fallback(lower_prompt: str) -> str:
    if "type" in lower_prompt or "coverage" in lower_prompt or "all" in lower_prompt:
        return "Local offline lifecycle fallback:\n" + verify_principal_types()

    principal = extract_known_principal(lower_prompt)
    if not principal:
        return "Local offline lifecycle fallback:\n" + verify_principal_types()
    return "Local offline lifecycle fallback:\n" + verify_principal_lifecycle(principal)


def _run_certificate_fallback(prompt: str, lower_prompt: str) -> str:
    if "type" in lower_prompt or "support" in lower_prompt or "renewal" in lower_prompt:
        return "Local offline certificate fallback:\n" + list_cert_types()

    domain = extract_domain(prompt)
    if domain:
        return "Local offline certificate fallback: " + check_cert_expiry(domain)

    return "Local offline certificate fallback: provide a domain name, for example api.example.com."


def _run_account_fallback(lower_prompt: str) -> str:
    if "stale" in lower_prompt:
        return "Local offline account-manager fallback:\n" + find_stale_accounts()

    principal = _fallback_principal(lower_prompt)
    if not principal:
        return (
            "Local offline account-manager fallback: provide a principal, for example deploy-bot."
        )

    if "onboarding" in lower_prompt:
        return "Local offline account-manager fallback: " + validate_onboarding(principal)
    if "offboarding" in lower_prompt:
        return "Local offline account-manager fallback: " + validate_offboarding(principal)
    if "permission" in lower_prompt or "access" in lower_prompt:
        return "Local offline account-manager fallback: " + list_access(principal)
    if "account" in lower_prompt:
        return "Local offline account-manager fallback: " + list_accounts(principal)
    return "Local offline account-manager fallback: " + lookup_principal(principal)


def _fallback_principal(lower_prompt: str) -> str | None:
    principal = extract_known_principal(lower_prompt)
    if principal:
        return principal
    if "onboarding" in lower_prompt:
        return "new.engineer"
    if "offboarding" in lower_prompt:
        return "leaving.contractor"
    return None
