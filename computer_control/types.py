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
# Proposed / executed action
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
    "ActionCategory",
    "BudgetExceededError",
    "CancellationError",
    "ClosedLoopError",
    "ComputerAction",
    "Frame",
    "FrameSource",
    "LoopBudget",
    "LoopPhase",
    "LoopState",
    "SafetyDenialError",
    "StaleObservationError",
    "VerificationFailedError",
    "VerificationResult",
    "VerificationStatus",
    "VisionObservation",
]
