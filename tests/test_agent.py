from botocore.exceptions import NoCredentialsError
import pytest

from apps import agent as agent_module
from apps.agent import invoke
from apps.agents.leaf_account_manager import (
    find_stale_accounts,
    list_access,
    list_accounts,
    list_credentials,
    list_principals,
    lookup_principal,
    validate_offboarding,
    validate_onboarding,
)
from apps.agents.leaf_cert import check_cert_expiry, list_cert_types


@pytest.fixture(autouse=True)
def _disable_slack_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_BOT_USER_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_NOTIFICATION_CHANNEL_ID", raising=False)
    monkeypatch.delenv("SLACK_ALERT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)


# ── payload boundary ─────────────────────────────────────────────────────────


def test_invoke_requires_object_payload() -> None:
    assert invoke("bad") == "payload must be a JSON object"


def test_invoke_empty_prompt() -> None:
    assert invoke({}) == "prompt is required"


def test_run_prompt_falls_back_to_local_cert_stub_without_credentials(monkeypatch) -> None:
    def raise_no_credentials(*args, **kwargs):
        raise NoCredentialsError()

    monkeypatch.setattr(agent_module, "BedrockModel", raise_no_credentials)

    result = invoke({"prompt": "Check the certificate status for api.example.com"})

    assert "Local offline certificate fallback" in result
    assert "domain=api.example.com" in result
    assert "days_remaining=42" in result


def test_run_prompt_falls_back_to_local_account_stub_without_credentials(monkeypatch) -> None:
    def raise_no_credentials(*args, **kwargs):
        raise NoCredentialsError()

    monkeypatch.setattr(agent_module, "BedrockModel", raise_no_credentials)

    result = invoke({"prompt": "Which accounts does deploy-bot use?"})

    assert "Local offline account-manager fallback" in result
    assert "principal=deploy-bot" in result
    assert "github:deploy-bot" in result


def test_run_prompt_verifies_principal_lifecycle_without_credentials(monkeypatch) -> None:
    def raise_no_credentials(*args, **kwargs):
        raise NoCredentialsError()

    monkeypatch.setattr(agent_module, "BedrockModel", raise_no_credentials)

    result = invoke({"prompt": "verify lifecycle for payments-api"})

    assert "Local offline lifecycle fallback" in result
    assert "type=application" in result
    assert "result=MANAGEABLE" in result


def test_run_prompt_verifies_principal_type_coverage_without_credentials(monkeypatch) -> None:
    def raise_no_credentials(*args, **kwargs):
        raise NoCredentialsError()

    monkeypatch.setattr(agent_module, "BedrockModel", raise_no_credentials)

    result = invoke({"prompt": "verify principal type lifecycle coverage"})

    assert "hierarchy_can_manage_all_types=yes" in result


def test_run_prompt_triggers_slack_notification_for_direct_invocation(monkeypatch) -> None:
    def raise_no_credentials(*args, **kwargs):
        raise NoCredentialsError()

    notifications: list[str] = []

    monkeypatch.setattr(agent_module, "BedrockModel", raise_no_credentials)
    monkeypatch.setattr(
        agent_module,
        "maybe_send_invocation_notification",
        lambda prompt: notifications.append(prompt),
    )

    invoke({"prompt": "api.example.com 인증서가 7일 후 만료됩니다."})

    assert notifications == ["api.example.com 인증서가 7일 후 만료됩니다."]


def test_run_prompt_skips_slack_notification_when_disabled(monkeypatch) -> None:
    def raise_no_credentials(*args, **kwargs):
        raise NoCredentialsError()

    notifications: list[str] = []

    monkeypatch.setattr(agent_module, "BedrockModel", raise_no_credentials)
    monkeypatch.setattr(
        agent_module,
        "maybe_send_invocation_notification",
        lambda prompt: notifications.append(prompt),
    )

    invoke({"prompt": "api.example.com 인증서가 7일 후 만료됩니다.", "notify_slack": False})

    assert notifications == []


# ── leaf cert tools (offline deterministic) ───────────────────────────────────


def test_check_cert_expiry_valid() -> None:
    result = check_cert_expiry("api.example.com")
    assert "valid" in result
    assert "days_remaining=42" in result


def test_check_cert_expiry_expiring_soon() -> None:
    result = check_cert_expiry("nginx.internal")
    assert "expiring_soon" in result
    assert "days_remaining=7" in result


def test_check_cert_expiry_expired() -> None:
    result = check_cert_expiry("old.example.com")
    assert "expired" in result
    assert "days_remaining=-3" in result


def test_check_cert_expiry_unknown_domain() -> None:
    result = check_cert_expiry("unknown.example.com")
    assert "No certificate record found" in result


def test_list_cert_types_contains_known_types() -> None:
    result = list_cert_types()
    assert "certbot-dns-route53" in result
    assert "ACM" in result


# ── leaf account-manager tools (offline deterministic) ───────────────────────


def test_lookup_principal_service_account() -> None:
    result = lookup_principal("deploy-bot")
    assert "principal=deploy-bot" in result
    assert "type=service_account" in result
    assert "owner=platform-team" in result


def test_list_accounts_for_principal() -> None:
    result = list_accounts("deploy-bot")
    assert "github:deploy-bot" in result
    assert "aws:iam/deploy-bot" in result


def test_list_access_for_principal() -> None:
    result = list_access("deploy-bot")
    assert "repo-deploy" in result
    assert "eks-rollout" in result


def test_validate_onboarding() -> None:
    result = validate_onboarding("new.engineer")
    assert "onboarding_status=blocked" in result
    assert "mfa-not-enrolled" in result


def test_validate_offboarding() -> None:
    result = validate_offboarding("leaving.contractor")
    assert "offboarding_status=action_required" in result
    assert "legacy-repo-access" in result


def test_find_stale_accounts_lists_risks() -> None:
    result = find_stale_accounts()
    assert "deploy-bot" in result
    assert "leaving.contractor" in result


def test_lookup_principal_application() -> None:
    result = lookup_principal("payments-api")
    assert "type=application" in result
    assert "certificate=api.example.com" in result


def test_lookup_principal_workload() -> None:
    result = lookup_principal("batch-runner")
    assert "type=workload" in result
    assert "certificate=old.example.com" in result


def test_list_credentials_reports_certificate_material() -> None:
    result = list_credentials("deploy-bot")
    assert "principal=deploy-bot" in result
    assert "certificate=nginx.internal" in result


def test_list_principals_filters_by_type() -> None:
    result = list_principals("application")
    assert "payments-api" in result
    assert "deploy-bot" not in result


def test_list_principals_lists_all_types_when_unfiltered() -> None:
    result = list_principals()
    for principal in ("deploy-bot", "new.engineer", "payments-api", "batch-runner"):
        assert principal in result
