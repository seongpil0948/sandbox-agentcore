"""Centralized offline mock data for the sandbox.

Single source of truth for every resource type the hierarchy manages. Consolidates
mock registries previously split across agent and Slack modules.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

# Principal resource types
RESOURCE_TYPE_USER = "user"
RESOURCE_TYPE_CONTRACTOR = "contractor"
RESOURCE_TYPE_SERVICE_ACCOUNT = "service_account"
RESOURCE_TYPE_APPLICATION = "application"
RESOURCE_TYPE_WORKLOAD = "workload"
RESOURCE_TYPE_AGENT_IDENTITY = "agent_identity"

# Credential / infrastructure resource types
RESOURCE_TYPE_NGINX_CERTIFICATE = "nginx_certificate"
RESOURCE_TYPE_ACM_CERTIFICATE = "acm_certificate"
RESOURCE_TYPE_AWS_SECRET = "aws_secret"
RESOURCE_TYPE_AWS_ACCOUNT = "aws_account"

PRINCIPAL_TYPES = (
    RESOURCE_TYPE_USER,
    RESOURCE_TYPE_CONTRACTOR,
    RESOURCE_TYPE_SERVICE_ACCOUNT,
    RESOURCE_TYPE_APPLICATION,
    RESOURCE_TYPE_WORKLOAD,
    RESOURCE_TYPE_AGENT_IDENTITY,
)


@dataclass(frozen=True)
class CertificateRecord:
    domain: str
    resource_type: str
    cert_type: str
    arn: str
    account: str
    region: str
    status: str
    expiration: str
    days_remaining: int
    renewal_eligible: bool
    renewal_status: str
    in_use: bool
    managed_via: str
    management_endpoint: str


@dataclass(frozen=True)
class SecretRecord:
    name: str
    resource_type: str
    arn: str
    account: str
    region: str
    status: str
    rotation_enabled: bool
    last_rotated: str
    days_since_rotation: int
    managed_via: str
    management_endpoint: str


@dataclass(frozen=True)
class AccountRecord:
    account_id: str
    resource_type: str
    name: str
    email: str
    status: str
    arn: str
    organizational_unit: str
    joined_method: str


PRINCIPALS: dict[str, dict[str, Any]] = {
    "deploy-bot": {
        "principal": "deploy-bot",
        "type": RESOURCE_TYPE_SERVICE_ACCOUNT,
        "owner": "platform-team",
        "status": "active",
        "accounts": ["github:deploy-bot", "aws:iam/deploy-bot", "slack:deploy-bot-alerts"],
        "access": ["repo-deploy", "ecr-push", "eks-rollout"],
        "credentials": [
            "iam-access-key age=82d",
            "certificate=nginx.internal",
            "secret=deploy-bot-signing-key",
        ],
        "risks": ["owner-confirmation-required", "key-age-unknown"],
    },
    "new.engineer": {
        "principal": "new.engineer",
        "type": RESOURCE_TYPE_USER,
        "owner": "engineering-manager",
        "status": "onboarding",
        "accounts": ["identity-center:new.engineer", "github:new-engineer"],
        "access": ["base-engineering", "vpn-required"],
        "credentials": ["password pending", "mfa pending"],
        "risks": ["mfa-not-enrolled", "slack-account-missing"],
    },
    "leaving.contractor": {
        "principal": "leaving.contractor",
        "type": RESOURCE_TYPE_CONTRACTOR,
        "owner": "vendor-management",
        "status": "offboarding",
        "accounts": ["identity-center:leaving.contractor", "github:leaving-contractor"],
        "access": ["contractor-readonly", "legacy-repo-access"],
        "credentials": ["password active", "github-token age=124d"],
        "risks": ["legacy-repo-access", "github-token-active"],
    },
    "payments-api": {
        "principal": "payments-api",
        "type": RESOURCE_TYPE_APPLICATION,
        "owner": "payments-team",
        "status": "active",
        "accounts": ["aws:iam/payments-api", "ecr:payments-api", "cognito:payments-pool"],
        "access": ["secrets-read", "db-connect", "kms-decrypt"],
        "credentials": [
            "certificate=api.example.com",
            "iam-access-key age=15d",
            "secret=payments-api-db",
        ],
        "risks": [],
    },
    "batch-runner": {
        "principal": "batch-runner",
        "type": RESOURCE_TYPE_WORKLOAD,
        "owner": "data-platform",
        "status": "active",
        "accounts": ["aws:iam/batch-runner", "k8s:sa/batch-runner"],
        "access": ["s3-read", "batch-submit"],
        "credentials": ["certificate=old.example.com", "iam-role=batch-runner-role"],
        "risks": ["certificate-expired"],
    },
    "sandbox-orchestrator": {
        "principal": "sandbox-orchestrator",
        "type": RESOURCE_TYPE_AGENT_IDENTITY,
        "owner": "ai-platform",
        "status": "active",
        "accounts": ["agentcore:runtime/orchestrator", "aws:iam/agentcore-orchestrator"],
        "access": ["invoke-supervisor", "bedrock-invoke"],
        "credentials": ["agentcore-workload-token age=1d", "iam-role=agentcore-exec"],
        "risks": [],
    },
}


CERTIFICATE_TYPE_DESCRIPTIONS = [
    "certbot-dns-route53 (auto-renew via DNS challenge)",
    "ACM public cert (auto-renew managed by AWS)",
    "ACM imported cert (no auto-renew; must re-import or manually renew on expiry)",
]

CERTIFICATES: dict[str, CertificateRecord] = {
    "api.example.com": CertificateRecord(
        domain="api.example.com",
        resource_type=RESOURCE_TYPE_ACM_CERTIFICATE,
        cert_type="ACM public cert",
        arn="arn:aws:acm:us-east-1:111122223333:certificate/1a2b3c4d-api",
        account="111122223333",
        region="us-east-1",
        status="valid",
        expiration="2026-08-12",
        days_remaining=42,
        renewal_eligible=True,
        renewal_status="auto_managed",
        in_use=True,
        managed_via="acm_api",
        management_endpoint="https://acm.us-east-1.amazonaws.com",
    ),
    "nginx.internal": CertificateRecord(
        domain="nginx.internal",
        resource_type=RESOURCE_TYPE_NGINX_CERTIFICATE,
        cert_type="certbot-dns-route53",
        arn="arn:aws:acm:us-east-1:111122223333:certificate/1a2b3c4d-nginx",
        account="111122223333",
        region="us-east-1",
        status="expiring_soon",
        expiration="2026-07-08",
        days_remaining=7,
        renewal_eligible=True,
        renewal_status="eligible",
        in_use=True,
        managed_via="ssh",
        management_endpoint="ssh://deploy@nginx.internal",
    ),
    "payments.example.com": CertificateRecord(
        domain="payments.example.com",
        resource_type=RESOURCE_TYPE_NGINX_CERTIFICATE,
        cert_type="certbot-dns-route53",
        arn="arn:aws:acm:us-east-1:111122223333:certificate/1a2b3c4d-pay",
        account="111122223333",
        region="us-east-1",
        status="expiring_soon",
        expiration="2026-07-22",
        days_remaining=21,
        renewal_eligible=True,
        renewal_status="eligible",
        in_use=True,
        managed_via="ssh",
        management_endpoint="ssh://deploy@payments.example.com",
    ),
    "old.example.com": CertificateRecord(
        domain="old.example.com",
        resource_type=RESOURCE_TYPE_ACM_CERTIFICATE,
        cert_type="ACM imported cert",
        arn="arn:aws:acm:us-west-2:111122223333:certificate/1a2b3c4d-old",
        account="111122223333",
        region="us-west-2",
        status="expired",
        expiration="2026-06-28",
        days_remaining=-3,
        renewal_eligible=False,
        renewal_status="manual_reimport_required",
        in_use=False,
        managed_via="acm_api",
        management_endpoint="https://acm.us-west-2.amazonaws.com",
    ),
}


SECRETS: dict[str, SecretRecord] = {
    "deploy-bot-signing-key": SecretRecord(
        name="deploy-bot-signing-key",
        resource_type=RESOURCE_TYPE_AWS_SECRET,
        arn="arn:aws:secretsmanager:us-east-1:111122223333:secret:deploy-bot-signing-key",
        account="111122223333",
        region="us-east-1",
        status="rotation_due",
        rotation_enabled=False,
        last_rotated="2025-12-03",
        days_since_rotation=210,
        managed_via="api",
        management_endpoint="https://secretsmanager.us-east-1.amazonaws.com",
    ),
    "payments-api-db": SecretRecord(
        name="payments-api-db",
        resource_type=RESOURCE_TYPE_AWS_SECRET,
        arn="arn:aws:secretsmanager:us-east-1:111122223333:secret:payments-api-db",
        account="111122223333",
        region="us-east-1",
        status="active",
        rotation_enabled=True,
        last_rotated="2026-06-24",
        days_since_rotation=7,
        managed_via="api",
        management_endpoint="https://secretsmanager.us-east-1.amazonaws.com",
    ),
    "rds-prod-password": SecretRecord(
        name="rds-prod-password",
        resource_type=RESOURCE_TYPE_AWS_SECRET,
        arn="arn:aws:secretsmanager:us-east-1:111122223333:secret:rds-prod-password",
        account="111122223333",
        region="us-east-1",
        status="active",
        rotation_enabled=True,
        last_rotated="2026-06-16",
        days_since_rotation=15,
        managed_via="api",
        management_endpoint="https://secretsmanager.us-east-1.amazonaws.com",
    ),
}


ACCOUNTS: dict[str, AccountRecord] = {
    "111122223333": AccountRecord(
        account_id="111122223333",
        resource_type=RESOURCE_TYPE_AWS_ACCOUNT,
        name="sandbox-prod",
        email="aws-prod@example.com",
        status="ACTIVE",
        arn="arn:aws:organizations::999999999999:account/o-sandbox/111122223333",
        organizational_unit="Production",
        joined_method="CREATED",
    ),
    "444455556666": AccountRecord(
        account_id="444455556666",
        resource_type=RESOURCE_TYPE_AWS_ACCOUNT,
        name="sandbox-staging",
        email="aws-staging@example.com",
        status="ACTIVE",
        arn="arn:aws:organizations::999999999999:account/o-sandbox/444455556666",
        organizational_unit="NonProd",
        joined_method="CREATED",
    ),
    "777788889999": AccountRecord(
        account_id="777788889999",
        resource_type=RESOURCE_TYPE_AWS_ACCOUNT,
        name="sandbox-legacy",
        email="aws-legacy@example.com",
        status="SUSPENDED",
        arn="arn:aws:organizations::999999999999:account/o-sandbox/777788889999",
        organizational_unit="Suspended",
        joined_method="INVITED",
    ),
}


def _principal_key(principal: str) -> str:
    return principal.strip().lower()


def get_principal(principal: str) -> dict[str, Any] | None:
    return PRINCIPALS.get(_principal_key(principal))


def select_principals(principal_type: str | None = None) -> list[dict[str, Any]]:
    if not principal_type:
        return list(PRINCIPALS.values())
    key = principal_type.strip().lower()
    return [info for info in PRINCIPALS.values() if info["type"] == key]


def _linked_resources(principal: str, prefix: str) -> list[str]:
    info = get_principal(principal)
    if not info:
        return []
    return [
        credential.split("=", 1)[1].strip()
        for credential in info["credentials"]
        if credential.startswith(prefix)
    ]


def certificate_domains(principal: str) -> list[str]:
    return _linked_resources(principal, "certificate=")


def secret_names(principal: str) -> list[str]:
    return _linked_resources(principal, "secret=")


def list_certificates() -> list[CertificateRecord]:
    return list(CERTIFICATES.values())


def get_certificate(domain: str) -> CertificateRecord | None:
    return CERTIFICATES.get(domain.strip().lower())


def search_certificates(query: str) -> list[CertificateRecord]:
    needle = query.strip().lower()
    if not needle:
        return list_certificates()
    return [
        record
        for record in CERTIFICATES.values()
        if needle in record.domain.lower() or needle in record.status.lower()
    ]


def list_secrets() -> list[SecretRecord]:
    return list(SECRETS.values())


def get_secret(name: str) -> SecretRecord | None:
    return SECRETS.get(name.strip().lower())


def search_secrets(query: str) -> list[SecretRecord]:
    needle = query.strip().lower()
    if not needle:
        return list_secrets()
    return [
        record
        for record in SECRETS.values()
        if needle in record.name.lower() or needle in record.status.lower()
    ]


def list_org_accounts() -> list[AccountRecord]:
    return list(ACCOUNTS.values())


def get_org_account(account_id: str) -> AccountRecord | None:
    return ACCOUNTS.get(account_id.strip())


def search_org_accounts(query: str) -> list[AccountRecord]:
    needle = query.strip().lower()
    if not needle:
        return list_org_accounts()
    return [
        record
        for record in ACCOUNTS.values()
        if needle in record.account_id
        or needle in record.name.lower()
        or needle in record.email.lower()
        or needle in record.status.lower()
    ]


def create_account_request_id(name: str, email: str) -> str:
    """Deterministic AWS-Organizations-style CreateAccountStatus id (offline stub)."""
    digest = hashlib.sha256(f"{name.strip().lower()}|{email.strip().lower()}".encode()).hexdigest()
    return f"car-{digest[:32]}"
