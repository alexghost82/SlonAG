"""Route one chat/stream request to one selected provider.

Fallback is an explicit pluggable policy. The default policy never retries
and never moves a local failure to a cloud adapter. This module does not
read ``api_keys.json`` and does not implement cost accounting.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from typing import Protocol, runtime_checkable

from providers.capabilities import require_capabilities, require_capability
from providers.contracts import (
    ChatEvent,
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
)
from providers.errors import ProviderAuthError, ProviderError
from providers.registry import get
from providers.routing import select_model

CLOUD_PROVIDER_IDS = frozenset({"gemini", "openai", "openrouter"})
LOCAL_PROVIDER_IDS = frozenset({"local", "ollama", "llama_cpp"})

_ADAPTER_MODULES = {
    "gemini": "providers.gemini",
    "openai": "providers.openai",
    "openrouter": "providers.openrouter",
    "local": "providers.local",
    "ollama": "providers.local",
    "llama_cpp": "providers.local",
}

KeyProvider = Callable[[str], str | None]


@runtime_checkable
class FallbackPolicy(Protocol):
    """Choose at most one next provider id after a failed attempt."""

    name: str

    def next(self, failed_provider_id: str, error: BaseException) -> str | None:
        """Return another provider id to try once, or ``None`` to stop."""


class NeverFallbackPolicy:
    """Default policy: never substitute another provider or model."""

    name = "never"

    def next(self, failed_provider_id: str, error: BaseException) -> str | None:
        return None


class Router:
    """Send one request to one provider after a capability check."""

    def __init__(
        self,
        provider_id: str,
        *,
        network_mode: str | None = None,
        privacy_profile: str | None = None,
        key_provider: KeyProvider | None = None,
        providers: Mapping[str, ChatProvider] | None = None,
        fallback_policy: FallbackPolicy | None = None,
        routing_mode: str | None = None,
        models: tuple[ModelInfo, ...] = (),
        model_availability: Mapping[object, bool] | None = None,
        configured_model_id: str | None = None,
    ) -> None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ProviderError("provider_id must be a non-empty string")
        self.provider_id = provider_id
        self.network_mode = network_mode
        self.privacy_profile = privacy_profile
        self.routing_mode = routing_mode
        self._models = models
        self._model_availability = model_availability
        self._configured_model_id = configured_model_id
        self._key_provider = key_provider
        self._injected = dict(providers) if providers is not None else {}
        self._fallback_policy: FallbackPolicy = (
            fallback_policy if fallback_policy is not None else NeverFallbackPolicy()
        )
        self._resolved: dict[str, ChatProvider] = {}

    async def validate(self) -> ProviderStatus:
        """Check the selected provider without opening a chat request."""
        if not self._cloud_allowed(self.provider_id):
            return ProviderStatus(
                provider_id=self.provider_id,
                ok=False,
                message=self._cloud_forbidden_message(self.provider_id),
            )
        if self._missing_cloud_key(self.provider_id):
            return ProviderStatus(
                provider_id=self.provider_id,
                ok=False,
                message="missing api key",
            )
        return await self._resolve(self.provider_id).validate()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        request = self._route_request(request)
        self._require_request_capabilities(request)
        try:
            return await self._resolve(request.model.provider_id).chat(request)
        except Exception as exc:
            fallback_id = self._fallback_provider_id(request.model.provider_id, exc)
            if fallback_id is None:
                raise
            self._require_request_capabilities(request)
            return await self._resolve(fallback_id).chat(request)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        request = self._route_request(request)
        self._require_request_capabilities(request)
        yielded = False
        try:
            async for event in self._resolve(request.model.provider_id).stream(request):
                yielded = True
                yield _as_chat_event(event)
            return
        except Exception as exc:
            if yielded:
                raise
            fallback_id = self._fallback_provider_id(request.model.provider_id, exc)
            if fallback_id is None:
                raise
        self._require_request_capabilities(request)
        async for event in self._resolve(fallback_id).stream(request):
            yield _as_chat_event(event)

    @staticmethod
    def _require_request_capabilities(request: ChatRequest) -> None:
        require_capability(request.model, request.role)
        if request.tools:
            require_capabilities(request.model, ("text", "tool_calling"))

    def _cloud_restricted(self) -> bool:
        return (
            self.network_mode in {"offline", "tools_only"}
            or self.privacy_profile in {"fully_local", "local_with_tools"}
        )

    def _cloud_allowed(self, provider_id: str) -> bool:
        if self.routing_mode == "local_only" and provider_id in CLOUD_PROVIDER_IDS:
            return False
        return provider_id not in CLOUD_PROVIDER_IDS or not self._cloud_restricted()

    def _route_request(self, request: ChatRequest) -> ChatRequest:
        if self.routing_mode is None:
            return request
        candidates = self._models or (request.model,)
        required = ("text", "tool_calling") if request.tools else ()
        model = select_model(
            candidates,
            routing_mode=self.routing_mode,
            configured_provider_id=self.provider_id,
            configured_model_id=self._configured_model_id,
            required_role=request.role,
            required_capabilities=required,
            availability=self._model_availability,
            network_mode=self.network_mode,
            privacy_profile=self.privacy_profile,
        )
        return request if model is request.model else replace(request, model=model)

    def _restriction_reason(self) -> str:
        if self.network_mode == "offline":
            return "network_mode='offline'"
        if self.network_mode == "tools_only":
            return "network_mode='tools_only'"
        if self.privacy_profile == "fully_local":
            return "privacy_profile='fully_local'"
        if self.privacy_profile == "local_with_tools":
            return "privacy_profile='local_with_tools'"
        return "cloud access is disabled"

    def _cloud_forbidden_message(self, provider_id: str) -> str:
        return (
            f"cloud provider {provider_id!r} is not allowed when "
            f"{self._restriction_reason()}"
        )

    def _lookup_key(self, provider_id: str) -> str | None:
        if self._key_provider is None:
            return None
        key = self._key_provider(provider_id)
        if key is None:
            return None
        stripped = key.strip()
        return stripped or None

    def _missing_cloud_key(self, provider_id: str) -> bool:
        if provider_id in self._injected or provider_id in self._resolved:
            return False
        return (
            provider_id in CLOUD_PROVIDER_IDS
            and self._lookup_key(provider_id) is None
        )

    def _fallback_provider_id(
        self, failed_provider_id: str, error: BaseException
    ) -> str | None:
        nxt = self._fallback_policy.next(failed_provider_id, error)
        if nxt is None or nxt == failed_provider_id:
            return None
        if not self._cloud_allowed(nxt):
            return None
        return nxt

    def _resolve(self, provider_id: str) -> ChatProvider:
        if not self._cloud_allowed(provider_id):
            raise ProviderError(
                self._cloud_forbidden_message(provider_id),
                provider_id=provider_id,
            )
        cached = self._resolved.get(provider_id)
        if cached is not None:
            return cached
        injected = self._injected.get(provider_id)
        if injected is not None:
            self._resolved[provider_id] = injected
            return injected
        if self._missing_cloud_key(provider_id):
            raise ProviderAuthError(
                "missing api key",
                provider_id=provider_id,
            )
        instance = self._build_from_factory(provider_id)
        self._resolved[provider_id] = instance
        return instance

    def _build_from_factory(self, provider_id: str) -> ChatProvider:
        factory = _factory_for(provider_id)
        key = self._lookup_key(provider_id)
        if key is not None and "api_key" in inspect.signature(factory).parameters:
            return factory(api_key=key)
        return factory()


def _factory_for(provider_id: str):
    try:
        return get(provider_id)
    except ProviderError:
        module_name = _ADAPTER_MODULES.get(provider_id)
        if module_name is None:
            raise
        importlib.import_module(module_name)
        return get(provider_id)


def _as_chat_event(event: object) -> ChatEvent:
    if isinstance(event, ChatEvent):
        return event
    event_type = getattr(event, "type", None)
    text = getattr(event, "text", "")
    if event_type in {"delta", "done"} and isinstance(text, str):
        return ChatEvent(type=event_type, text=text)
    raise ProviderError("provider stream emitted an unsupported event")


ProviderRouter = Router

__all__ = [
    "CLOUD_PROVIDER_IDS",
    "FallbackPolicy",
    "KeyProvider",
    "LOCAL_PROVIDER_IDS",
    "NeverFallbackPolicy",
    "ProviderRouter",
    "Router",
]
