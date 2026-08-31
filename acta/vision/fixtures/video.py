"""Deterministic video fixtures.

Creates MP4 video files with known content for testing the frame
acquisition pipeline with video input.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def create_test_video(
    width: int = 640,
    height: int = 480,
    num_frames: int = 30,
    fps: float = 10.0,
    path: str | Path | None = None,
) -> Path:
    """Create a deterministic test video (MP4).

    Generates a video with a moving rectangle so detection/tracking
    can be tested over multiple frames.

    Parameters
    ----------
    width, height : int
        Video dimensions.
    num_frames : int
        Number of frames in the video.
    fps : float
        Frames per second.
    path : str | Path
        Output video path (must end in .mp4).

    Returns
    -------
    Path : Path to the created video file.
    """
    import cv2 as cv  # type: ignore[import-untyped]  # noqa: F401
    import numpy as np  # type: ignore[import-untyped]

    out_path = Path(path) if path else Path("/tmp/vision_test_video.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
    out = cv.VideoWriter(str(out_path), fourcc, fps, (width, height))  # type: ignore[attr-defined]

    for i in range(num_frames):
        # Background
        frame = np.full((height, width, 3), [30, 60, 120], dtype=np.uint8)
        # Moving rectangle
        x = int(50 + i * (width - 100) / num_frames)
        y = int(100 + i * 5)
        cv.rectangle(frame, (x, y), (x + 80, y + 60), (220, 50, 50), 2)
        # Frame counter text
        cv.putText(frame, f"Frame {i}", (10, 30), cv.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        out.write(frame)

    out.release()
    return out_path
