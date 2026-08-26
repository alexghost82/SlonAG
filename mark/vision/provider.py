"""Local VisionProvider with an injected engine.

Engines are wrapped behind ``VisionEngine``. This module does not download
models, capture screenshots, read API keys, or touch the network.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass, field
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
                f"Неподдерживаемый тип vision: {raw!r}",
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
                "загруженное vision-модель не разрешено, когда "
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
                    "snapshot temp path escaped temp_dir",
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


class RTSPSnapshot:
    """A captured frame from an RTSP stream with metadata."""

    def __init__(
        self,
        index: int,
        image: bytes,
        timestamp: float,
        stream_url: str,
        width: int = 0,
        height: int = 0,
    ) -> None:
        self.index = index
        self.image = image
        self.timestamp = timestamp
        self.stream_url = stream_url
        self.width = width
        self.height = height


class RTSPClient:
    """Minimal RTSP client that captures snapshots from a stream.
    
    Uses subprocess to call ffmpeg for reliable RTSP capture.
    """

    def __init__(self, stream_url: str) -> None:
        self.stream_url = stream_url
        self._running = False
        self._frame_index = 0
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_frame: Callable[[RTSPSnapshot], None] | None = None

    def set_frame_callback(self, callback: Callable[[RTSPSnapshot], None]) -> None:
        self._on_frame = callback

    def start_capture(self) -> None:
        """Start capturing frames in background thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="rtsp-capture")
        self._thread.start()

    def stop_capture(self) -> None:
        self._stop_event.set()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _capture_loop(self) -> None:
        """Capture frames using ffmpeg subprocess."""
        while not self._stop_event.is_set():
            try:
                result = self._capture_frame()
                if result is not None:
                    snap = RTSPSnapshot(
                        index=self._frame_index,
                        image=result["data"],
                        timestamp=time.time(),
                        stream_url=self.stream_url,
                        width=result.get("width", 0),
                        height=result.get("height", 0),
                    )
                    self._frame_index += 1
                    if self._on_frame is not None:
                        self._on_frame(snap)
                self._stop_event.wait(timeout=0.5)
            except Exception:
                self._stop_event.wait(timeout=1.0)

    def _capture_frame(self) -> dict[str, object] | None:
        """Capture a single frame using ffmpeg."""
        try:
            import subprocess
            proc = subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-y",
                    "-fflags", "nobuffer",
                    "-rtsp_transport", "tcp",
                    "-i", self.stream_url,
                    "-frames:v", "1",
                    "-f", "image2pipe",
                    "-vcodec", "mjpeg",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=10.0,
            )
            if proc.returncode == 0 and proc.stdout:
                return {"data": proc.stdout, "width": 0, "height": 0}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def capture_once(self) -> RTSPSnapshot | None:
        """Capture a single frame without background threading."""
        result = self._capture_frame()
        if result is None:
            return None
        snap = RTSPSnapshot(
            index=self._frame_index,
            image=result["data"],
            timestamp=time.time(),
            stream_url=self.stream_url,
            width=result.get("width", 0),
            height=result.get("height", 0),
        )
        self._frame_index += 1
        return snap


class VisionResult:
    """Structured vision analysis result with metadata."""

    def __init__(
        self,
        objects: list[dict[str, object]] | None = None,
        text: str = "",
        description: str = "",
        confidence: float = 0.0,
        frame_index: int = 0,
        source: str = "unknown",
        person_count: int = 0,
        trajectory_ids: list[str] | None = None,
    ) -> None:
        self.objects = objects or []
        self.text = text
        self.description = description
        self.confidence = confidence
        self.frame_index = frame_index
        self.source = source
        self.person_count = person_count
        self.trajectory_ids = trajectory_ids or []


@dataclass
class TrackingState:
    """Persistent tracking state for objects across frames."""

    track_id: str
    first_seen: float
    last_seen: float
    appearances: list[dict[str, object]] = field(default_factory=list)
    is_present: bool = True

    @property
    def age(self) -> float:
        return self.last_seen - self.first_seen


class TemporalVisionResult(VisionResult):
    """Vision result with temporal awareness across multiple frames."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tracking: dict[str, TrackingState] = {}

    def update_tracking(
        self, track_id: str, appearance: dict[str, object],
    ) -> None:
        if track_id in self.tracking:
            state = self.tracking[track_id]
            state.last_seen = time.time()
            state.appearances.append(appearance)
        else:
            self.tracking[track_id] = TrackingState(
                track_id=track_id,
                first_seen=time.time(),
                last_seen=time.time(),
                appearances=[appearance],
            )

    def get_present_objects(self) -> list[str]:
        """Return track IDs that are still present (seen within last 10s)."""
        now = time.time()
        return [
            tid for tid, state in self.tracking.items()
            if now - state.last_seen < 10.0
        ]

    def get_appearances(self, track_id: str) -> list[dict[str, object]]:
        return self.tracking.get(track_id, TrackingState(
            track_id=track_id, first_seen=0, last_seen=0
        )).appearances
