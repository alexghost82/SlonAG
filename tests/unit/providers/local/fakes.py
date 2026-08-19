"""In-memory HTTP transport for local adapter tests. No network I/O."""

from __future__ import annotations

import json
from collections.abc import Mapping

from providers.local.http import TransportResponse

OPENAI_MODELS = {"data": [{"id": "tinyllama", "owned_by": "local"}]}
OPENAI_CHAT = {"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
OPENAI_STREAM_LINES = (
    'data: {"choices":[{"delta":{"content":"po"}}]}',
    'data: {"choices":[{"delta":{"content":"ng"}}]}',
    "data: [DONE]",
)
OLLAMA_TAGS = {"models": [{"name": "llama3:latest"}]}
OLLAMA_CHAT = {"message": {"role": "assistant", "content": "pong"}, "done": True}
OLLAMA_STREAM_LINES = (
    json.dumps({"message": {"content": "po"}, "done": False}),
    json.dumps({"message": {"content": "ng"}, "done": True}),
)


class FakeTransport:
    """Records requests and returns canned OpenAI or Ollama payloads."""

    def __init__(
        self,
        *,
        models: object | None = None,
        chat: object | None = None,
        stream_lines: tuple[str, ...] | None = None,
        status_code: int = 200,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.models = models
        self.chat = chat
        self.stream_lines = stream_lines
        self.status_code = status_code
        self.error = error

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
        stream: bool = False,
        timeout: float = 30.0,
    ) -> TransportResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "json_body": json_body,
                "stream": stream,
                "timeout": timeout,
            }
        )
        if self.error is not None:
            raise self.error
        if method.upper() == "GET":
            body = json.dumps(self.models if self.models is not None else {})
            return TransportResponse(status_code=self.status_code, body=body)
        if stream:
            lines = self.stream_lines if self.stream_lines is not None else ()
            return TransportResponse(
                status_code=self.status_code,
                body="\n".join(lines),
                lines=lines,
            )
        body = json.dumps(self.chat if self.chat is not None else {})
        return TransportResponse(status_code=self.status_code, body=body)


def openai_transport() -> FakeTransport:
    return FakeTransport(
        models=OPENAI_MODELS,
        chat=OPENAI_CHAT,
        stream_lines=OPENAI_STREAM_LINES,
    )


def ollama_transport() -> FakeTransport:
    return FakeTransport(
        models=OLLAMA_TAGS,
        chat=OLLAMA_CHAT,
        stream_lines=OLLAMA_STREAM_LINES,
    )
