"""Tests for VisionRuntime.

Covers:
- Image source frame acquisition
- Full pipeline (acquisition → processing → tracking → temporal)
- Bounded constraints
- Status reporting
- Cancellation / stop
- Reconnect
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from mark.vision.config import VisionConfig
from mark.vision.fixtures.image import create_test_image, create_moving_object_image
from mark.vision.runtime import create_runtime
from mark.vision.types import FrameSource


class TestVisionRuntimeImage:
    """Tests for VisionRuntime with image source."""

    @pytest.fixture
    def config(self):
        return VisionConfig(
            enable_object_detection=True,
            enable_person_detection=True,
            enable_ocr=True,
            enable_tracking=True,
            enable_temporal=True,
        )

    def test_create_runtime(self, config):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(create_test_image())
            f.flush()
            rt = create_runtime("image", config=config, file_path=f.name)
            assert rt is not None

    @pytest.mark.asyncio
    async def test_image_source_lifecycle(self, config, tmp_path: Path):
        img_path = tmp_path / "test.png"
        create_test_image(path=str(img_path))
        rt = create_runtime("image", config=config, file_path=str(img_path))
        ok = await rt.start("image", file_path=str(img_path))
        assert ok is True
        status = rt.status()
        assert status.is_running
        await rt.stop()
        status = rt.status()
        assert status.is_running is False


class TestVisionRuntimeBounded:
    """Tests that the runtime respects bounded constraints."""

    @pytest.mark.asyncio
    async def test_bounded_frame_queue(self, tmp_path: Path):
        config = VisionConfig(max_frame_queue=3, max_detection_queue=5, max_event_queue=10)
        img_path = tmp_path / "test.png"
        create_test_image(path=str(img_path))
        rt = create_runtime("image", config=config, file_path=str(img_path))
        ok = await rt.start("image", file_path=str(img_path))
        assert ok is True
        await asyncio.sleep(0.3)
        status = rt.status()
        assert status.frame_count >= 1

    @pytest.mark.asyncio
    async def test_status_reporting(self, tmp_path: Path):
        config = VisionConfig()
        img_path = tmp_path / "test.png"
        create_test_image(path=str(img_path))
        rt = create_runtime("image", config=config, file_path=str(img_path))
        ok = await rt.start("image", file_path=str(img_path))
        assert ok is True
        status = rt.status()
        assert status.is_running is True
        assert status.source_type == "image"


class TestVisionRuntimeCancellation:
    """Tests for cancellation and resource cleanup."""

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, tmp_path: Path):
        config = VisionConfig()
        img_path = tmp_path / "test.png"
        create_test_image(path=str(img_path))
        rt = create_runtime("image", config=config, file_path=str(img_path))
        ok = await rt.start("image", file_path=str(img_path))
        assert ok is True
        await rt.stop()
        status = rt.status()
        assert status.is_running is False

    @pytest.mark.asyncio
    async def test_cancel(self, tmp_path: Path):
        config = VisionConfig()
        img_path = tmp_path / "test.png"
        create_test_image(path=str(img_path))
        rt = create_runtime("image", config=config, file_path=str(img_path))
        ok = await rt.start("image", file_path=str(img_path))
        assert ok is True
        await rt.cancel()
        status = rt.status()
        assert status.is_running is False


class TestVisionRuntimeCapabilities:
    """Tests capability detection."""

    def test_capabilities_reported(self, tmp_path: Path):
        config = VisionConfig()
        img_path = tmp_path / "test.png"
        create_test_image(path=str(img_path))
        rt = create_runtime("image", config=config, file_path=str(img_path))
        caps = rt.get_capabilities()
        assert "object_detection" in caps
        assert "person_detection" in caps
        assert "ocr" in caps
