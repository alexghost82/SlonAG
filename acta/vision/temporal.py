"""Vision Runtime — temporal state and multi-frame reasoning.

Provides bounded temporal history, multi-frame reasoning, event
detection (appearance, disappearance, motion), and temporal state
queries for AgentLoop consumption.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from acta.vision.types import (
    DetectionResult,
    TrackEvent,
)
from acta.vision.types import (
    FrameEvent as Event,
)


@dataclass
class TemporalState:
    """Bounded temporal state for multi-frame reasoning."""

    max_history: int = 100  # max frames of history
    history: list[dict[str, Any]] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    max_events: int = 500
    # Track history for trajectory queries
    _trajectory_cache: dict[str, list[dict[str, float]]] = field(default_factory=dict)
    _max_trajectory_points: int = 200

    def add_frame(self, frame_index: int, detections: list[DetectionResult]) -> None:
        # Extract labels and track_ids from detections
        labels = [d.label for d in detections]
        self.history.append({
            "frame_index": frame_index,
            "timestamp": time.time(),
            "detection_count": len(detections),
            "labels": labels,
        })
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def add_event(self, event: Event) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events.pop(0)

    def add_trajectory_point(self, track_id: str, cx: float, cy: float) -> None:
        if track_id not in self._trajectory_cache:
            self._trajectory_cache[track_id] = []
        self._trajectory_cache[track_id].append({"cx": cx, "cy": cy})
        if len(self._trajectory_cache[track_id]) > self._max_trajectory_points:
            self._trajectory_cache[track_id].pop(0)

    @property
    def frame_count(self) -> int:
        return len(self.history)

    @property
    def event_count(self) -> int:
        return len(self.events)


class TemporalAnalyzer:
    """Multi-frame reasoning and event detection.

    Observes consecutive frame detections and generates higher-level
    events like "object moved left", "person appeared", etc.
    """

    def __init__(self, max_history: int = 100, max_events: int = 500) -> None:
        self.state = TemporalState(max_history=max_history, max_events=max_events)

    def process_frame(
        self, frame_index: int, detections: list[DetectionResult],
    ) -> list[Event]:
        """Process detections for one frame and return new events."""
        self.state.add_frame(frame_index, detections)
        events: list[Event] = []

        # Detect appearance events (new labels not seen in recent history)
        seen_labels = self._get_recent_labels()
        new_labels = {d.label for d in detections if d.label not in seen_labels}
        for label in new_labels:
            events.append(Event(
                event_type=TrackEvent.APPEARANCE,
                track_id=f"label_{label}",
                timestamp=time.time(),
                description=f"New object label '{label}' detected",
            ))

        # Detect motion events for tracked detections
        for d in detections:
            if d.track_id:
                # Record trajectory point from current detection
                self.state.add_trajectory_point(
                    d.track_id,
                    d.bbox.center_x,
                    d.bbox.center_y,
                )
                prev_points = self._get_trajectory(d.track_id)
                if len(prev_points) >= 2:
                    pt1 = prev_points[-2]
                    pt2 = prev_points[-1]
                    dx = pt2["cx"] - pt1["cx"]
                    if abs(dx) > 0.1:
                        direction = "right" if dx > 0 else "left"
                        events.append(Event(
                            event_type=TrackEvent.CONTINUITY,
                            track_id=d.track_id,
                            timestamp=time.time(),
                            description=f"Object {d.track_id} moving {direction}",
                            extra={"direction": direction, "delta": dx},
                        ))

        return events

    def query_recent_frames(self, n: int = 10) -> list[dict[str, Any]]:
        return self.state.history[-n:]

    def query_recent_events(self, n: int = 10, event_type: TrackEvent | None = None) -> list[Event]:
        if event_type:
            return [e for e in self.state.events[-n:] if e.event_type == event_type]
        return list(self.state.events[-n:])

    def get_full_history(self) -> list[dict[str, Any]]:
        return list(self.state.history)

    def _get_recent_labels(self, window: int = 10) -> set[str]:
        """Return labels seen in recent frames."""
        recent = self.state.history[-window:]
        labels: set[str] = set()
        for entry in recent:
            if "labels" in entry:
                labels.update(entry["labels"])
        return labels

    def _get_trajectory(self, track_id: str) -> list[dict[str, float]]:
        """Return trajectory points for a track ID from the cache."""
        return list(self.state._trajectory_cache.get(track_id, []))
