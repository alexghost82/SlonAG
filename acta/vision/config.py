"""Vision Runtime — bounded configuration.

All limits are explicit so the runtime never grows unbounded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VisionConfig:
    """Bounded configuration for the Vision Runtime.

    Attributes
    ----------
    max_frame_queue : int
        Maximum frames in the acquisition queue (default 30).
    max_age_seconds : float
        Frames older than this are dropped (default 5.0).
    max_detection_queue : int
        Maximum pending detections (default 60).
    max_event_queue : int
        Maximum pending events (default 200).
    max_active_tracks : int
        Maximum concurrent tracks (default 100).
    track_ttl_seconds : float
        Per-track inactivity TTL before stale-cleanup (default 30.0).
    max_trajectory_points : int
        Max trajectory points per track (default 50).
    max_appearances : int
        Max appearance history per track (default 100).
    max_temporal_history : int
        Max frames of temporal history (default 100).
    max_temporal_events : int
        Max temporal events stored (default 500).
    sampling_interval : float
        Seconds between frame processing (default 0.0 = process all).
    source_config : dict
        Source-specific configuration.
    """

    max_frame_queue: int = 30
    max_age_seconds: float = 5.0
    max_detection_queue: int = 60
    max_event_queue: int = 200
    max_active_tracks: int = 100
    track_ttl_seconds: float = 30.0
    max_trajectory_points: int = 50
    max_appearances: int = 100
    max_temporal_history: int = 100
    max_temporal_events: int = 500
    sampling_interval: float = 0.0
    source_config: dict[str, Any] = field(default_factory=dict)

    # Capability toggles
    enable_object_detection: bool = True
    enable_person_detection: bool = True
    enable_ocr: bool = True
    enable_tracking: bool = True
    enable_temporal: bool = True

    @property
    def all_capabilities(self) -> list[str]:
        caps = []
        if self.enable_object_detection:
            caps.append("object_detection")
        if self.enable_person_detection:
            caps.append("person_detection")
        if self.enable_ocr:
            caps.append("ocr")
        if self.enable_tracking:
            caps.append("tracking")
        if self.enable_temporal:
            caps.append("temporal")
        return caps

    def with_source(self, source_type: str, **kwargs: Any) -> VisionConfig:
        """Return a copy with source_config updated."""
        import copy
        c = copy.copy(self)
        c.source_config["type"] = source_type
        c.source_config.update(kwargs)
        return c
