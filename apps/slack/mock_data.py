"""Compatibility shim for legacy imports.

New code should import from ``apps.mock_data`` directly.
"""

from apps.mock_data import (
    AccountRecord,
    CertificateRecord,
    create_account_request_id,
    get_certificate,
    get_org_account,
    list_certificates,
    list_org_accounts,
    search_certificates,
    search_org_accounts,
)

__all__ = [
    "CertificateRecord",
    "AccountRecord",
    "list_certificates",
    "get_certificate",
    "search_certificates",
    "list_org_accounts",
    "get_org_account",
    "search_org_accounts",
    "create_account_request_id",
]
