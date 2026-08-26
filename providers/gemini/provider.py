"""Gemini ChatProvider backed by the official google-genai client.

The API key is accepted only through the constructor. This module does not
read ``config/api_keys.json`` and does not call ``get_secret``.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from providers.capabilities import require_capability, require_provider_match
from providers.contracts import (
    ChatEvent,
    ConversationMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
    ToolCall,
)
from providers.errors import CapabilityError, ProviderAuthError, ProviderError
from providers.gemini.catalog import GEMINI_MODELS, PROVIDER_ID

ClientFactory = Callable[[str], Any]
_END = object()


def _normalize_key(api_key: str | None) -> str | None:
    if api_key is None:
        return None
    stripped = api_key.strip()
    return stripped or None


def _default_client_factory(api_key: str) -> Any:
    from google import genai

    return genai.Client(api_key=api_key)


def _text_of(payload: object) -> str:
    try:
        text = getattr(payload, "text", None)
    except (AttributeError, ValueError, TypeError):
        return ""
    if callable(text):
        try:
            text = text()
        except (TypeError, ValueError):
            return ""
    return text if isinstance(text, str) else ""


def _contents_and_config(
    messages: Sequence[ConversationMessage],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            system_parts.append(message.content)
            continue
        if message.role == "tool":
            response = (
                {"error": message.error}
                if message.error is not None
                else {"result": message.result}
            )
            if message.artifacts:
                response["artifacts"] = [
                    asdict(item) if is_dataclass(item) else item
                    for item in message.artifacts
                ]
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "id": message.tool_call_id,
                                "name": message.name,
                                "response": response,
                            }
                        }
                    ],
                }
            )
            continue
        gemini_role = "model" if message.role in {"assistant", "model"} else "user"
        parts: list[dict[str, Any]] = []
        if message.content:
            parts.append({"text": message.content})
        parts.extend(
            {
                "function_call": {
                    "id": call.id,
                    "name": call.name,
                    "args": dict(call.arguments),
                }
            }
            for call in getattr(message, "tool_calls", ())
        )
        contents.append({"role": gemini_role, "parts": parts})
    config = (
        {"system_instruction": "\n\n".join(system_parts)} if system_parts else None
    )
    return contents, config


def _models_api(client: Any) -> Any:
    models = getattr(client, "models", None)
    if models is not None and hasattr(models, "generate_content"):
        return models
    return client


def _raise_mapped_error(exc: BaseException) -> None:
    message = str(exc)
    lowered = message.lower()
    auth_markers = (
        "401",
        "403",
        "unauthorized",
        "unauthenticated",
        "permission denied",
        "api key",
        "invalid key",
    )
    if any(marker in lowered for marker in auth_markers):
        raise ProviderAuthError(message, provider_id=PROVIDER_ID) from exc
    raise ProviderError(message, provider_id=PROVIDER_ID) from exc


def _next_or_end(iterator: Iterator[Any]) -> Any:
    return next(iterator, _END)


def _tool_calls_of(
    response: object, *, fallback_prefix: str = "call"
) -> tuple[ToolCall, ...]:
    raw_calls = getattr(response, "function_calls", None)
    if raw_calls is None:
        return ()
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        name = getattr(raw, "name", None)
        if not isinstance(name, str) or not name:
            raise ProviderError(
                "Gemini вернул вызов функции без имени",
                provider_id=PROVIDER_ID,
            )
        arguments = getattr(raw, "args", {})
        if not isinstance(arguments, dict):
            try:
                arguments = dict(arguments)
            except (TypeError, ValueError) as exc:
                raise ProviderError(
                    "Gemini вернул некорректные аргументы функции",
                    provider_id=PROVIDER_ID,
                ) from exc
        calls.append(
            ToolCall(
                id=str(getattr(raw, "id", None) or f"{fallback_prefix}_{index}"),
                name=name,
                arguments=arguments,
            )
        )
    ids = [call.id for call in calls]
    if len(ids) != len(set(ids)):
        raise ProviderError(
            "Gemini вернул повторяющиеся идентификаторы вызовов функций",
            provider_id=PROVIDER_ID,
        )
    return tuple(calls)


class GeminiChatProvider:
    """Chat and stream against Gemini using an injectable google-genai client."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._api_key = _normalize_key(api_key)
        self._client = client
        self._client_factory = client_factory or _default_client_factory

    def _require_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._api_key is None:
            raise ProviderAuthError(
                "Ключ API Gemini отсутствует",
                provider_id=PROVIDER_ID,
            )
        self._client = self._client_factory(self._api_key)
        return self._client

    async def list_models(self) -> list[ModelInfo]:
        return list(GEMINI_MODELS)

    async def validate(self) -> ProviderStatus:
        if self._client is None and self._api_key is None:
            return ProviderStatus(
                provider_id=PROVIDER_ID,
                ok=False,
                message="Ключ API Gemini отсутствует",
            )
        return ProviderStatus(provider_id=PROVIDER_ID, ok=True)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        require_provider_match(request.model, PROVIDER_ID)
        require_capability(request.model, request.role)
        try:
            response = await self._generate(request)
        except (CapabilityError, ProviderAuthError, ProviderError):
            raise
        except Exception as exc:
            _raise_mapped_error(exc)
            raise
        return ChatResponse(
            text=_text_of(response),
            provider_id=PROVIDER_ID,
            model_id=request.model.model_id,
            tool_calls=_tool_calls_of(response),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        require_provider_match(request.model, PROVIDER_ID)
        require_capability(request.model, request.role)
        try:
            raw = self._open_stream(request)
            seen_call_ids: set[str] = set()
            chunk_index = 0
            if hasattr(raw, "__aiter__"):
                async for chunk in raw:
                    text = _text_of(chunk)
                    if text:
                        yield ChatEvent(type="delta", text=text)
                    for call in _tool_calls_of(
                        chunk, fallback_prefix=f"stream_{chunk_index}"
                    ):
                        if call.id in seen_call_ids:
                            raise ProviderError(
                                "Поток Gemini вернул повторяющийся идентификатор вызова функции",
                                provider_id=PROVIDER_ID,
                            )
                        seen_call_ids.add(call.id)
                        yield ChatEvent(type="tool_call", tool_call=call)
                    chunk_index += 1
            else:
                while True:
                    chunk = await asyncio.to_thread(_next_or_end, raw)
                    if chunk is _END:
                        break
                    text = _text_of(chunk)
                    if text:
                        yield ChatEvent(type="delta", text=text)
                    for call in _tool_calls_of(
                        chunk, fallback_prefix=f"stream_{chunk_index}"
                    ):
                        if call.id in seen_call_ids:
                            raise ProviderError(
                                "Поток Gemini вернул повторяющийся идентификатор вызова функции",
                                provider_id=PROVIDER_ID,
                            )
                        seen_call_ids.add(call.id)
                        yield ChatEvent(type="tool_call", tool_call=call)
                    chunk_index += 1
        except (CapabilityError, ProviderAuthError, ProviderError):
            raise
        except Exception as exc:
            _raise_mapped_error(exc)
            raise
        yield ChatEvent(type="done")

    async def _generate(self, request: ChatRequest) -> Any:
        models = _models_api(self._require_client())
        kwargs = _request_kwargs(request)
        generate = models.generate_content
        if inspect.iscoroutinefunction(generate):
            return await generate(**kwargs)
        return await asyncio.to_thread(generate, **kwargs)

    def _open_stream(self, request: ChatRequest) -> Any:
        models = _models_api(self._require_client())
        return models.generate_content_stream(**_request_kwargs(request))


def _request_kwargs(request: ChatRequest) -> dict[str, Any]:
    contents, config = _contents_and_config(request.messages)
    kwargs: dict[str, Any] = {
        "model": request.model.model_id,
        "contents": contents,
    }
    if config is not None:
        kwargs["config"] = config
    if request.tools:
        kwargs.setdefault("config", {})["tools"] = [
            {
                "function_declarations": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.parameters),
                    }
                    for tool in request.tools
                ]
            }
        ]
    return kwargs
