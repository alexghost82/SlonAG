"""OpenAI-compatible HTTP client used only by this adapter.

Chat Completions is the default transport. Any Responses-style payloads or
SSE event types are parsed here so they never leak into shared contracts.
This module does not import the ``openai`` SDK and does not read secrets.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Protocol

from providers.errors import ProviderAuthError, ProviderError, ProviderOfflineError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 60.0
PROVIDER_ID = "openai"


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...

    def iter_lines(self, decode_unicode: bool = True) -> Iterator[str]: ...

    def close(self) -> None: ...


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None = None,
        stream: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> HttpResponse: ...


class RequestsTransport:
    """``requests``-backed transport. Imported lazily for CI without runtime deps."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None = None,
        stream: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> HttpResponse:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError(
                "requests is required for the openai adapter",
                provider_id=PROVIDER_ID,
            ) from exc
        try:
            response = requests.request(
                method,
                url,
                headers=dict(headers),
                json=dict(json) if json is not None else None,
                stream=stream,
                timeout=timeout,
            )
            return response  # type: ignore[return-value]
        except requests.ConnectionError as exc:
            raise ProviderOfflineError(
                "openai is unreachable",
                provider_id=PROVIDER_ID,
            ) from exc
        except requests.RequestException as exc:
            raise ProviderError(
                "openai request failed",
                provider_id=PROVIDER_ID,
            ) from exc


class OpenAIHttpClient:
    """One-request HTTP helper for models, chat, and streaming."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: HttpTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport: HttpTransport = transport or RequestsTransport()

    def list_models(self) -> dict[str, Any]:
        response = self._request("GET", "/models")
        try:
            payload = response.json()
        finally:
            response.close()
        if not isinstance(payload, dict):
            raise ProviderError(
                "openai models response was not an object",
                provider_id=PROVIDER_ID,
            )
        return payload

    def chat_completion(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/chat/completions", json=payload)
        try:
            body = response.json()
        finally:
            response.close()
        if not isinstance(body, dict):
            raise ProviderError(
                "openai chat response was not an object",
                provider_id=PROVIDER_ID,
            )
        return body

    def stream_chat_completion(
        self, payload: Mapping[str, Any]
    ) -> Iterator[dict[str, Any]]:
        response = self._request(
            "POST",
            "/chat/completions",
            json=payload,
            stream=True,
        )
        try:
            yield from iter_sse_events(response)
        finally:
            response.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        stream: bool = False,
    ) -> HttpResponse:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response = self.transport.request(
            method,
            url,
            headers=self._headers(),
            json=json,
            stream=stream,
            timeout=self.timeout,
        )
        _raise_for_status(response)
        return response

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SlonAG/1.0 ProviderLayer",
        }


def iter_sse_events(response: HttpResponse) -> Iterator[dict[str, Any]]:
    """Parse Chat Completions SSE and isolated Responses-style events."""
    import json

    for raw in response.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def extract_message_text(payload: Mapping[str, Any]) -> str:
    """Read assistant text from Chat Completions or Responses-style bodies."""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                text = _content_to_text(message.get("content"))
                if text:
                    return text
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") in {
                    "output_text",
                    "text",
                }:
                    parts.append(str(content.get("text") or ""))
        if parts:
            return "".join(parts)
    if choices == [] or choices is None:
        raise ProviderError(
            "openai returned no choices",
            provider_id=PROVIDER_ID,
        )
    return ""


def extract_delta_text(event: Mapping[str, Any]) -> str:
    """Read one stream delta from Chat Completions or Responses SSE."""
    choices = event.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            delta = first.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    return content
    if event.get("type") == "response.output_text.delta":
        delta = event.get("delta")
        if isinstance(delta, str):
            return delta
    return ""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {
                "text",
                "output_text",
            }:
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return ""


def _raise_for_status(response: HttpResponse) -> None:
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 400:
        return
    if status in {401, 403}:
        raise ProviderAuthError(
            "openai rejected credentials",
            provider_id=PROVIDER_ID,
        )
    if status == 429:
        raise ProviderError(
            "openai rate-limited the request",
            provider_id=PROVIDER_ID,
        )
    raise ProviderError(
        f"openai returned HTTP {status}",
        provider_id=PROVIDER_ID,
    )
