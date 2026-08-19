"""Local VisionProvider with an injected engine.

Engines are wrapped behind ``VisionEngine``. This module does not download
models, capture screenshots, read API keys, or touch the network.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from providers.capabilities import require_capability
from providers.contracts import ModelInfo, VisionRequest, VisionResponse
from providers.errors import ProviderError

PROVIDER_ID = "vision_local"
DEFAULT_PRIVACY_PROFILE = "fully_local"
DEFAULT_KIND = "describe"
VISION_KINDS = frozenset({"ocr", "describe", "ui", "document", "visual_control"})
UNTRUSTED_LABEL = "untrusted user data"
UNTRUSTED_FENCE = "untrusted-user-data"


class VisionEngine(Protocol):
    """Sync vision backend. Implementations must not hit the network."""

    def analyze(self, image: bytes, prompt: str, kind: str) -> str: ...


@dataclass(frozen=True)
class VisionTaskRequest:
    """``VisionRequest`` plus an explicit task kind.

    ``analyze`` still accepts a plain ``VisionRequest``; ``kind`` is read
    when present so callers do not need to encode the task in ``prompt``.
    """

    model: ModelInfo
    image: bytes
    prompt: str = ""
    kind: str = DEFAULT_KIND


def engine_is_cloud(engine: object) -> bool:
    """Return True when the injected engine is explicitly marked as cloud."""
    cloud = getattr(engine, "cloud", None)
    if cloud is not None:
        return bool(cloud)
    is_cloud = getattr(engine, "is_cloud", None)
    if is_cloud is not None:
        return bool(is_cloud)
    return False


def wrap_untrusted_image_text(text: str) -> str:
    """Fence extracted image text so it cannot be read as system or tool input."""
    payload = text.replace("```", "'''")
    return (
        f"[{UNTRUSTED_LABEL}]\n"
        f"```{UNTRUSTED_FENCE}\n"
        f"{payload}\n"
        f"```"
    )


def resolve_kind(request: VisionRequest | VisionTaskRequest) -> str:
    """Return a supported task kind from ``request.kind`` or the prompt."""
    raw = getattr(request, "kind", None)
    if raw is not None:
        if not isinstance(raw, str) or raw not in VISION_KINDS:
            raise ProviderError(
                f"unsupported vision kind {raw!r}",
                provider_id=PROVIDER_ID,
            )
        return raw
    token = _prompt_kind_token(request.prompt)
    if token is not None:
        return token
    return DEFAULT_KIND


def _prompt_kind_token(prompt: str) -> str | None:
    stripped = prompt.strip()
    if not stripped:
        return None
    token = stripped.split(None, 1)[0].lower().rstrip(":")
    if token in VISION_KINDS:
        return token
    return None


class LocalVisionProvider:
    """Headless local vision adapter. Cloud engines stay opt-in."""

    provider_id = PROVIDER_ID

    def __init__(
        self,
        engine: VisionEngine,
        allow_cloud: bool = False,
        temp_dir: str | Path | None = None,
        privacy_profile: str = DEFAULT_PRIVACY_PROFILE,
        *,
        network_mode: str | None = None,
    ) -> None:
        if engine is None:
            raise TypeError("engine is required")
        if temp_dir is None:
            raise TypeError("temp_dir is required")
        self._engine = engine
        self.allow_cloud = allow_cloud
        self.temp_dir = Path(temp_dir)
        self.privacy_profile = privacy_profile
        self.network_mode = network_mode

    def _cloud_blocked(self) -> bool:
        if not self.allow_cloud:
            return True
        if self.privacy_profile == "fully_local":
            return True
        if self.network_mode == "offline":
            return True
        return False

    def _restriction_reason(self) -> str:
        if not self.allow_cloud:
            return "allow_cloud=False"
        if self.network_mode == "offline":
            return "network_mode='offline'"
        if self.privacy_profile == "fully_local":
            return "privacy_profile='fully_local'"
        return "cloud access is disabled"

    def _refuse_cloud_if_needed(self) -> None:
        if engine_is_cloud(self._engine) and self._cloud_blocked():
            raise ProviderError(
                "cloud vision engine is not allowed when "
                f"{self._restriction_reason()}",
                provider_id=PROVIDER_ID,
            )

    def _write_snapshot(self, image: bytes) -> Path:
        root = self.temp_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(
            prefix="vision-snapshot-",
            suffix=".img",
            dir=str(root),
        )
        path = Path(raw_path)
        try:
            if not path.resolve().is_relative_to(root):
                raise ProviderError(
                    "temp snapshot escaped temp_dir",
                    provider_id=PROVIDER_ID,
                )
            with os.fdopen(fd, "wb") as handle:
                handle.write(image)
                handle.flush()
            return path
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise

    async def analyze(self, request: VisionRequest | VisionTaskRequest) -> VisionResponse:
        require_capability(request.model, "vision")
        kind = resolve_kind(request)
        self._refuse_cloud_if_needed()
        snapshot: Path | None = None
        try:
            snapshot = self._write_snapshot(request.image)
            text = await asyncio.to_thread(
                self._engine.analyze,
                request.image,
                request.prompt,
                kind,
            )
            return VisionResponse(text=wrap_untrusted_image_text(text))
        finally:
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
