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

from computer_control.capabilities import CapabilityDetector, CapabilityResult
from computer_control.executor import computer_control, build_computer_control_executor
from computer_control.platform import MouseClickButton, ScrollDirection, PlatformAdapter
from computer_control.deterministic import MockPlatformAdapter
from computer_control.platform import (
    build_linux_adapter,
    build_macos_adapter,
    build_windows_adapter,
    build_platform_adapter,
)

__all__ = [
    "CapabilityDetector",
    "CapabilityResult",
    "PlatformAdapter",
    "MockPlatformAdapter",
    "build_platform_adapter",
    "MouseClickButton",
    "ScrollDirection",
    "computer_control",
    "build_computer_control_executor",
]
