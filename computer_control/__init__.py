"""computer_control — platform-agnostic desktop automation for SlonAG.

Exports:
    - CapabilityDetector  — OS / display / permission detection
    - PlatformAdapter     — base adapter class
    - MockPlatformAdapter — deterministic E2E adapter (no real desktop)
    - build_platform_adapter — factory that selects platform adapter
    - CapabilityResult    — capability detection result
    - ComputerControlAction — enum of supported actions
    - MouseClickButton    — click button type
    - ScrollDirection     — scroll direction type
"""

from __future__ import annotations

from computer_control.capabilities import CapabilityDetector, CapabilityResult, check_capabilities
from computer_control.deterministic import MockPlatformAdapter
from computer_control.executor import (
    ComputerControlExecutor,
    build_computer_control_executor,
    run_computer_control,
    validate_action,
)
from computer_control.platform import (
    build_linux_adapter,
    build_macos_adapter,
    build_platform_adapter,
    build_windows_adapter,
    PlatformAdapter,
)
from computer_control.types import (
    ACTION_FIELDS,
    AppInfo,
    CancellationToken,
    ComputerControlAction,
    ExecutionResult,
    MouseClickButton,
    OSPlatform,
    Permission,
    ScreenPosition,
    ScrollDirection,
    WindowInfo,
)

__all__ = [
    # Types
    "ACTION_FIELDS",
    "AppInfo",
    "CancellationToken",
    "ComputerControlAction",
    "ExecutionResult",
    "MouseClickButton",
    "OSPlatform",
    "Permission",
    "ScreenPosition",
    "ScrollDirection",
    "WindowInfo",
    # Platform
    "PlatformAdapter",
    "MockPlatformAdapter",
    "build_platform_adapter",
    "build_linux_adapter",
    "build_macos_adapter",
    "build_windows_adapter",
    # Capabilities
    "CapabilityDetector",
    "CapabilityResult",
    "check_capabilities",
    # Executor
    "ComputerControlExecutor",
    "build_computer_control_executor",
    "run_computer_control",
    "validate_action",
]

# Closed-loop and viewport utilities
from computer_control.closed_loop import (
    ComputerAdapterProtocol,
    DefaultReasoner,
    DefaultVerifier,
    TargetGroundingResult,
    VisionComputerAgent,
)
from computer_control.click_detector import (
    ClickLoopDetector,
    ClickRecord,
    LoopBreakError,
    get_detector,
    reset_detector,
)
from computer_control.viewport import (
    CoordinateValidationError,
    ScreenBounds,
    normalized_to_screen,
    screen_to_normalized,
    validate_coordinates,
)

__all__.extend([
    # Closed-loop
    "ComputerAdapterProtocol",
    "DefaultReasoner",
    "DefaultVerifier",
    "TargetGroundingResult",
    "VisionComputerAgent",
    # Click loop detector
    "ClickLoopDetector",
    "ClickRecord",
    "LoopBreakError",
    "get_detector",
    "reset_detector",
    # Viewport
    "CoordinateValidationError",
    "ScreenBounds",
    "screen_to_normalized",
    "normalized_to_screen",
    "validate_coordinates",
])
