"""Viewport utilities — coordinate validation and screen bounds.

Provides:
    * ScreenBounds — named 4-tuple (left, top, width, height).
    * validate_coordinates — clamp and bounds-check x/y against ScreenBounds.
    * screen_to_normalized — convert raw pixels to 0-1 normalized coords.
    * normalized_to_screen — convert normalized coords to raw pixels.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScreenBounds:
    """A rectangular region of the screen in raw pixels."""

    left: int = 0
    top: int = 0
    width: int = 1920
    height: int = 1080

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains(self, x: int, y: int) -> bool:
        """Return True if (x, y) is inside the bounds (exclusive on right/bottom)."""
        return self.left <= x < self.right and self.top <= y < self.bottom


class CoordinateValidationError(Exception):
    """A coordinate falls outside the valid screen region."""

    def __init__(self, x: int, y: int, bounds: ScreenBounds) -> None:
        self.x = x
        self.y = y
        self.bounds = bounds
        super().__init__(
            f"Координаты ({x}, {y}) выходят за пределы экрана "
            f"[{bounds.left}:{bounds.right}, {bounds.top}:{bounds.bottom}]"
        )


def validate_coordinates(
    x: int | None,
    y: int | None,
    bounds: ScreenBounds,
) -> tuple[int, int]:
    """Validate and clamp coordinates against *bounds*."""
    if x is None or x < bounds.left:
        x = bounds.left
    if x > bounds.right:
        x = bounds.right - 1
    if y is None or y < bounds.top:
        y = bounds.top
    if y > bounds.bottom:
        y = bounds.bottom - 1
    return x, y


def screen_to_normalized(x: int, y: int, bounds: ScreenBounds) -> tuple[float, float]:
    """Convert raw pixel coordinates to normalised (0-1) values."""
    nx = (x - bounds.left) / max(bounds.width - 1, 1)
    ny = (y - bounds.top) / max(bounds.height - 1, 1)
    return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))


def normalized_to_screen(nx: float, ny: float, bounds: ScreenBounds) -> tuple[int, int]:
    """Convert normalised (0-1) coordinates back to raw pixels."""
    x = int(nx * (bounds.width - 1)) + bounds.left
    y = int(ny * (bounds.height - 1)) + bounds.top
    return bounds.left + max(0, min(bounds.width - 1, x)), bounds.top + max(0, min(bounds.height - 1, y))
