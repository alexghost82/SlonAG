"""Closed-loop visual computer agent.

Exports:
    types – canonical dataclasses (Frame, VisionObservation, ComputerAction,
            LoopBudget, LoopState, VerificationResult, error types).
    adapter – VirtualScreenAdapter (deterministic E2E), ScreenshotAdapter.
    closed_loop – VisionComputerAgent (observe→reason→act→verify→correct).
"""

from computer_control import types, adapter, closed_loop

__all__ = ["types", "adapter", "closed_loop"]

# Re-export key symbols for convenience
from computer_control.types import (
    ActionCategory,
    BudgetExceededError,
    CancellationError,
    ClosedLoopError,
    ComputerAction,
    Frame,
    FrameSource,
    LoopBudget,
    LoopPhase,
    LoopState,
    SafetyDenialError,
    StaleObservationError,
    VerificationFailedError,
    VerificationResult,
    VerificationStatus,
    VisionObservation,
)
from computer_control.adapter import (
    ComputerAdapter,
    DeterministicVisionEngine,
    VirtualScreenAdapter,
    ScreenshotAdapter,
    VirtualElement,
    VirtualScreenState,
)
from computer_control.closed_loop import (
    DefaultReasoner,
    DefaultVerifier,
    TargetGroundingResult,
    VisionComputerAgent,
)

__all__ += [
    "ActionCategory",
    "BudgetExceededError",
    "CancellationError",
    "ClosedLoopError",
    "ComputerAction",
    "ComputerAdapter",
    "DefaultReasoner",
    "DefaultVerifier",
    "DeterministicVisionEngine",
    "Frame",
    "FrameSource",
    "LoopBudget",
    "LoopPhase",
    "LoopState",
    "SafetyDenialError",
    "ScreenshotAdapter",
    "StaleObservationError",
    "TargetGroundingResult",
    "VerificationFailedError",
    "VerificationResult",
    "VerificationStatus",
    "VerificationStatus",
    "VirtualElement",
    "VirtualScreenAdapter",
    "VirtualScreenState",
    "VisionComputerAgent",
    "VisionObservation",
]
