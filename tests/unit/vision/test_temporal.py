"""Tests for TemporalAnalyzer.

Covers:
- Bounded temporal history
- Multi-frame event detection
- Event queries
"""

import time

import pytest

from acta.vision.temporal import TemporalAnalyzer
from acta.vision.types import Bbox, DetectionResult, DetectionKind


class TestTemporalAnalyzer:
    """Tests for TemporalAnalyzer."""

    def test_bounded_history(self):
        analyzer = TemporalAnalyzer(max_history=5)
        for i in range(20):
            analyzer.process_frame(i, [])
        assert analyzer.state.frame_count == 5  # bounded

    def test_bounded_events(self):
        analyzer = TemporalAnalyzer(max_events=3)
        for i in range(20):
            analyzer.process_frame(i, [])
        assert analyzer.state.event_count <= 3  # bounded

    def test_add_frame(self):
        analyzer = TemporalAnalyzer()
        det = DetectionResult(kind=DetectionKind.OBJECT, label="box", confidence=0.9, bbox=Bbox(0, 0, 1, 1))
        analyzer.process_frame(1, [det])
        assert analyzer.state.frame_count >= 1
        recent = analyzer.query_recent_frames(1)
        assert len(recent) >= 1

    def test_event_query(self):
        analyzer = TemporalAnalyzer()
        analyzer.process_frame(1, [])
        events = analyzer.query_recent_events(10)
        assert isinstance(events, list)

    def test_full_history(self):
        analyzer = TemporalAnalyzer()
        for i in range(5):
            analyzer.process_frame(i, [])
        hist = analyzer.get_full_history()
        assert len(hist) == 5
