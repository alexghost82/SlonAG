"""Deterministic image fixtures.

Creates PNG images with known geometry so detection and tracking tests
produce reproducible results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def create_test_image(
    width: int = 640,
    height: int = 480,
    colors: list[tuple[int, int, int]] | None = None,
    path: str | Path | None = None,
    **kwargs: Any,
) -> bytes:
    """Create a deterministic test image (PNG).

    Generates a simple geometric image: a coloured rectangle on a
    contrasting background.  Used for detection/tracking tests.

    Parameters
    ----------
    width, height : int
        Image dimensions.
    colors : list of (R, G, B)
        [background, foreground]. Defaults to blue background, red rectangle.
    path : str | Path, optional
        If given, save the PNG to this path.
    **kwargs
        Additional geometry overrides (rect_x, rect_y, rect_w, rect_h).

    Returns
    -------
    bytes : PNG data.
    """
    colors = colors or [(30, 60, 120), (220, 50, 50)]
    bg_r, bg_g, bg_b = colors[0]
    fg_r, fg_g, fg_b = colors[1] if len(colors) > 1 else colors[0]

    rect_x = kwargs.get("rect_x", width // 4)
    rect_y = kwargs.get("rect_y", height // 4)
    rect_w = kwargs.get("rect_w", width // 2)
    rect_h = kwargs.get("rect_h", height // 2)

    _ensure_dependencies()
    import numpy as np  # type: ignore

    img = np.full((height, width, 3), [bg_b, bg_g, bg_r], dtype=np.uint8)  # BGR
    cv = __import__("cv2")  # type: ignore
    cv.rectangle(img, (rect_x, rect_y), (rect_x + rect_w, rect_y + rect_h),
                 (fg_b, fg_g, fg_r), 2)

    success, buf = cv.imencode(".png", img)
    if not success:
        raise RuntimeError("Failed to encode test image")

    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(buf.tobytes())

    return buf.tobytes()


def create_moving_object_image(
    width: int = 640,
    height: int = 480,
    positions: list[tuple[int, int]] | None = None,
    path: str | Path | None = None,
) -> list[bytes]:
    """Create multiple frames with a moving rectangle.

    Useful for multi-frame tracking tests: each frame has the rectangle
    at a different position, giving a known trajectory.

    Parameters
    ----------
    positions : list of (x, y)
        Rectangle top-left corner per frame.

    Returns
    -------
    list[bytes] : PNG data for each frame.
    """
    if positions is None:
        positions = [
            (50, 50), (150, 100), (250, 150),
            (350, 200), (450, 250), (550, 300),
        ]

    _ensure_dependencies()
    import cv2 as cv  # type: ignore
    import numpy as np  # type: ignore

    frames: list[bytes] = []
    for px, py in positions:
        img = np.full((height, width, 3), [30, 60, 120], dtype=np.uint8)
        cv.rectangle(img, (px, py), (px + 80, py + 60), (220, 50, 50), 2)
        success, buf = cv.imencode(".png", img)
        frames.append(buf.tobytes())

    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        for i, data in enumerate(frames):
            (p / f"frame_{i:04d}.png").write_bytes(data)

    return frames


def create_grid_image(
    width: int = 640,
    height: int = 480,
    cols: int = 3,
    rows: int = 2,
    colors: list[tuple[int, int, int]] | None = None,
    path: str | Path | None = None,
) -> bytes:
    """Create an image with a grid of coloured rectangles.

    Useful for testing multiple-object detection in a single frame.
    """
    colors = colors or [
        (220, 50, 50), (50, 220, 50), (50, 50, 220),
        (220, 220, 50), (220, 50, 220), (50, 220, 220),
    ]
    _ensure_dependencies()
    import cv2 as cv  # type: ignore
    import numpy as np  # type: ignore

    img = np.full((height, width, 3), [10, 10, 10], dtype=np.uint8)
    cell_w = width // cols
    cell_h = height // rows

    for row in range(rows):
        for col in range(cols):
            idx = row * cols + col
            r, g, b = colors[idx % len(colors)]
            x = col * cell_w + cell_w // 10
            y = row * cell_h + cell_h // 10
            w = cell_w * 4 // 5
            h = cell_h * 4 // 5
            cv.rectangle(img, (x, y), (x + w, y + h), (b, g, r), 2)
            if path is not None:
                pass  # saved below

    success, buf = cv.imencode(".png", img)
    if not success:
        raise RuntimeError("Failed to encode grid image")

    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(buf.tobytes())

    return buf.tobytes()


def create_text_image(
    width: int = 640,
    height: int = 480,
    text: str = "TEST-TEXT-OCR",
    path: str | Path | None = None,
) -> bytes:
    """Create an image with test text for OCR testing."""
    _ensure_dependencies()
    import cv2 as cv  # type: ignore
    import numpy as np  # type: ignore

    img = np.full((height, width, 3), [255, 255, 255], dtype=np.uint8)
    cv.putText(img, text, (50, 200), cv.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)

    success, buf = cv.imencode(".png", img)
    if not success:
        raise RuntimeError("Failed to encode text image")

    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(buf.tobytes())

    return buf.tobytes()


def create_person_roi(
    width: int = 640,
    height: int = 480,
    path: str | Path | None = None,
) -> bytes:
    """Create an image with a person-sized rectangle ROI.

    Useful for testing the OpenCV person detector with a known object.
    """
    _ensure_dependencies()
    import cv2 as cv  # type: ignore
    import numpy as np  # type: ignore

    img = np.full((height, width, 3), [30, 60, 120], dtype=np.uint8)
    # Draw a person-sized rectangle (typical aspect ratio ~1:3)
    px, py = width // 3, height // 6
    pw, ph = width // 6, height * 2 // 3
    cv.rectangle(img, (px, py), (px + pw, py + ph), (220, 50, 50), 3)

    success, buf = cv.imencode(".png", img)
    if not success:
        raise RuntimeError("Failed to encode person ROI image")

    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(buf.tobytes())

    return buf.tobytes()


def _ensure_dependencies() -> None:
    """Ensure OpenCV and numpy are available."""
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Vision fixtures require cv2 and numpy. Install with: "
            "pip install opencv-python numpy"
        ) from e
