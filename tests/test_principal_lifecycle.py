from __future__ import annotations

from apps.agents.leaf_account_manager import PRINCIPAL_TYPES, certificate_domains, select_principals
from apps.agents.principal_lifecycle import (
    MANAGED_PRINCIPAL_TYPES,
    principal_lifecycle_status,
    verify_principal_lifecycle,
    verify_principal_types,
)


def test_certificate_domains_extracts_cert_credentials() -> None:
    assert certificate_domains("deploy-bot") == ["nginx.internal"]
    assert certificate_domains("payments-api") == ["api.example.com"]
    assert certificate_domains("new.engineer") == []


def test_principal_types_cover_requested_forms() -> None:
    for principal_type in ("user", "service_account", "application", "workload"):
        assert principal_type in PRINCIPAL_TYPES
        assert select_principals(principal_type), f"no principal of type {principal_type}"


def test_lifecycle_status_service_account_tracks_expiring_cert() -> None:
    status = principal_lifecycle_status("deploy-bot")
    assert status is not None
    assert status.type == "service_account"
    assert status.fully_manageable
    assert any("expiring_soon" in cert for cert in status.certificate_statuses)


def test_lifecycle_status_application_uses_valid_cert() -> None:
    status = principal_lifecycle_status("payments-api")
    assert status is not None
    assert status.type == "application"
    assert status.fully_manageable
    assert any("status=valid" in cert for cert in status.certificate_statuses)


def test_lifecycle_status_workload_detects_expired_cert() -> None:
    status = principal_lifecycle_status("batch-runner")
    assert status is not None
    assert status.type == "workload"
    # Resolvable == manageable, even though the certificate itself is expired.
    assert status.fully_manageable
    assert any("expired" in cert for cert in status.certificate_statuses)


def test_lifecycle_status_user_without_cert_is_manageable() -> None:
    status = principal_lifecycle_status("new.engineer")
    assert status is not None
    assert status.type == "user"
    assert status.certificate_statuses == []
    assert status.fully_manageable


def test_lifecycle_status_tracks_aws_secret_lifecycle() -> None:
    status = principal_lifecycle_status("payments-api")
    assert status is not None
    assert status.secret_manageable
    assert any("type=aws_secret" in secret for secret in status.secret_statuses)


def test_verify_principal_lifecycle_reports_unknown_principal() -> None:
    assert "not_registered" in verify_principal_lifecycle("ghost-principal")


def test_verify_principal_types_confirms_full_coverage() -> None:
    report = verify_principal_types()
    for principal_type in MANAGED_PRINCIPAL_TYPES:
        assert f"type={principal_type}" in report
    assert "hierarchy_can_manage_all_types=yes" in report
