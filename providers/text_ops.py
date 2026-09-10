"""Provider-neutral sync text helpers. SDK imports stay inside adapters."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from providers.contracts import ChatRequest, ModelInfo, UserMessage
from providers.router import NeverFallbackPolicy, Router

logger = logging.getLogger(__name__)


class LocalOnlyBlocked(RuntimeError):
    """Cloud text ops are forbidden in local_only / offline / fully_local."""


def _settings_forbid_cloud() -> bool:
    try:
        from config.settings import load_settings

        settings = load_settings()
    except Exception:
        return True
    network = getattr(settings, "network_mode", "")
    routing = getattr(settings, "routing_mode", "")
    privacy = getattr(settings, "privacy_profile", "")
    return (
        network in {"offline", "local_only", "tools_only"}
        or routing == "local_only"
        or privacy in {"fully_local", "local_only", "local_with_tools"}
    )


def _run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


async def _complete_async(prompt: str, system: str, model_id: str) -> str:
    def key_provider(name: str) -> str | None:
        from config.secrets import get_provider_secret, get_secret

        return get_provider_secret(name) or get_secret("gemini_api_key")

    router = Router(
        "gemini",
        fallback_policy=NeverFallbackPolicy(),
        key_provider=key_provider,
    )
    model = ModelInfo(
        provider_id="gemini",
        model_id=model_id,
        display_name=model_id,
        text=True,
    )
    messages = []
    text = prompt
    if system:
        text = f"{system}\n\n{prompt}"
    messages.append(UserMessage(text))
    response = await router.chat(ChatRequest(model=model, messages=tuple(messages)))
    return response.text or ""


class _CompatClient:
    """Drop-in for the retired root or_client.chat helper."""

    def chat(self, prompt: str, system: str = "", **_kwargs: object) -> str:
        try:
            return complete_text(prompt, system=system)
        except LocalOnlyBlocked:
            return ""


client = _CompatClient()


def complete_text(
    prompt: str,
    *,
    system: str = "",
    model_id: str = "gemini-2.5-flash",
) -> str:
    """Complete text through Router. Fail-closed when cloud is forbidden."""
    if _settings_forbid_cloud():
        raise LocalOnlyBlocked("text ops are disabled in local_only/offline")
    return _run_sync(_complete_async(prompt, system, model_id))
