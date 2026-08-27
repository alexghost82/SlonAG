"""Deterministic test fixtures for Vision Runtime.

All fixtures are reproducible — they use fixed seeds and simple geometry
so detection/tracking tests don't depend on external model weights.
"""

from mark.vision.fixtures.image import (
    create_test_image,
    create_moving_object_image,
    create_grid_image,
    create_text_image,
    create_person_roi,
)
from mark.vision.fixtures.video import (
    create_test_video,
)
from mark.vision.fixtures.rtsp import (
    create_rtsp_fixture,
    RTSPFixture,
)

__all__ = [
    "create_test_image",
    "create_moving_object_image",
    "create_grid_image",
    "create_text_image",
    "create_person_roi",
    "create_test_video",
    "create_rtsp_fixture",
    "RTSPFixture",
]
