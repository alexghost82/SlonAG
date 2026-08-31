"""Vision Runtime — core types.

Data classes and enums for the bounded Vision Runtime.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class FrameSource(str, Enum):
    IMAGE_FILE = "image"
    SCREENSHOT = "screenshot"
    SCREEN = "screen"
    CAMERA = "camera"
    RTSP_STREAM = "rtsp"


class DetectionKind(str, Enum):
    OBJECT = "object"
    PERSON = "person"
    TEXT = "text"


class TrackEvent(str, Enum):
    APPEARANCE = "appearance"
    DISAPPEARANCE = "disappearance"
    CONTINUITY = "continuity"


@dataclass(frozen=True)
class Bbox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center_x(self) -> float:
        return (self.x_min + self.x_max) / 2

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2


@dataclass
class Frame:
    index: int
    timestamp: float = field(default_factory=time.time)
    source: FrameSource = FrameSource.IMAGE_FILE
    raw: bytes = b""
    width: int = 0
    height: int = 0
    stream_url: str = ""
    camera_id: int = 0
    file_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def age(self) -> float:
        return time.time() - self.timestamp


@dataclass
class DetectionResult:
    kind: DetectionKind
    label: str
    confidence: float
    bbox: Bbox
    track_id: str | None = None
    frame_index: int = 0


@dataclass
class TrajectoryPoint:
    timestamp: float
    track_id: str
    center_x: float
    center_y: float
    width: float
    height: float


@dataclass
class TrackingState:
    track_id: str
    kind: DetectionKind
    label: str
    first_seen: float
    last_seen: float
    ttl_seconds: float = 30.0
    max_trajectory_points: int = 50
    max_appearances: int = 100

    trajectory: list[TrajectoryPoint] = field(default_factory=list)
    appearances: list[dict[str, Any]] = field(default_factory=list)
    is_present: bool = True

    @property
    def age(self) -> float:
        return self.last_seen - self.first_seen

    @property
    def stale(self) -> bool:
        return time.time() - self.last_seen > self.ttl_seconds

    def add_appearance(self, frame_index: int, bbox: Bbox, confidence: float) -> None:
        self.appearances.append({
            "frame_index": frame_index,
            "bbox": {"x_min": bbox.x_min, "y_min": bbox.y_min,
                     "x_max": bbox.x_max, "y_max": bbox.y_max},
            "confidence": confidence,
            "timestamp": time.time(),
        })
        if len(self.appearances) > self.max_appearances:
            self.appearances.pop(0)

    def add_trajectory_point(self, frame_index: int, bbox: Bbox) -> None:
        pt = TrajectoryPoint(
            timestamp=time.time(), track_id=self.track_id,
            center_x=bbox.center_x, center_y=bbox.center_y,
            width=bbox.width, height=bbox.height,
        )
        self.trajectory.append(pt)
        if len(self.trajectory) > self.max_trajectory_points:
            self.trajectory.pop(0)


@dataclass
class FrameEvent:
    event_type: TrackEvent
    track_id: str
    timestamp: float
    description: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionAnalysis:
    frame_index: int
    timestamp: float
    source: FrameSource
    detections: list[DetectionResult] = field(default_factory=list)
    text_blocks: list[dict[str, Any]] = field(default_factory=list)
    frame_count: int = 0
    processing_time_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionRuntimeStatus:
    is_running: bool = False
    source_type: str = ""
    frame_count: int = 0
    active_tracks: int = 0
    stale_tracks_cleaned: int = 0
    total_events: int = 0
    errors: int = 0
    last_frame_time: float = 0.0
    started_at: float = 0.0
