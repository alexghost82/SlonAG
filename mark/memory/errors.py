"""Structured memory-store error codes.

Messages must never include API keys, tokens, passwords, or card numbers.
"""

from __future__ import annotations

from i18n import t
from providers.errors import redact_secrets

CODE_OK = "ok"
CODE_SECRET_REJECTED = "secret_rejected"
CODE_UNKNOWN_PROPOSAL = "unknown_proposal"
CODE_UNKNOWN_TYPE = "unknown_type"
CODE_INVALID_RECORD = "invalid_record"
CODE_INVALID_MIGRATION = "invalid_migration"
CODE_NOT_FOUND = "not_found"

ERROR_CODES = frozenset(
    {
        CODE_OK,
        CODE_SECRET_REJECTED,
        CODE_UNKNOWN_PROPOSAL,
        CODE_UNKNOWN_TYPE,
        CODE_INVALID_RECORD,
        CODE_INVALID_MIGRATION,
        CODE_NOT_FOUND,
    }
)

_MESSAGES = {
    CODE_OK: "Memory store is ready.",
    CODE_SECRET_REJECTED: "Memory refused a secret-like value.",
    CODE_UNKNOWN_PROPOSAL: "Proposal id is not pending.",
    CODE_UNKNOWN_TYPE: "Unknown memory record type.",
    CODE_INVALID_RECORD: "Memory record is missing required fields.",
    CODE_INVALID_MIGRATION: "Legacy memory payload is not a mapping.",
    CODE_NOT_FOUND: "Memory record was not found.",
}

_UNKNOWN = "Memory store error."


def memory_message(code: str) -> str:
    """Return a secret-free explanation for a structured memory error code."""
    return _MESSAGES.get(code, _UNKNOWN)


class MemoryStoreError(Exception):
    """Caller or policy error. Messages are redacted before storage."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        text = message if message is not None else memory_message(code)
        super().__init__(redact_secrets(text))


class MemoryPolicyError(MemoryStoreError):
    """A proposed or updated value matched a blocked secret category."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_SECRET_REJECTED, message)


__all__ = [
    "CODE_INVALID_MIGRATION",
    "CODE_INVALID_RECORD",
    "CODE_NOT_FOUND",
    "CODE_OK",
    "CODE_SECRET_REJECTED",
    "CODE_UNKNOWN_PROPOSAL",
    "CODE_UNKNOWN_TYPE",
    "ERROR_CODES",
    "MemoryPolicyError",
    "MemoryStoreError",
    "memory_message",
]
