"""Cross-leaf principal lifecycle verification.

Answers the question: *can the agent hierarchy manage each principal's account and
credential/certificate lifecycle?* People, service accounts, applications, workloads, and
agent identities are all modeled as principals. This module coordinates the account-manager
leaf (account + credential inventory) and the cert leaf (certificate status) deterministically
and offline, so the coverage can be smoke-tested without AWS credentials.

"Manageable" means the hierarchy can enumerate and track the lifecycle (not that the resource
is currently healthy) — an expired certificate is still manageable because the cert leaf can
detect it and drive a HITL renewal.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.agents.leaf_account_manager import (
    certificate_domains,
    get_principal,
    secret_names,
    select_principals,
)
from apps.agents.leaf_cert import check_cert_expiry
from apps.mock_data import get_secret

# Principal types the sandbox explicitly claims to manage as first-class principals.
MANAGED_PRINCIPAL_TYPES = ("user", "service_account", "application", "workload")

_CERT_NOT_FOUND = "No certificate record found"


@dataclass(frozen=True)
class LifecycleStatus:
    principal: str
    type: str
    account_manageable: bool
    credential_manageable: bool
    certificate_manageable: bool
    secret_manageable: bool
    certificate_statuses: list[str]
    secret_statuses: list[str]

    @property
    def fully_manageable(self) -> bool:
        return (
            self.account_manageable
            and self.credential_manageable
            and self.certificate_manageable
            and self.secret_manageable
        )


def principal_lifecycle_status(principal: str) -> LifecycleStatus | None:
    """Assess account + credential/certificate lifecycle coverage for one principal."""
    info = get_principal(principal)
    if info is None:
        return None

    certificate_statuses = [check_cert_expiry(domain) for domain in certificate_domains(principal)]
    certificate_manageable = all(_CERT_NOT_FOUND not in status for status in certificate_statuses)

    secret_statuses = [_secret_status(name) for name in secret_names(principal)]
    secret_manageable = all("secret_status=not_found" not in status for status in secret_statuses)

    return LifecycleStatus(
        principal=info["principal"],
        type=info["type"],
        account_manageable=bool(info["accounts"]),
        credential_manageable=bool(info["credentials"]),
        certificate_manageable=certificate_manageable,
        secret_manageable=secret_manageable,
        certificate_statuses=certificate_statuses,
        secret_statuses=secret_statuses,
    )


def verify_principal_lifecycle(principal: str) -> str:
    """Return a per-principal lifecycle coverage report across account and cert leaves."""
    status = principal_lifecycle_status(principal)
    if status is None:
        return f"principal={principal} lifecycle=unknown reason=not_registered"

    lines = [
        f"principal={status.principal} type={status.type}",
        f"account_lifecycle={_flag(status.account_manageable)}",
        f"credential_lifecycle={_flag(status.credential_manageable)}",
        f"certificate_lifecycle={_flag(status.certificate_manageable)}",
        f"secret_lifecycle={_flag(status.secret_manageable)}",
    ]
    lines.extend(f"  cert: {cert_status}" for cert_status in status.certificate_statuses)
    lines.extend(f"  secret: {secret_status}" for secret_status in status.secret_statuses)
    lines.append(f"result={'MANAGEABLE' if status.fully_manageable else 'NEEDS_ATTENTION'}")
    return "\n".join(lines)


def verify_principal_types() -> str:
    """Report whether the hierarchy can manage account + credential lifecycle per principal type."""
    lines = ["principal-type lifecycle coverage:"]
    all_ok = True

    for principal_type in MANAGED_PRINCIPAL_TYPES:
        principals = select_principals(principal_type)
        if not principals:
            lines.append(f"type={principal_type} coverage=missing")
            all_ok = False
            continue

        statuses = [principal_lifecycle_status(info["principal"]) for info in principals]
        manageable = all(status is not None and status.fully_manageable for status in statuses)
        examples = ", ".join(info["principal"] for info in principals)
        lines.append(
            f"type={principal_type} principals=[{examples}] "
            f"lifecycle={'manageable' if manageable else 'needs_attention'}"
        )
        all_ok = all_ok and manageable

    lines.append(f"hierarchy_can_manage_all_types={'yes' if all_ok else 'no'}")
    return "\n".join(lines)


def _flag(manageable: bool) -> str:
    return "manageable" if manageable else "gap"


def _secret_status(name: str) -> str:
    secret = get_secret(name)
    if secret is None:
        return f"name={name} secret_status=not_found"
    return (
        f"name={secret.name} type={secret.resource_type} status={secret.status} "
        f"rotation_enabled={secret.rotation_enabled} days_since_rotation={secret.days_since_rotation}"
    )
