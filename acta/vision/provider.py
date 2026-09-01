"""Production VisionProvider with bounded VisionRuntime.

Integrates the full Vision Runtime pipeline (frame acquisition,
detection, tracking, temporal analysis) and exposes results through the
standard VisionProvider interface so AgentLoop can consume vision data.

Supported sources
-----------------
- ``image``       : local image file (single frame)
- ``screenshot``  : cross-platform screenshot via mss
- ``screen``      : screen capture via PIL
- ``camera``      : webcam via OpenCV
- ``rtsp``        : RTSP stream via ffmpeg subprocess

Capabilities are automatically detected:
- ``object_detection`` : OpenCV HOG (fallback → no-op)
- ``person_detection`` : OpenCV HOG people detector (fallback → no-op)
- ``ocr``              : Tesseract (fallback → no-op)

When a capability backend is unavailable, the provider reports the
capability as ``false`` and the result still completes without error.
"""

from __future__ import annotations

from typing import Any

from acta.vision.config import VisionConfig
from acta.vision.processing import detect_capabilities
from acta.vision.runtime import VisionRuntime, create_runtime
from acta.vision.tools import register_vision_capabilities, register_vision_tools
from acta.vision.types import (
    Frame,
    FrameEvent,
    VisionAnalysis,
    VisionRuntimeStatus,
)


class VisionProvider:
    """Production-grade vision provider backed by VisionRuntime.

    Parameters
    ----------
    source_type : str
        One of "image", "screenshot", "screen", "camera", "rtsp".
    source_config : dict | None
        Source-specific kwargs (rtsp_url, camera_id, file_path, etc.).
    config : VisionConfig | None
        Override bounded limits.
    """

    def __init__(
        self,
        source_type: str = "image",
        source_config: dict[str, Any] | None = None,
        config: VisionConfig | None = None,
    ) -> None:
        self._source_type = source_type
        self._config = config or VisionConfig()
        # Merge source config
        src_cfg = (source_config or {}).copy()
        src_cfg["type"] = source_type
        self._config.source_config.update(src_cfg)
        self._runtime: VisionRuntime | None = None
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self) -> bool:
        """Start the vision pipeline.

        Returns True on success.
        """
        try:
            self._runtime = create_runtime(
                self._source_type,
                config=self._config,
                **self._config.source_config,
            )
            # Wire callbacks
            self._runtime.on_frame = self._on_frame
            self._runtime.on_analysis = self._on_analysis
            self._runtime.on_event = self._on_event
            result = await self._runtime.start(self._source_type, **self._config.source_config)
            if result:
                self._running = True
            return result
        except Exception:
            self._running = False
            return False

    async def stop(self) -> None:
        """Stop and clean up."""
        self._running = False
        if self._runtime is not None:
            await self._runtime.stop()
            self._runtime = None

    async def cancel(self) -> None:
        """Cancel (alias for stop)."""
        await self.stop()

    async def reconnect(self) -> bool:
        """Attempt source reconnection."""
        if self._runtime is None:
            return False
        return await self._runtime.reconnect()

    def status(self) -> VisionRuntimeStatus | None:
        if self._runtime is None:
            return None
        return self._runtime.status()

    # ── query API (used by AgentLoop) ────────────────────────────

    async def get_frame_results(self, n: int = 10) -> list[dict[str, Any]]:
        """Get recent frame processing results."""
        if self._runtime is None:
            return []
        detections = await self._runtime.get_recent_detections(n)
        return [
            {
                "kind": d.kind.value,
                "label": d.label,
                "confidence": d.confidence,
                "track_id": d.track_id,
                "bbox": {
                    "x_min": d.bbox.x_min, "y_min": d.bbox.y_min,
                    "x_max": d.bbox.x_max, "y_max": d.bbox.y_max,
                },
            }
            for d in detections
        ]

    async def get_events(self, n: int = 20) -> list[dict[str, Any]]:
        """Get recent frame events."""
        if self._runtime is None:
            return []
        events = await self._runtime.get_recent_events(n)
        return [
            {
                "type": e.event_type.value,
                "track_id": e.track_id,
                "description": e.description,
                "timestamp": e.timestamp,
            }
            for e in events
        ]

    def get_tracks(self) -> dict[str, Any]:
        """Get current tracking state."""
        if self._runtime is None:
            return {}
        tracks = self._runtime.get_active_tracks()
        return {
            tid: {
                "label": ts.label,
                "kind": ts.kind.value,
                "age": ts.age,
                "present": ts.is_present,
                "trajectory_len": len(ts.trajectory),
                "appearances": len(ts.appearances),
            }
            for tid, ts in tracks.items()
        }

    def get_trajectory(self, track_id: str) -> list[dict[str, Any]]:
        """Get trajectory for a specific track."""
        if self._runtime is None:
            return []
        pts = self._runtime.get_trajectory(track_id)
        return [{"cx": p.center_x, "cy": p.center_y, "w": p.width, "h": p.height} for p in pts]

    def get_present_tracks(self) -> list[str]:
        """Get currently present track IDs."""
        if self._runtime is None:
            return []
        return self._runtime.get_present_tracks()

    def get_capabilities(self) -> dict[str, bool]:
        """Return capability detection status."""
        if self._runtime is None:
            return {"object_detection": False, "person_detection": False, "ocr": False}
        return detect_capabilities(b"", 640, 480)

    def register_with_registry(self, registry: Any) -> None:
        """Register vision tools with a Mark tool registry."""
        if self._runtime is not None:
            register_vision_tools(registry, self._runtime)

    def register_capabilities(self, capabilities: dict[str, bool]) -> None:
        """Register vision capabilities."""
        if self._runtime is not None:
            register_vision_capabilities(capabilities, self._runtime)

    # ── internal callbacks ───────────────────────────────────────

    def _on_frame(self, frame: Frame) -> None:
        pass  # could be hooked for logging

    def _on_analysis(self, analysis: VisionAnalysis) -> None:
        pass

    def _on_event(self, event: FrameEvent) -> None:
        pass


def create_vision_provider(
    source_type: str = "image",
    source_config: dict[str, Any] | None = None,
    config: VisionConfig | None = None,
) -> VisionProvider:
    """Convenience factory."""
    return VisionProvider(source_type, source_config, config)

# ───────────────────────────────────────────────────────────────────────────
# Security constants and untrusted fencing
# ───────────────────────────────────────────────────────────────────────────

DEFAULT_KIND: str = "vlm"
DEFAULT_PRIVACY_PROFILE: str = "fully_local"
PROVIDER_ID: str = "vision_local"

VISION_KINDS: tuple[str, ...] = (
    "vlm",
    "ocr",
    "object_detection",
    "person_detection",
    "general",
)

UNTRUSTED_LABEL: str = "untrusted-vision"
UNTRUSTED_FENCE: str = "<!-- untrusted-vision -->"


def wrap_untrusted_image_text(text: str) -> str:
    """Wrap extracted image text so the LLM treats it as untrusted user data.

    The fence prefix prevents the LLM from interpreting the text as system
    instructions or tool-call output.  The output never contains a leading
    "system" or "system instruction" token.
    """
    # Escape backticks to prevent code-block injection through the text
    escaped = text.replace("```", "`\u200b``")
    return (
        f"{UNTRUSTED_FENCE}\n"
        f"# {UNTRUSTED_LABEL}\n"
        f"untrusted user data — extracted from image:\n"
        f"```ocr\n"
        f"{escaped}\n"
        f"```\n"
        f"<!-- /untrusted-vision -->"
    )


# ───────────────────────────────────────────────────────────────────────────
# LocalVisionProvider — security-gated, ephemeral-image vision analysis
# ───────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from providers.contracts import VisionRequest, VisionResponse
from providers.errors import CapabilityError, ProviderError


@dataclass(frozen=True)
class VisionTaskRequest:
    """Extended VisionRequest with a ``kind`` selector."""
    model: Any  # ModelInfo
    image: bytes
    prompt: str = ""
    kind: str = DEFAULT_KIND


class _EngineProtocol:
    """Minimal protocol expected of a vision analysis engine."""
    def analyze(self, image: bytes, prompt: str, kind: str) -> str:
        ...  # pragma: no cover


class LocalVisionProvider:
    """Secure local vision provider backed by an injectable analysis engine.

    Security properties
    -------------------
    * **fail-closed**: cloud engines are rejected unless ``allow_cloud=True``
      *and* ``privacy_profile != "fully_local"`` *and* ``network_mode != "offline"``.
    * **ephemeral images**: the input bytes are written to a named temp file,
      the engine is called, and the file is deleted (on both success and failure).
    * **untrusted text**: OCR results are automatically wrapped with
      ``UNTRUSTED_FENCE`` so the LLM treats them as user data.
    * **bounded kinds**: only ``VISION_KINDS`` are accepted; unknown kinds raise
      ``ProviderError`` before reaching the engine.
    """

    def __init__(
        self,
        engine: _EngineProtocol,
        temp_dir: Path,
        *,
        allow_cloud: bool = False,
        privacy_profile: str = DEFAULT_PRIVACY_PROFILE,
        network_mode: str = "offline",
    ) -> None:
        if engine is None:
            raise TypeError("engine is required")
        if temp_dir is None:
            raise TypeError("temp_dir is required")
        self.engine = engine
        self.temp_dir = Path(temp_dir)
        self.allow_cloud = allow_cloud
        self.privacy_profile = privacy_profile
        self.network_mode = network_mode
        self.provider_id = PROVIDER_ID

    # ── public API ────────────────────────────────────────────────────

    async def analyze(
        self,
        request: VisionRequest | VisionTaskRequest,
    ) -> VisionResponse:
        """Run a single analysis with full security gating."""
        # 1. Reject if model has vision=False
        model_id = getattr(request.model, "model_id", "unknown")
        provider_id = getattr(request.model, "provider_id", "")
        vision_cap = getattr(request.model, "vision", True)
        if not vision_cap:
            raise CapabilityError(
                provider_id=provider_id,
                model_id=model_id,
                role="vision",
                message="vision capability is disabled for this model",
            )

        # 2. Reject cloud engine when policy forbids it
        if getattr(self.engine, "cloud", False) and not self._cloud_allowed():
            raise ProviderError(
                provider_id=provider_id or PROVIDER_ID,
                message="Облачный engine запрещён: privacy_profile или allow_cloud=False",
            )

        # 3. Validate kind
        kind = self._resolve_kind(request.prompt, request.kind)

        # 4. Write ephemeral temp file
        tmp_file = self.temp_dir / f"vision-snapshot-{uuid4().hex[:12]}.png"
        tmp_file.write_bytes(request.image)

        # 5. Call engine (bounded, may raise)
        try:
            text = self.engine.analyze(
                image=request.image,
                prompt=request.prompt,
                kind=kind,
            )
        finally:
            # 6. Always delete temp file
            try:
                tmp_file.unlink(missing_ok=True)
            except OSError:
                pass

        # 7. Wrap OCR/general results as untrusted
        if kind in ("ocr", "general") or "ocr" in request.prompt.lower():
            text = wrap_untrusted_image_text(text)

        return VisionResponse(text=text)

    # ── internals ─────────────────────────────────────────────────────

    def _cloud_allowed(self) -> bool:
        """Return True only when all three conditions hold."""
        if not self.allow_cloud:
            return False
        if self.privacy_profile == "fully_local":
            return False
        if self.network_mode == "offline":
            return False
        return True

    def _resolve_kind(self, prompt: str, explicit_kind: str) -> str:
        """Determine kind: explicit kind must be in VISION_KINDS,
        otherwise try to infer from prompt.
        "general" is treated as a placeholder — prompt inference is tried first.
        Unknown explicit kinds raise ProviderError.
        """
        kind = explicit_kind.strip()
        # "general" is a placeholder — infer from prompt first
        if kind == "general":
            lower = prompt.lower()
            for k in VISION_KINDS:
                if k in lower:
                    return k
            # No match in prompt -> treat as DEFAULT_KIND
            return DEFAULT_KIND
        elif kind and kind in VISION_KINDS:
            return kind
        # Unknown explicit kind -> reject
        if kind:
            raise ProviderError(
                provider_id=PROVIDER_ID,
                message=f"Неподдерживаемый тип vision: {kind!r}",
            )
        # Infer from prompt: "ocr", "object_detection", etc.
        lower = prompt.lower()
        for k in VISION_KINDS:
            if k in lower:
                return k
        return DEFAULT_KIND



def register_factory() -> None:
    """Register ``LocalVisionProvider`` factory with the providers registry."""
    from providers.registry import register
    register(PROVIDER_ID, LocalVisionProvider)

__all__ = [
    "DEFAULT_KIND",
    "DEFAULT_PRIVACY_PROFILE",
    "PROVIDER_ID",
    "UNTRUSTED_FENCE",
    "UNTRUSTED_LABEL",
    "VISION_KINDS",
    "LocalVisionProvider",
    "VisionTaskRequest",
    "create_vision_provider",
    "create_runtime",
    "detect_capabilities",
    "wrap_untrusted_image_text",
    "register_factory",
]
