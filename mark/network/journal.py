"""In-memory network activity journal with secret redaction."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence

from mark.network.types import NetworkJournalEntry

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)=([^\s&]+)"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-+=/]+"),
    re.compile(r"(?i)\bsk-[a-z0-9]{8,}\b"),
    re.compile(r"(?i)\bAIza[0-9A-Za-z\-_]{10,}\b"),
)


def redact_secrets(value: str) -> str:
    """Remove credential-looking substrings from a journal field."""
    if not value:
        return value
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def safe_domain(domain: str) -> str:
    """Keep only a hostname-like domain; drop query/userinfo fragments."""
    cleaned = domain.strip()
    if not cleaned:
        return ""
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    cleaned = cleaned.split("/", 1)[0]
    cleaned = cleaned.split("?", 1)[0]
    cleaned = cleaned.split("#", 1)[0]
    if "@" in cleaned:
        cleaned = cleaned.rsplit("@", 1)[-1]
    # Strip brackets / port for IPv6 literals carefully.
    if cleaned.startswith("["):
        end = cleaned.find("]")
        if end != -1:
            cleaned = cleaned[1:end]
    elif cleaned.count(":") == 1:
        cleaned = cleaned.split(":", 1)[0]
    return redact_secrets(cleaned.rstrip(".").lower())


class NetworkJournal:
    """Append-only activity log for NetworkPolicy decisions."""

    def __init__(self, *, max_entries: int = 500) -> None:
        self._max_entries = max(1, max_entries)
        self._entries: list[NetworkJournalEntry] = []

    def record(
        self,
        *,
        tool: str | None,
        domain: str,
        reason: str,
        allowed: bool,
        when: float | None = None,
    ) -> NetworkJournalEntry:
        entry = NetworkJournalEntry(
            tool=tool,
            domain=safe_domain(domain),
            time=time.time() if when is None else when,
            reason=redact_secrets(reason),
            allowed=allowed,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            overflow = len(self._entries) - self._max_entries
            del self._entries[:overflow]
        return entry

    def activity(self) -> list[NetworkJournalEntry]:
        """Return a snapshot of all retained journal entries."""
        return list(self._entries)

    def recent(self, limit: int = 50) -> list[NetworkJournalEntry]:
        """Return the newest entries, oldest-first within the window."""
        if limit <= 0:
            return []
        return list(self._entries[-limit:])

    def clear(self) -> None:
        self._entries.clear()


def journal_has_secret(entries: Sequence[NetworkJournalEntry], secret: str) -> bool:
    """Test helper: True if ``secret`` appears in any journal field."""
    if not secret:
        return False
    for entry in entries:
        haystacks = (
            entry.tool or "",
            entry.domain,
            entry.reason,
            str(entry.time),
            str(entry.allowed),
        )
        if any(secret in part for part in haystacks):
            return True
    return False


__all__ = [
    "NetworkJournal",
    "journal_has_secret",
    "redact_secrets",
    "safe_domain",
]
