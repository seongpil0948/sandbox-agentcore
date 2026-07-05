"""Centralized offline mock data for the sandbox.

Single source of truth for every resource type the hierarchy manages. Consolidates
mock registries previously split across agent and Slack modules.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

# Principal resource types (subtypes)
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
RESOURCE_TYPE_BASIC_CREDENTIAL = "basic_credential"

# Principal category layer: human principals vs service-account principals.
# application, workload, and agent_identity are service_account-category concepts —
# they share the same credential lifecycle management patterns.
PRINCIPAL_CATEGORY_HUMAN = "human"
PRINCIPAL_CATEGORY_SERVICE_ACCOUNT = "service_account"

PRINCIPAL_TYPE_TO_CATEGORY: dict[str, str] = {
    RESOURCE_TYPE_USER: PRINCIPAL_CATEGORY_HUMAN,
    RESOURCE_TYPE_CONTRACTOR: PRINCIPAL_CATEGORY_HUMAN,
    RESOURCE_TYPE_SERVICE_ACCOUNT: PRINCIPAL_CATEGORY_SERVICE_ACCOUNT,
    RESOURCE_TYPE_APPLICATION: PRINCIPAL_CATEGORY_SERVICE_ACCOUNT,
    RESOURCE_TYPE_WORKLOAD: PRINCIPAL_CATEGORY_SERVICE_ACCOUNT,
    RESOURCE_TYPE_AGENT_IDENTITY: PRINCIPAL_CATEGORY_SERVICE_ACCOUNT,
}

PRINCIPAL_TYPES = (
    RESOURCE_TYPE_USER,
    RESOURCE_TYPE_CONTRACTOR,
    RESOURCE_TYPE_SERVICE_ACCOUNT,
    RESOURCE_TYPE_APPLICATION,
    RESOURCE_TYPE_WORKLOAD,
    RESOURCE_TYPE_AGENT_IDENTITY,
)

# Renewal/rotation methods keyed by credential resource_type.
CREDENTIAL_RENEWAL_METHODS: dict[str, str] = {
    RESOURCE_TYPE_NGINX_CERTIFICATE: "certbot renew over SSH + nginx reload",
    RESOURCE_TYPE_ACM_CERTIFICATE: "ACM renew / re-import via ACM API",
    RESOURCE_TYPE_AWS_SECRET: "Secrets Manager rotation via API",
    RESOURCE_TYPE_BASIC_CREDENTIAL: "password reset via identity provider (IdP)",
}


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


@dataclass(frozen=True)
class BasicCredentialRecord:
    name: str
    resource_type: str
    principal: str
    idp: str
    status: str
    last_changed: str
    days_since_change: int
    managed_via: str
    management_endpoint: str


@dataclass(frozen=True)
class IamAccessRequirement:
    """One IAM access requirement for a principal, and whether it is currently satisfied.

    An unsatisfied requirement is an *IAM permission gap* the account leaf can detect and close
    by proposing Terraform (``terraform-aws-modules/iam/aws``). ``kind`` selects the submodule:

    - ``read_only_policy`` → ``iam-read-only-policy`` (uses ``allowed_services``)
    - ``assumable_role`` → ``iam-policy`` granting ``sts:AssumeRole`` on ``assume_role_arns``
    - ``policy`` → ``iam-policy`` with explicit ``actions`` / ``resources``
    """

    principal: str
    name: str
    kind: str
    description: str
    satisfied: bool
    actions: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    allowed_services: tuple[str, ...] = ()
    assume_role_arns: tuple[str, ...] = ()


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
        "credentials": ["basic=new.engineer-password", "mfa pending"],
        "risks": ["mfa-not-enrolled", "slack-account-missing"],
    },
    "leaving.contractor": {
        "principal": "leaving.contractor",
        "type": RESOURCE_TYPE_CONTRACTOR,
        "owner": "vendor-management",
        "status": "offboarding",
        "accounts": ["identity-center:leaving.contractor", "github:leaving-contractor"],
        "access": ["contractor-readonly", "legacy-repo-access"],
        "credentials": ["basic=leaving.contractor-password", "github-token age=124d"],
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
    "AWS Secrets Manager secret (rotation via API or Lambda)",
    "basic credential / password (reset via identity provider)",
]

BASIC_CREDENTIALS: dict[str, BasicCredentialRecord] = {
    "new.engineer-password": BasicCredentialRecord(
        name="new.engineer-password",
        resource_type=RESOURCE_TYPE_BASIC_CREDENTIAL,
        principal="new.engineer",
        idp="AWS IAM Identity Center",
        status="pending",
        last_changed="(never — onboarding)",
        days_since_change=-1,
        managed_via="identity_api",
        management_endpoint="https://identitycenter.amazonaws.com",
    ),
    "leaving.contractor-password": BasicCredentialRecord(
        name="leaving.contractor-password",
        resource_type=RESOURCE_TYPE_BASIC_CREDENTIAL,
        principal="leaving.contractor",
        idp="AWS IAM Identity Center",
        status="active",
        last_changed="2025-09-01",
        days_since_change=307,
        managed_via="identity_api",
        management_endpoint="https://identitycenter.amazonaws.com",
    ),
}


# Per-principal IAM access requirements. Unsatisfied entries are IAM permission gaps the account
# leaf detects during onboarding/access review and closes by proposing Terraform.
IAM_ACCESS_REQUIREMENTS: dict[str, list[IamAccessRequirement]] = {
    "new.engineer": [
        IamAccessRequirement(
            principal="new.engineer",
            name="base-engineering-readonly",
            kind="read_only_policy",
            description="Base engineering read-only access to core AWS services",
            satisfied=False,
            allowed_services=("ec2", "s3", "cloudwatch", "logs"),
        ),
        IamAccessRequirement(
            principal="new.engineer",
            name="dev-deployer-assume",
            kind="assumable_role",
            description="Assume the shared dev-deployer role in the staging account",
            satisfied=False,
            assume_role_arns=("arn:aws:iam::444455556666:role/dev-deployer",),
        ),
    ],
    "deploy-bot": [
        IamAccessRequirement(
            principal="deploy-bot",
            name="ecr-push",
            kind="policy",
            description="Push container images to ECR",
            satisfied=True,
            actions=(
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:PutImage",
                "ecr:UploadLayerPart",
            ),
            resources=("*",),
        ),
        IamAccessRequirement(
            principal="deploy-bot",
            name="eks-rollout",
            kind="policy",
            description="Describe and roll out EKS deployments",
            satisfied=False,
            actions=("eks:DescribeCluster", "eks:ListClusters"),
            resources=("*",),
        ),
    ],
}

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


def principal_category(principal_type: str) -> str:
    """Return the category (human or service_account) for a principal subtype."""
    return PRINCIPAL_TYPE_TO_CATEGORY.get(
        principal_type.strip().lower(), PRINCIPAL_CATEGORY_SERVICE_ACCOUNT
    )


def get_principal(principal: str) -> dict[str, Any] | None:
    return PRINCIPALS.get(_principal_key(principal))


def select_principals(principal_type: str | None = None) -> list[dict[str, Any]]:
    """Return principals filtered by category name or exact subtype.

    Passing ``"service_account"`` matches all SA-category subtypes (service_account,
    application, workload, agent_identity). Passing a specific subtype like
    ``"application"`` matches only that subtype. Pass ``None`` / ``""`` for all.
    """
    if not principal_type:
        return list(PRINCIPALS.values())
    key = principal_type.strip().lower()
    # Category-first match: "service_account" or "human" returns all principals of that category.
    if key in (PRINCIPAL_CATEGORY_HUMAN, PRINCIPAL_CATEGORY_SERVICE_ACCOUNT):
        return [info for info in PRINCIPALS.values() if principal_category(info["type"]) == key]
    # Exact subtype match.
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


def basic_credential_names(principal: str) -> list[str]:
    return _linked_resources(principal, "basic=")


def iam_access_requirements(principal: str) -> list[IamAccessRequirement]:
    """Return every IAM access requirement recorded for a principal."""
    return IAM_ACCESS_REQUIREMENTS.get(_principal_key(principal), [])


def iam_access_gaps(principal: str) -> list[IamAccessRequirement]:
    """Return the unsatisfied IAM access requirements (permission gaps) for a principal."""
    return [req for req in iam_access_requirements(principal) if not req.satisfied]


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


def list_basic_credentials() -> list[BasicCredentialRecord]:
    return list(BASIC_CREDENTIALS.values())


def get_basic_credential(name: str) -> BasicCredentialRecord | None:
    return BASIC_CREDENTIALS.get(name.strip().lower())


def search_basic_credentials(query: str) -> list[BasicCredentialRecord]:
    needle = query.strip().lower()
    if not needle:
        return list_basic_credentials()
    return [
        record
        for record in BASIC_CREDENTIALS.values()
        if needle in record.name.lower()
        or needle in record.principal.lower()
        or needle in record.status.lower()
    ]
