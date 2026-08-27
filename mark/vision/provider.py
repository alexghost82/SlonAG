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

import asyncio
import time
from typing import Any

from mark.vision.config import VisionConfig
from mark.vision.runtime import VisionRuntime, create_runtime
from mark.vision.processing import detect_capabilities
from mark.vision.tools import register_vision_tools, register_vision_capabilities
from mark.vision.types import (
    DetectionKind,
    DetectionResult,
    Frame,
    FrameEvent,
    FrameSource,
    TrackingState,
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
