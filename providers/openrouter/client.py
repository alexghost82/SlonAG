"""OpenAI-compatible OpenRouter HTTP client.

Transport is ``requests`` and is injectable so unit tests never touch the
network. One request uses exactly one model: HTTP 429 is an error.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Any

from providers.errors import ProviderAuthError, ProviderError, ProviderOfflineError
from providers.openrouter.errors import PROVIDER_ID, RateLimitError

# Injectable transport; tests pass fakes that are not ``requests.Response``.
RequestFn = Callable[..., Any]

DEFAULT_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT = 60.0


def _requests() -> Any:
    import requests

    return requests


def models_url_from_api_url(api_url: str) -> str:
    """Derive ``/models`` from a chat-completions URL or a versioned base."""
    trimmed = api_url.rstrip("/")
    suffix = "/chat/completions"
    if trimmed.endswith(suffix):
        return f"{trimmed[: -len(suffix)]}/models"
    return f"{trimmed}/models"


def parse_retry_after_header(
    headers: Mapping[str, str],
) -> tuple[float | None, str | None]:
    """Return ``(seconds, raw)`` from ``Retry-After`` when present."""
    raw: str | None = None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            raw = str(value).strip()
            break
    if not raw:
        return None, None
    try:
        return float(raw), raw
    except ValueError:
        return None, raw


class OpenRouterClient:
    """Thin ``requests`` wrapper. Does not walk a fallback model list."""

    def __init__(
        self,
        api_key: str,
        *,
        api_url: str = DEFAULT_API_URL,
        request: RequestFn | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ProviderAuthError("missing api_key", provider_id=PROVIDER_ID)
        self.api_key = api_key
        self.api_url = api_url
        self.models_url = models_url_from_api_url(api_url)
        self.timeout = timeout
        self._request = request or _requests().request

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _raise_http(self, response: Any) -> None:
        status = int(response.status_code)
        if status == 429:
            seconds, raw = parse_retry_after_header(response.headers)
            detail = "rate limited (HTTP 429)"
            if raw is not None:
                detail = f"{detail}; Retry-After={raw}"
            raise RateLimitError(
                detail,
                retry_after=seconds,
                retry_after_header=raw,
                status_code=status,
            )
        if status in (401, 403):
            raise ProviderAuthError(
                f"authentication failed (HTTP {status})",
                provider_id=PROVIDER_ID,
            )
        if status >= 400:
            raise ProviderError(
                f"OpenRouter request failed (HTTP {status})",
                provider_id=PROVIDER_ID,
            )

    def send(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = self._request(
                method,
                url,
                headers=self._headers(),
                timeout=self.timeout,
                **kwargs,
            )
        except _requests().exceptions.RequestException as exc:
            raise ProviderOfflineError(
                f"OpenRouter is unreachable: {exc.__class__.__name__}",
                provider_id=PROVIDER_ID,
            ) from exc
        self._raise_http(response)
        return response

    def get_json(self, url: str) -> Any:
        return self._read_json(self.send("GET", url))

    def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        return self._read_json(self.send("POST", url, json=payload))

    def post_sse_lines(self, url: str, payload: dict[str, Any]) -> Iterator[str]:
        response = self.send("POST", url, json=payload, stream=True)
        for line in response.iter_lines(decode_unicode=True):
            if line:
                yield line

    def _read_json(self, response: Any) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(
                "OpenRouter returned invalid JSON",
                provider_id=PROVIDER_ID,
            ) from exc
