"""Headless NetworkPolicy: egress modes, proxy guard, secret-free journal."""

from acta.network.errors import (
    CODE_CLOUD_DENIED,
    CODE_INVALID_URL,
    CODE_OFFLINE,
    CODE_OK,
    CODE_PROXY_FORCED_EXTERNAL,
    CODE_TOOL_NOT_ALLOWED,
    CODE_UNSAFE_HOST,
    ERROR_CODES,
    NetworkDeniedError,
    network_message,
)
from acta.network.hosts import (
    domain_of,
    is_loopback_host,
    is_metadata_or_link_local_host,
    is_private_lan_host,
)
from acta.network.journal import NetworkJournal, redact_secrets, safe_domain
from acta.network.policy import NetworkPolicy
from acta.network.types import (
    CLOUD_PROVIDER_IDS,
    PRIVACY_FULLY_LOCAL,
    NetworkDecision,
    NetworkJournalEntry,
    NetworkMode,
)

__all__ = [
    "CLOUD_PROVIDER_IDS",
    "CODE_CLOUD_DENIED",
    "CODE_INVALID_URL",
    "CODE_OFFLINE",
    "CODE_OK",
    "CODE_PROXY_FORCED_EXTERNAL",
    "CODE_TOOL_NOT_ALLOWED",
    "CODE_UNSAFE_HOST",
    "ERROR_CODES",
    "PRIVACY_FULLY_LOCAL",
    "NetworkDecision",
    "NetworkDeniedError",
    "NetworkJournal",
    "NetworkJournalEntry",
    "NetworkMode",
    "NetworkPolicy",
    "domain_of",
    "is_loopback_host",
    "is_metadata_or_link_local_host",
    "is_private_lan_host",
    "network_message",
    "redact_secrets",
    "safe_domain",
]
