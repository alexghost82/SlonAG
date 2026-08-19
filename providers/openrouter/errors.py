"""OpenRouter-specific errors.

Shared ``providers.errors`` is owned by the contracts wave. Rate-limit
signaling stays inside this package so Wave 4 can back off without a
hidden model walk.
"""

from __future__ import annotations

from providers.errors import ProviderError

PROVIDER_ID = "openrouter"


class RateLimitError(ProviderError):
    """HTTP 429. Surfaces ``Retry-After``; callers must not switch models here."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        retry_after_header: str | None = None,
        status_code: int = 429,
    ) -> None:
        super().__init__(message, provider_id=PROVIDER_ID)
        self.retry_after = retry_after
        self.retry_after_header = retry_after_header
        self.status_code = status_code
