"""Pytest fixtures for Vision Runtime E2E testing.

Provides deterministic test images, videos, and RTSP fixtures.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest

from mark.vision.fixtures.image import (
    create_test_image,
    create_moving_object_image,
    create_grid_image,
    create_text_image,
    create_person_roi,
)
from mark.vision.fixtures.video import create_test_video
from mark.vision.fixtures.rtsp import RTSPFixture, create_rtsp_fixture
from mark.vision.config import VisionConfig
from mark.vision.runtime import VisionRuntime, create_runtime


@pytest.fixture
def test_image_path(tmp_path: Path) -> Path:
    """Path to a single test image."""
    p = tmp_path / "test_image.png"
    create_test_image(path=str(p))
    return p


@pytest.fixture
def test_image_bytes(test_image_path: Path) -> bytes:
    return test_image_path.read_bytes()


@pytest.fixture
def moving_image_paths(tmp_path: Path) -> list[Path]:
    """Paths to a sequence of images with a moving rectangle."""
    p = tmp_path / "moving"
    frames = create_moving_object_image(path=str(p))
    return [p / f"frame_{i:04d}.png" for i in range(len(frames))]


@pytest.fixture
def grid_image_path(tmp_path: Path) -> Path:
    """Path to a multi-object grid image."""
    p = tmp_path / "grid_image.png"
    create_grid_image(path=str(p))
    return p


@pytest.fixture
def text_image_path(tmp_path: Path) -> Path:
    """Path to an image with test text."""
    p = tmp_path / "text_image.png"
    create_text_image(path=str(p))
    return p


@pytest.fixture
def person_roi_path(tmp_path: Path) -> Path:
    """Path to an image with person-sized ROI."""
    p = tmp_path / "person_roi.png"
    create_person_roi(path=str(p))
    return p


@pytest.fixture
def test_video_path(tmp_path: Path) -> Path:
    """Path to a test video (MP4)."""
    p = tmp_path / "test_video.mp4"
    create_test_video(path=str(p))
    return p


@pytest.fixture
async def rtsp_fixture() -> RTSPFixture:
    """Start a mock RTSP server for testing."""
    fixture = create_rtsp_fixture(num_frames=20)
    await fixture.start()
    yield fixture
    await fixture.stop()


@pytest.fixture
async def vision_image_runtime(tmp_path: Path, test_image_path: Path) -> VisionRuntime:
    """VisionRuntime configured with an image source."""
    config = VisionConfig(
        enable_object_detection=True,
        enable_person_detection=True,
        enable_ocr=True,
        enable_tracking=True,
        enable_temporal=True,
    )
    rt = create_runtime(
        "image",
        config=config,
        file_path=str(test_image_path),
    )
    await rt.start("image", file_path=str(test_image_path))
    yield rt
    await rt.stop()


@pytest.fixture
async def vision_rtsp_runtime(tmp_path: Path, rtsp_fixture: RTSPFixture) -> VisionRuntime:
    """VisionRuntime configured with an RTSP source."""
    config = VisionConfig(
        enable_object_detection=True,
        enable_person_detection=True,
        enable_ocr=True,
        enable_tracking=True,
        enable_temporal=True,
    )
    rt = create_runtime(
        "rtsp",
        config=config,
        rtsp_url=rtsp_fixture.url,
    )
    await rt.start("rtsp", rtsp_url=rtsp_fixture.url)
    yield rt
    await rt.stop()


@pytest.fixture
def bounded_config() -> VisionConfig:
    """Default bounded configuration for tests."""
    return VisionConfig(
        max_frame_queue=10,
        max_detection_queue=20,
        max_event_queue=50,
        max_active_tracks=50,
        track_ttl_seconds=5.0,
        max_trajectory_points=20,
        max_appearances=50,
        max_temporal_history=50,
        max_temporal_events=100,
    )
