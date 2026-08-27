"""Vision Runtime — bounded multi-object tracking.

Persistent track IDs, trajectory, TTL-based stale-cleanup,
appearance/disappearance events, bounded history per track.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from mark.vision.types import (
    Bbox, DetectionResult, DetectionKind, FrameEvent, TrackEvent,
    TrackingState, TrajectoryPoint,
)


class ObjectTracker:
    """Bounded multi-object tracker with persistent IDs and TTL.

    Attributes
    ----------
    max_tracks : int
        Maximum number of active tracks at any time.
    ttl_seconds : float
        After this many seconds of inactivity a track is considered stale
        and is removed.
    max_trajectory_points : int
        Maximum trajectory points per track.
    max_appearances : int
        Maximum appearance history per track.
    """

    def __init__(
        self,
        max_tracks: int = 100,
        ttl_seconds: float = 30.0,
        max_trajectory_points: int = 50,
        max_appearances: int = 100,
    ) -> None:
        self.max_tracks = max_tracks
        self.ttl_seconds = ttl_seconds
        self.max_trajectory_points = max_trajectory_points
        self.max_appearances = max_appearances
        self._state: dict[str, TrackingState] = {}
        self._next_id = 0

    # ── API ──────────────────────────────────────────────────────

    def process_frame(
        self, frame_index: int, detections: list[DetectionResult],
    ) -> tuple[dict[str, TrackingState], list[FrameEvent]]:
        """Process detections for one frame.

        Returns
        -------
        (active_tracks, events)
        """
        now = time.time()
        new_detections: dict[str, DetectionResult] = {}
        for d in detections:
            if d.track_id is not None and d.track_id in self._state:
                # Re-assign existing track
                ts = self._state[d.track_id]
                ts.last_seen = now
                ts.is_present = True
                ts.add_appearance(frame_index, d.bbox, d.confidence)
                ts.add_trajectory_point(frame_index, d.bbox)
                new_detections[d.track_id] = d
            elif d.track_id is None:
                # New detection — assign new track if capacity allows
                if len(self._state) < self.max_tracks:
                    tid = self._allocate_id(d.kind, d.label)
                    d.track_id = tid
                    new_detections[tid] = d
            else:
                # Existing track ID not matched — keep it as is
                new_detections[d.track_id] = d

        # Mark non-matched present tracks as stale
        events: list[FrameEvent] = []
        stale_ids: list[str] = []
        for tid, ts in self._state.items():
            if tid not in new_detections:
                ts.is_present = False
                if ts.ttl_seconds and (now - ts.last_seen) > ts.ttl_seconds:
                    stale_ids.append(tid)
                    events.append(FrameEvent(
                        event_type=TrackEvent.DISAPPEARANCE,
                        track_id=tid,
                        timestamp=now,
                        description=f"Track {tid} disappeared (stale)",
                    ))
                else:
                    events.append(FrameEvent(
                        event_type=TrackEvent.CONTINUITY,
                        track_id=tid,
                        timestamp=now,
                        description=f"Track {tid} missing for {now - ts.last_seen:.1f}s",
                    ))

        # Remove stale tracks
        for tid in stale_ids:
            del self._state[tid]

        # Return current active state
        active = dict(self._state)

        # Generate appearance events for new detections
        for tid, d in new_detections.items():
            if tid not in self._state:
                pass  # already handled by the constructor check

        return active, events

    def update_detection(self, result: DetectionResult) -> None:
        """Update an existing detection with tracking metadata."""
        if result.track_id is None:
            if len(self._state) >= self.max_tracks:
                return  # capacity reached
            result.track_id = self._allocate_id(result.kind, result.label)

    def get_track(self, track_id: str) -> TrackingState | None:
        return self._state.get(track_id)

    def get_tracks(self) -> dict[str, TrackingState]:
        return dict(self._state)

    def get_present_tracks(self) -> list[str]:
        now = time.time()
        return [tid for tid, ts in self._state.items() if not ts.stale and ts.is_present]

    def cleanup_stale(self) -> int:
        now = time.time()
        before = len(self._state)
        stale = [tid for tid, ts in self._state.items() if now - ts.last_seen > ts.ttl_seconds]
        for tid in stale:
            del self._state[tid]
        return before - len(self._state)

    def get_trajectory(self, track_id: str) -> list[TrajectoryPoint]:
        ts = self._state.get(track_id)
        return ts.trajectory if ts else []

    def get_appearances(self, track_id: str) -> list[dict[str, Any]]:
        ts = self._state.get(track_id)
        return ts.appearances if ts else []

    @property
    def track_count(self) -> int:
        return len(self._state)

    def _allocate_id(self, kind: DetectionKind, label: str) -> str:
        self._next_id += 1
        tid = f"{kind.value}_{self._next_id:06d}"
        self._state[tid] = TrackingState(
            track_id=tid,
            kind=kind,
            label=label,
            first_seen=time.time(),
            last_seen=time.time(),
            ttl_seconds=self.ttl_seconds,
            max_trajectory_points=self.max_trajectory_points,
            max_appearances=self.max_appearances,
        )
        return tid
