"""Deterministic test fixtures for Vision Runtime.

All fixtures are reproducible — they use fixed seeds and simple geometry
so detection/tracking tests don't depend on external model weights.
"""

from acta.vision.fixtures.image import (
    create_grid_image,
    create_moving_object_image,
    create_person_roi,
    create_test_image,
    create_text_image,
)
from acta.vision.fixtures.video import (
    create_test_video,
)

try:
    from acta.vision.fixtures.rtsp import (
        RTSPFixture,
        create_rtsp_fixture,
    )
except ImportError:
    # cv2/rtsp unavailable without OpenCV installed
    pass

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
