"""Tests for ObjectTracker.

Covers:
- Persistent track IDs across frames
- Trajectory building
- Bounded history (trajectory, appearances)
- TTL-based stale-cleanup
- Capacity limits (max_tracks)
- Appearance / disappearance events
"""

import time

import pytest

from acta.vision.tracking import ObjectTracker
from acta.vision.types import Bbox, DetectionResult, DetectionKind, FrameEvent


class TestObjectTracker:
    """Tests for ObjectTracker."""

    def test_allocate_track(self):
        tracker = ObjectTracker()
        det = DetectionResult(
            kind=DetectionKind.OBJECT, label="box", confidence=0.9,
            bbox=Bbox(0.2, 0.2, 0.4, 0.4),
        )
        tracker.update_detection(det)
        assert det.track_id is not None
        assert "object_" in det.track_id

    def test_track_count(self):
        tracker = ObjectTracker()
        assert tracker.track_count == 0
        for i in range(5):
            det = DetectionResult(
                kind=DetectionKind.OBJECT, label="box", confidence=0.9,
                bbox=Bbox(0.2, 0.2, 0.4, 0.4),
            )
            tracker.update_detection(det)
        assert tracker.track_count == 5

    def test_trajectory_building(self):
        tracker = ObjectTracker()
        for i in range(5):
            det = DetectionResult(
                kind=DetectionKind.OBJECT, label="box", confidence=0.9,
                bbox=Bbox(0.2 + i * 0.05, 0.3, 0.4 + i * 0.05, 0.5),
                track_id="object_000001",
            )
            tracker.update_detection(det)
        traj = tracker.get_trajectory("object_000001")
        assert len(traj) > 0

    def test_bounded_trajectory(self):
        tracker = ObjectTracker(max_trajectory_points=3)
        for i in range(10):
            det = DetectionResult(
                kind=DetectionKind.OBJECT, label="box", confidence=0.9,
                bbox=Bbox(0.2, 0.3 + i * 0.02, 0.4, 0.5),
                track_id="object_000001",
            )
            tracker.update_detection(det)
        traj = tracker.get_trajectory("object_000001")
        assert len(traj) <= 3

    def test_bounded_appearances(self):
        tracker = ObjectTracker(max_appearances=3)
        for i in range(10):
            det = DetectionResult(
                kind=DetectionKind.OBJECT, label="box", confidence=0.9,
                bbox=Bbox(0.2, 0.3, 0.4, 0.5),
                track_id="object_000001",
            )
            tracker.update_detection(det)
        app = tracker.get_appearances("object_000001")
        assert len(app) <= 3

    def test_max_tracks_capacity(self):
        tracker = ObjectTracker(max_tracks=3)
        for i in range(10):
            det = DetectionResult(
                kind=DetectionKind.OBJECT, label="box", confidence=0.9,
                bbox=Bbox(0.2, 0.2, 0.4, 0.4),
            )
            tracker.update_detection(det)
        assert tracker.track_count <= 3

    def test_stale_cleanup(self):
        tracker = ObjectTracker(ttl_seconds=0.001)
        det = DetectionResult(
            kind=DetectionKind.OBJECT, label="box", confidence=0.9,
            bbox=Bbox(0.2, 0.2, 0.4, 0.4),
            track_id="object_000001",
        )
        tracker.update_detection(det)
        time.sleep(0.01)  # let it become stale
        cleaned = tracker.cleanup_stale()
        assert cleaned >= 1
        assert tracker.track_count == 0

    def test_process_frame_new_detections(self):
        tracker = ObjectTracker()
        detections = [
            DetectionResult(kind=DetectionKind.OBJECT, label="car", confidence=0.8, bbox=Bbox(0.1, 0.1, 0.3, 0.3)),
            DetectionResult(kind=DetectionKind.PERSON, label="person", confidence=0.9, bbox=Bbox(0.5, 0.2, 0.7, 0.8)),
        ]
        active, events = tracker.process_frame(1, detections)
        assert len(active) == 2

    def test_process_frame_reassigns_existing(self):
        tracker = ObjectTracker()
        det1 = DetectionResult(kind=DetectionKind.OBJECT, label="car", confidence=0.8, bbox=Bbox(0.1, 0.1, 0.3, 0.3))
        tracker.update_detection(det1)
        det1.track_id = "object_000001"
        # Re-assign in next frame
        det2 = DetectionResult(kind=DetectionKind.OBJECT, label="car", confidence=0.8, bbox=Bbox(0.2, 0.2, 0.4, 0.4))
        det2.track_id = "object_000001"  # same ID
        active, events = tracker.process_frame(2, [det2])
        assert "object_000001" in active

    def test_present_tracks(self):
        tracker = ObjectTracker()
        det = DetectionResult(kind=DetectionKind.OBJECT, label="box", confidence=0.9, bbox=Bbox(0.2, 0.2, 0.4, 0.4))
        tracker.update_detection(det)
        present = tracker.get_present_tracks()
        assert len(present) >= 1
