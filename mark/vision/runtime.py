"""Vision Runtime — main orchestrator.

Ties together frame acquisition, processing, tracking, and temporal
analysis into a single bounded, cancellable, self-healing system.

Public API
----------
- ``VisionRuntime`` : full pipeline with start / stop / reconnect.
- ``create_runtime(source_type, **src_kwargs)`` : convenience factory.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, Callable

from mark.vision.acquisition import (
    AcquisitionConfig,
    CameraSource,
    FrameSourceBase,
    ImageSource,
    RTSPSource,
    ScreenshotSource,
    ScreenSource,
)
from mark.vision.config import VisionConfig
from mark.vision.processing import (
    DetectionBackend,
    build_object_detector,
    build_ocr,
    build_person_detector,
    detect_capabilities,
)
from mark.vision.queues import (
    BoundedDetectionQueue,
    BoundedEventQueue,
    BoundedFrameQueue,
    BoundedTrajectoryStore,
)
from mark.vision.temporal import TemporalAnalyzer
from mark.vision.tracking import ObjectTracker
from mark.vision.types import (
    Bbox,
    DetectionKind,
    DetectionResult,
    Frame,
    FrameEvent,
    FrameSource,
    TrackingState,
    TrajectoryPoint,
    VisionAnalysis,
    VisionRuntimeStatus,
)


class VisionRuntime:
    """Bounded Vision Runtime pipeline.

    The runtime runs a capture loop (if configured with a real source),
    feeds frames through processing → tracking → temporal, and makes
    results available via query APIs.

    Cancellation : call ``cancel()`` or ``stop()`` to terminate the loop.
    Resource cleanup : all threads/subprocesses are released on stop.
    """

    def __init__(self, config: VisionConfig | None = None) -> None:
        self.config = config or VisionConfig()

        # Queues
        self._frame_queue = BoundedFrameQueue(
            maxlen=self.config.max_frame_queue,
            max_age_seconds=self.config.max_age_seconds,
        )
        self._detection_queue = BoundedDetectionQueue(
            maxlen=self.config.max_detection_queue,
        )
        self._event_queue = BoundedEventQueue(
            maxlen=self.config.max_event_queue,
        )

        # Trackers / analyzers
        self._tracker = ObjectTracker(
            max_tracks=self.config.max_active_tracks,
            ttl_seconds=self.config.track_ttl_seconds,
            max_trajectory_points=self.config.max_trajectory_points,
            max_appearances=self.config.max_appearances,
        )
        self._temporal = TemporalAnalyzer(
            max_history=self.config.max_temporal_history,
            max_events=self.config.max_temporal_events,
        )

        # Trajectory store (bounded per-track)
        self._trajectory_store = BoundedTrajectoryStore(
            default_maxlen=self.config.max_trajectory_points,
        )

        # Detection backends (capabilities gated)
        self._object_detector: DetectionBackend | None = None
        self._person_detector: DetectionBackend | None = None
        self._ocr: DetectionBackend | None = None
        self._init_detectors()

        # Acquisition source
        self._source: FrameSourceBase | None = None

        # Internal state
        self._running = False
        self._task: asyncio.Task | None = None
        self._stopped_event = asyncio.Event()
        self._frame_index = 0
        self._started_at: float = 0.0
        self._last_frame_time: float = 0.0
        self._error_count: int = 0

        # Callbacks
        self.on_frame: Callable[[Frame], None] | None = None
        self.on_analysis: Callable[[VisionAnalysis], None] | None = None
        self.on_event: Callable[[FrameEvent], None] | None = None

    # ── factory helpers ──────────────────────────────────────

    def _init_detectors(self) -> None:
        if self.config.enable_object_detection:
            self._object_detector = build_object_detector()
        if self.config.enable_person_detection:
            self._person_detector = build_person_detector()
        if self.config.enable_ocr:
            from mark.vision.processing import build_ocr as _build_ocr
            self._ocr = _build_ocr()

    def _build_source(self, source_type: str) -> FrameSourceBase:
        src_cfg = dict(self.config.source_config)
        cfg = AcquisitionConfig(
            source=FrameSource(source_type),
            extra=src_cfg,
        )
        if source_type == "image":
            return ImageSource(cfg)
        elif source_type == "screenshot":
            return ScreenshotSource(cfg)
        elif source_type == "screen":
            return ScreenSource(cfg)
        elif source_type == "camera":
            return CameraSource(cfg)
        elif source_type == "rtsp":
            return RTSPSource(cfg)
        raise ValueError(f"Unknown source type: {source_type}")

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self, source_type: str, **kwargs: Any) -> bool:
        """Start the vision pipeline.

        Returns True if the source connected successfully.
        """
        if self._running:
            return True
        self._running = True
        self._stopped_event.clear()
        self._started_at = time.time()
        self._source = self._build_source(source_type)
        if not await self._source.start():
            self._running = False
            return False
        self._task = asyncio.create_task(self._capture_loop())
        return True

    async def stop(self) -> None:
        """Stop the runtime and release resources."""
        self._running = False
        self._stopped_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._source is not None:
            await self._source.stop()
            self._source = None

    async def cancel(self) -> None:
        """Cancel the runtime (alias for stop)."""
        await self.stop()

    async def reconnect(self, attempts: int | None = None) -> bool:
        """Attempt to reconnect the source."""
        if self._source is None:
            return False
        return await self._source.reconnect(attempts)

    def status(self) -> VisionRuntimeStatus:
        return VisionRuntimeStatus(
            is_running=self._running,
            source_type=self._source.config.source.value if self._source else "",
            frame_count=self._frame_index,
            active_tracks=self._tracker.track_count,
            stale_tracks_cleaned=0,
            total_events=self._temporal.state.event_count,
            errors=self._error_count,
            last_frame_time=self._last_frame_time,
            started_at=self._started_at,
        )

    # ── internal loop ────────────────────────────────────────────

    async def _capture_loop(self) -> None:
        """Main loop: acquire → process → track → temporal."""
        try:
            while self._running and not self._stopped_event.is_set():
                try:
                    frame = await self._acquire_frame()
                    if frame is None:
                        await asyncio.sleep(0.1)
                        continue
                    self._frame_index += 1
                    self._last_frame_time = time.time()
                    if self.on_frame is not None:
                        self.on_frame(frame)

                    analysis = await self._process_frame(frame)
                    if self.on_analysis is not None:
                        self.on_analysis(analysis)

                except Exception:
                    self._error_count += 1
                    if self.config.sampling_interval > 0:
                        await asyncio.sleep(self.config.sampling_interval)
                    else:
                        await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    async def _acquire_frame(self) -> Frame | None:
        """Try to acquire a single frame from the source."""
        if self._source is None:
            return None
        try:
            frame = await self._source.acquire_frame()
            if frame is not None:
                await self._frame_queue.put(frame)
                self._fire_frame_event(frame)
            return frame
        except Exception:
            self._error_count += 1
            return None

    async def _process_frame(self, frame: Frame) -> VisionAnalysis:
        """Full processing pipeline for one frame."""
        t0 = time.time()
        detections: list[DetectionResult] = []

        # Object detection
        if self.config.enable_object_detection and self._object_detector:
            results = self._object_detector.detect(frame.raw, frame.width, frame.height)
            detections.extend(results)

        # Person detection
        if self.config.enable_person_detection and self._person_detector:
            results = self._person_detector.detect(frame.raw, frame.width, frame.height)
            detections.extend(results)

        # OCR
        text_blocks: list[dict[str, Any]] = []
        if self.config.enable_ocr and self._ocr:
            try:
                text_blocks = self._ocr.ocr(frame.raw, frame.width, frame.height)
            except AttributeError:
                pass  # _ocr might be DetectionBackend, not OCRBackend

        # Tracking
        if self.config.enable_tracking:
            self._tracker.process_frame(self._frame_index, detections)
            for d in detections:
                if d.track_id:
                    await self._trajectory_store.add(d.track_id, {
                        "frame_index": self._frame_index,
                        "center_x": d.bbox.center_x,
                        "center_y": d.bbox.center_y,
                        "timestamp": frame.timestamp,
                    })

        # Temporal analysis
        temporal_events: list[FrameEvent] = []
        if self.config.enable_temporal:
            temporal_events = self._temporal.process_frame(
                self._frame_index, detections,
            )
            for ev in temporal_events:
                await self._event_queue.put(ev)
                if self.on_event is not None:
                    self.on_event(ev)

        # Clean up stale tracks
        cleaned = self._tracker.cleanup_stale()

        elapsed_ms = (time.time() - t0) * 1000
        analysis = VisionAnalysis(
            frame_index=self._frame_index,
            timestamp=frame.timestamp,
            source=frame.source,
            detections=detections,
            text_blocks=text_blocks,
            frame_count=self._frame_index,
            processing_time_ms=elapsed_ms,
            extra={"tracks_cleaned": cleaned},
        )
        return analysis

    # ── query API ────────────────────────────────────────────────

    async def get_recent_detections(self, n: int = 20) -> list[DetectionResult]:
        return (await self._detection_queue.drain())[:n]

    async def get_recent_events(self, n: int = 20) -> list[FrameEvent]:
        return (await self._event_queue.drain())[:n]

    def get_active_tracks(self) -> dict[str, TrackingState]:
        return self._tracker.get_tracks()

    def get_present_tracks(self) -> list[str]:
        return self._tracker.get_present_tracks()

    def get_trajectory(self, track_id: str) -> list[TrajectoryPoint]:
        return self._tracker.get_trajectory(track_id)

    def get_appearances(self, track_id: str) -> list[dict[str, Any]]:
        return self._tracker.get_appearances(track_id)

    def get_capabilities(self) -> dict[str, bool]:
        return detect_capabilities(b"", 640, 480)

    def _fire_frame_event(self, frame: Frame) -> None:
        if self.on_frame is not None:
            try:
                self.on_frame(frame)
            except Exception:
                traceback.print_exc()


# ── convenience factory ────────────────────────────────────────────

def create_runtime(
    source_type: str,
    config: VisionConfig | None = None,
    **kwargs: Any,
) -> VisionRuntime:
    """Create a VisionRuntime with the given source type.

    Parameters
    ----------
    source_type : str
        One of 'image', 'screenshot', 'screen', 'camera', 'rtsp'.
    config : VisionConfig, optional
        Override bounded limits.
    **kwargs : Any
        Passed to ``source_config`` (e.g. rtsp_url, camera_id, file_path).
    """
    cfg = (config or VisionConfig())
    src_cfg = kwargs.copy()
    src_cfg["type"] = source_type
    cfg.source_config.update(src_cfg)
    runtime = VisionRuntime(cfg)
    return runtime
