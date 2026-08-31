"""Typed provider errors.

Messages must never include API keys, tokens, or other secret values.
Incoming text is redacted before it is stored on the exception.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)Bearer\s+\S+"),
)


def redact_secrets(message: str) -> str:
    """Replace key-like substrings so they cannot leak through errors."""
    redacted = message
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class ProviderError(Exception):
    """Base provider failure. Messages never include secret values."""

    def __init__(self, message: str, *, provider_id: str | None = None) -> None:
        super().__init__(redact_secrets(message))
        self.provider_id = provider_id


class CapabilityError(ProviderError):
    """The selected model cannot serve the requested role."""

    def __init__(
        self,
        message: str,
        *,
        provider_id: str | None = None,
        role: str | None = None,
        model_id: str | None = None,
    ) -> None:
        super().__init__(message, provider_id=provider_id)
        self.role = role
        self.model_id = model_id


class ProviderAuthError(ProviderError):
    """Provider rejected credentials. The secret itself is never included."""


class ProviderOfflineError(ProviderError):
    """Provider or local runtime is unreachable."""

__all__ = [
    "CapabilityError",
    "ProviderAuthError",
    "ProviderError",
    "ProviderOfflineError",
    "redact_secrets",
]
