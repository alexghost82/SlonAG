"""Canonical types for the closed-loop visual computer agent.

Every frame, observation, action, and verification carries correlation
identifiers so the loop can detect stale observations, enforce
action/observation correlation, and fail-closed.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ---------------------------------------------------------------------------
# Frame sources
# ---------------------------------------------------------------------------

class FrameSource(StrEnum):
    """Where a frame originates."""

    SCREENSHOT = "screenshot"
    CAMERA = "camera"
    RTSP = "rtsp"
    VIRTUAL = "virtual"
    GENERATED = "generated"


class ActionCategory(StrEnum):
    """Risk category of a computer action."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"


class VerificationStatus(StrEnum):
    """Outcome of a post-action verification."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# OS / platform enums
# ---------------------------------------------------------------------------

class OSPlatform(StrEnum):
    """Operating system platform."""

    UNKNOWN = "unknown"
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


class ScrollDirection(StrEnum):
    """Scroll direction."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class MouseClickButton(StrEnum):
    """Mouse button for click actions."""

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class Permission(StrEnum):
    """Platform permission types."""

    SCREEN = "screen"
    MOUSE = "mouse"
    KEYBOARD = "keyboard"
    CLIPBOARD = "clipboard"
    WINDOW = "window"
    APP = "application"


# ---------------------------------------------------------------------------
# ComputerControlAction — platform action identifiers (StrEnum)
# ---------------------------------------------------------------------------

class ComputerControlAction(StrEnum):
    """Canonical identifiers for platform-level computer-control actions.

    Used by the executor to dispatch actions to the platform adapter.
    """

    # Mouse
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_DOUBLE_CLICK = "mouse_double_click"
    MOUSE_RIGHT_CLICK = "mouse_right_click"
    MOUSE_DRAG = "mouse_drag"

    # Keyboard
    KEYBOARD_TYPE = "keyboard_type"
    KEYBOARD_HOTKEY = "keyboard_hotkey"
    KEYBOARD_PRESS = "keyboard_press"

    # Clipboard
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"

    # Screen
    SCREENSHOT = "screenshot"
    SCROLL = "scroll"

    # Window
    WINDOW_LIST = "window_list"
    WINDOW_FOCUS = "window_focus"
    WINDOW_MINIMIZE = "window_minimize"
    WINDOW_MAXIMIZE = "window_maximize"
    WINDOW_CLOSE = "window_close"
    WINDOW_GET_INFO = "window_get_info"

    # App
    APP_LAUNCH = "app_launch"
    APP_KILL = "app_kill"
    APP_LIST = "app_list"

    # System
    VOLUME_GET = "volume_get"
    VOLUME_SET = "volume_set"
    BRIGHTNESS_GET = "brightness_get"
    BRIGHTNESS_SET = "brightness_set"

    # Control
    WAIT = "wait"
    CAPABILITY_CHECK = "capability_check"


# ACTION_FIELDS defines the JSON schema fields for each platform action.
ACTION_FIELDS: dict[str, dict[str, Any]] = {
    "mouse_move": {"x": {"type": "int"}, "y": {"type": "int"}},
    "mouse_click": {
        "x": {"type": "int", "optional": True},
        "y": {"type": "int", "optional": True},
        "button": {"type": "str", "enum": ["left", "right", "middle"], "default": "left"},
        "clicks": {"type": "int", "default": 1},
    },
    "mouse_drag": {
        "x1": {"type": "int"}, "y1": {"type": "int"},
        "x2": {"type": "int"}, "y2": {"type": "int"},
        "duration": {"type": "float", "default": 0.5},
    },
    "keyboard_type": {"text": {"type": "str"}},
    "keyboard_hotkey": {"keys": {"type": "list[str]"}},
    "keyboard_press": {"key": {"type": "str"}},
    "scroll": {
        "direction": {"type": "str", "enum": ["up", "down", "left", "right"]},
        "amount": {"type": "int", "default": 3},
    },
    "clipboard_read": {},
    "clipboard_write": {"text": {"type": "str"}},
    "screenshot": {"save_path": {"type": "str", "optional": True}},
    "window_focus": {"title": {"type": "str"}},
    "window_minimize": {"title": {"type": "str"}},
    "window_maximize": {"title": {"type": "str"}},
    "window_close": {"title": {"type": "str"}},
    "window_list": {},
    "window_get_info": {"title": {"type": "str", "optional": True}},
    "app_launch": {"path": {"type": "str", "optional": True}, "name": {"type": "str", "optional": True}},
    "app_kill": {"pid": {"type": "int", "default": 0}, "name": {"type": "str", "optional": True}},
    "app_list": {},
    "volume_get": {},
    "volume_set": {"value": {"type": "int"}},
    "brightness_get": {},
    "brightness_set": {"value": {"type": "int"}},
    "screen_info": {},
    "wait": {"seconds": {"type": "float", "default": 1.0}},
    "capability_check": {"capability": {"type": "str"}},
}


# ---------------------------------------------------------------------------
# Platform dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScreenPosition:
    """A screen coordinate."""

    x: int
    y: int


@dataclass(frozen=True)
class WindowInfo:
    """A window on the desktop."""

    title: str
    pid: int
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    is_active: bool = False
    is_visible: bool = True
    is_minimized: bool = False
    is_maximized: bool = False


@dataclass(frozen=True)
class AppInfo:
    """Application info."""

    name: str
    pid: int
    is_active: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    """Result of a platform action execution."""

    ok: bool = True
    message: str = ""
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok_result(cls, message: str = "", data: dict[str, Any] | None = None) -> ExecutionResult:
        return cls(ok=True, message=message, data=data or {})

    @classmethod
    def error_result(cls, code: str, message: str) -> ExecutionResult:
        return cls(ok=False, message=message, error=code, data={})


# ---------------------------------------------------------------------------
# CancellationToken — lightweight cancellation protocol
# ---------------------------------------------------------------------------

class CancellationToken:
    """Cancel an in-flight operation."""

    def __init__(self) -> None:
        self._cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    def check(self) -> None:
        if self._cancelled:
            raise CancellationError("Operation cancelled.")

    @property
    def cancelled(self) -> bool:
        return self._cancelled


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    """A single visual observation (raw bytes)."""

    source: FrameSource
    image_bytes: bytes
    timestamp: float = field(default_factory=time.time)
    index: int = 0
    stream_url: str | None = None
    width: int = 0
    height: int = 0

    @property
    def fingerprint(self) -> str:
        """Deterministic hash for stale-observation detection."""
        data = (
            f"{self.source}:{self.index}:{self.timestamp:.6f}:"
            f"{len(self.image_bytes)}"
        ).encode()
        return hashlib.sha256(data).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Vision observation (output of the vision engine)
# ---------------------------------------------------------------------------

@dataclass
class VisionObservation:
    """Structured output from a vision engine on a single frame."""

    frame_fingerprint: str
    frame_index: int
    detected_objects: list[dict[str, Any]] = field(default_factory=list)
    ocr_text: str = ""
    description: str = ""
    ui_elements: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Proposed / executed action (closed-loop specific)
# ---------------------------------------------------------------------------

@dataclass
class ComputerAction:
    """An action the agent proposes or executes on the computer."""

    action_type: str  # e.g. "click", "type", "scroll", "screenshot"
    target: str = ""  # element description / coordinates
    args: dict[str, Any] = field(default_factory=dict)
    category: ActionCategory = ActionCategory.NONE
    proposed_by: str = "agent"  # "agent" or "user"
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hashlib.sha256(
                f"{self.action_type}:{self.target}:{time.time_ns()}".encode()
            ).hexdigest()[:12]

    @property
    def is_write(self) -> bool:
        return self.category in (ActionCategory.WRITE, ActionCategory.IRREVERSIBLE)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """Post-action observation compared against the expected outcome."""

    action_id: str
    pre_frame_fingerprint: str
    post_frame_fingerprint: str
    status: VerificationStatus = VerificationStatus.PENDING
    changed: bool = False
    detected_changes: list[dict[str, Any]] = field(default_factory=list)
    expected_fingerprint: str = ""
    actual_fingerprint: str = ""
    reason: str = ""
    stale: bool = False
    retryable: bool = True


# ---------------------------------------------------------------------------
# Loop state
# ---------------------------------------------------------------------------

class LoopPhase(StrEnum):
    IDLE = "idle"
    OBSERVE = "observe"
    REASON = "reason"
    PROPOSE = "propose"
    APPROVE = "approve"
    ACT = "act"
    VERIFY = "verify"
    CORRECT = "correct"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class LoopBudget:
    """Resource limits for the closed-loop cycle."""

    max_steps: int = 10
    max_steps_in_phase: int = 5
    timeout_seconds: float = 60.0
    observation_stale_seconds: float = 30.0
    # Mutable counters
    step: int = 0
    phase_step: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_seconds - self.elapsed_seconds)

    def can_step(self) -> bool:
        return (
            self.step < self.max_steps
            and self.phase_step < self.max_steps_in_phase
            and self.remaining_seconds > 0
        )

    def advance_phase(self) -> None:
        self.step += 1
        self.phase_step = 0

    def advance_step(self) -> None:
        self.phase_step += 1


@dataclass
class LoopState:
    """Mutable state tracked by the closed-loop cycle."""

    phase: LoopPhase = LoopPhase.IDLE
    current_frame: Frame | None = None
    current_observation: VisionObservation | None = None
    proposed_action: ComputerAction | None = None
    executed_action: ComputerAction | None = None
    verification: VerificationResult | None = None
    correction_history: list[str] = field(default_factory=list)
    cancelled: bool = False
    error: str | None = None
    result: str | None = None

    @property
    def latest_fingerprint(self) -> str:
        if self.current_frame:
            return self.current_frame.fingerprint
        return ""


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class ClosedLoopError(Exception):
    """Base exception for closed-loop failures."""


class StaleObservationError(ClosedLoopError):
    """Observation is older than the allowed window."""


class BudgetExceededError(ClosedLoopError):
    """Max steps or timeout exceeded."""


class CancellationError(ClosedLoopError):
    """Loop was explicitly cancelled."""


class VerificationFailedError(ClosedLoopError):
    """Post-action verification did not confirm expected change."""


class SafetyDenialError(ClosedLoopError):
    """Safety policy denied the proposed action."""


__all__ = [
    # Enums
    "FrameSource",
    "ActionCategory",
    "VerificationStatus",
    "OSPlatform",
    "ScrollDirection",
    "MouseClickButton",
    "Permission",
    "ComputerControlAction",
    "LoopPhase",
    # Dataclasses
    "ScreenPosition",
    "WindowInfo",
    "AppInfo",
    "ExecutionResult",
    "Frame",
    "VisionObservation",
    "ComputerAction",
    "VerificationResult",
    "LoopBudget",
    "LoopState",
    # Constants
    "ACTION_FIELDS",
    # Cancellation
    "CancellationToken",
    # Errors
    "ClosedLoopError",
    "StaleObservationError",
    "BudgetExceededError",
    "CancellationError",
    "VerificationFailedError",
    "SafetyDenialError",
]
