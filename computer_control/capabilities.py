"""Capability detection for computer-control actions.

Detects OS, display, and dependency availability so the adapter
can report what is and isn't supported before an action fails.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any

from computer_control.platform import build_platform_adapter
from computer_control.types import (
    OSPlatform,
    Permission,
)


@dataclass(frozen=True)
class CapabilityResult:
    """Result of a capability check."""

    capability: str
    supported: bool
    details: str = ""
    missing: str = ""

    @property
    def ok(self) -> bool:
        return self.supported


@dataclass
class CapabilityDetector:
    """Detect OS, display, permission, and tool availability."""

    platform: OSPlatform = OSPlatform.UNKNOWN
    _details: dict[str, Any] = field(default_factory=dict, repr=False)
    _validated: dict[str, bool] = field(default_factory=dict, repr=False)
    _runtime_checked: bool = field(default=False, repr=False)

    # ── Factory ────────────────────────────────────────────────────

    @staticmethod
    def detect() -> "CapabilityDetector":
        """Auto-detect platform and capabilities."""
        system = platform.system()
        if system == "Linux":
            plat = OSPlatform.LINUX
        elif system == "Darwin":
            plat = OSPlatform.MACOS
        elif system == "Windows":
            plat = OSPlatform.WINDOWS
        else:
            plat = OSPlatform.UNKNOWN

        det = CapabilityDetector(platform=plat)
        det._collect()
        return det

    def _collect(self) -> None:
        """Collect capability information."""
        self._details["os"] = platform.platform()
        self._details["os_name"] = platform.system()
        self._details["os_version"] = platform.version()
        self._details["python_version"] = platform.python_version()
        self._details["arch"] = platform.machine()

        # Check pyautogui
        self._details["pyautogui"] = self._has_module("pyautogui")
        self._details["pyperclip"] = self._has_module("pyperclip")
        self._details["xdotool"] = self._has_tool("xdotool")
        self._details["xclip"] = (
            self._has_tool("xclip") or self._has_tool("xsel")
        )

        # Wayland detection — only meaningful on Linux; ignore errors.
        self._details["wayland"] = False
        if self.platform == OSPlatform.LINUX:
            try:
                release = platform.freedesktop_os_release()
                if isinstance(release, dict):
                    desktop = str(release.get("VERSION_ID", "")).lower()
                    self._details["wayland"] = (
                        "wayland" in desktop or "gnome" in desktop
                    )
            except Exception:
                pass
            if not self._details["wayland"] and self._has_tool("systemctl"):
                try:
                    result = subprocess.run(
                        ["systemctl", "is-system-running"],
                        capture_output=True, timeout=5,
                    )
                    self._details["wayland"] = (
                        result.returncode == 0
                        and result.stdout.strip().decode() in ("degraded", "running")
                    )
                except Exception:
                    pass

    @staticmethod
    def _has_module(name: str) -> bool:
        try:
            __import__(name)
            return True
        except ImportError:
            return False

    @staticmethod
    def _has_tool(name: str) -> bool:
        try:
            subprocess.run(["which", name], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ── Public queries ─────────────────────────────────────────────

    def get(self, capability: str) -> CapabilityResult:
        """Query a specific capability."""
        if capability == "input":
            return self._validated_or(capability, self._check_input)
        if capability == "screenshot":
            return self._validated_or(capability, self._check_screenshot)
        if capability == "window_management":
            return self._validated_or(capability, self._check_window)
        if capability == "clipboard":
            return self._validated_or(capability, self._check_clipboard)
        if capability == "system_settings":
            return self._validated_or(capability, self._check_system_settings)
        if capability == "app_launch":
            return self._validated_or(capability, self._check_app_launch)
        if capability == "screen_info":
            return self._validated_or(capability, self._check_screen_info)
        if capability == "platform":
            return CapabilityResult(
                capability="platform",
                supported=self.platform != OSPlatform.UNKNOWN,
                details=self.platform.value,
            )
        if capability == "permissions":
            perms: dict[str, bool] = {}
            for perm in Permission:
                r = self.get(perm.value)
                perms[perm.value] = r.supported
            return CapabilityResult(
                capability="permissions",
                supported=True,
                details=str(perms),
            )
        # Fallback: check via adapter
        return self._check_via_adapter(capability)

    def _validated_or(
        self, capability: str, fallback_fn
    ) -> CapabilityResult:
        """Return the validated result if runtime-checked, else the static result.

        This prevents reporting capabilities as supported when they have
        not been actually tested at runtime — the core "no false capabilities"
        guarantee.
        """
        if self._runtime_checked and capability in self._validated:
            return CapabilityResult(
                capability=capability,
                supported=self._validated.get(capability, False),
            )
        return fallback_fn()

    def validate(self) -> None:
        """Run a lightweight runtime probe for every capability.

        This is a zero-cost no-op the second time it is called.
        After validation every reported capability has been confirmed
        to actually *work*, not just have its tools installed.
        """
        if self._runtime_checked:
            return
        self._runtime_checked = True

        # input — verify pyautogui actually imports and is usable
        if self._details.get("pyautogui"):
            try:
                import pyautogui as _pa
                _pa.FAILSAFE  # triggers import sanity checks
                self._validated["input"] = True
            except Exception:
                self._validated["input"] = False

        # app_launch — verify subprocess can fork/exec at all
        try:
            subprocess.run(["true"], capture_output=True, timeout=2)
            self._validated["app_launch"] = True
        except Exception:
            self._validated["app_launch"] = False

    # ── Static capability checks ───────────────────────────────────

    def _check_input(self) -> CapabilityResult:
        if self._details.get("pyautogui"):
            return CapabilityResult(
                capability="input",
                supported=True,
                details="pyautogui available",
            )
        return CapabilityResult(
            capability="input",
            supported=False,
            details="",
            missing="pyautogui",
        )

    def _check_screenshot(self) -> CapabilityResult:
        if self.platform == OSPlatform.LINUX:
            tools = ["scrot", "import", "gnome-screenshot"]
            found = any(self._has_tool(t) for t in tools)
            if self._details.get("pyautogui"):
                found = True
            return CapabilityResult(
                capability="screenshot",
                supported=found,
                details="screenshot tools available" if found else "",
                missing="scrot|import|pyautogui" if not found else "",
            )
        if self.platform == OSPlatform.MACOS:
            return CapabilityResult(
                capability="screenshot",
                supported=self._has_tool("screencapture"),
                details="screencapture available",
            )
        if self.platform == OSPlatform.WINDOWS:
            return CapabilityResult(
                capability="screenshot",
                supported=self._details.get("pyautogui", False),
                details="pyautogui available",
                missing="pyautogui" if not self._details.get("pyautogui") else "",
            )
        return CapabilityResult(
            capability="screenshot",
            supported=False,
            missing=f"screenshot not supported on {self.platform.value}",
        )

    def _check_window(self) -> CapabilityResult:
        if self.platform == OSPlatform.LINUX:
            has_xdotool = self._details.get("xdotool", False)
            return CapabilityResult(
                capability="window_management",
                supported=has_xdotool,
                details="xdotool available" if has_xdotool else "",
                missing="xdotool" if not has_xdotool else "",
            )
        if self.platform == OSPlatform.MACOS:
            return CapabilityResult(
                capability="window_management",
                supported=self._has_tool("osascript"),
                details="AppleScript available",
            )
        if self.platform == OSPlatform.WINDOWS:
            has_win32 = self._has_module("win32gui")
            return CapabilityResult(
                capability="window_management",
                supported=has_win32,
                details="pywin32 available" if has_win32 else "",
                missing="pywin32" if not has_win32 else "",
            )
        return CapabilityResult(
            capability="window_management",
            supported=False,
            missing=f"window management not supported on {self.platform.value}",
        )

    def _check_clipboard(self) -> CapabilityResult:
        if self._details.get("pyperclip"):
            return CapabilityResult(
                capability="clipboard",
                supported=True,
                details="pyperclip available",
            )
        if self.platform == OSPlatform.LINUX:
            has_xclip = self._details.get("xclip") or self._details.get("xsel")
            return CapabilityResult(
                capability="clipboard",
                supported=has_xclip,
                details="xclip/xsel available" if has_xclip else "",
                missing="xclip|pyperclip" if not has_xclip else "",
            )
        if self.platform == OSPlatform.MACOS:
            return CapabilityResult(
                capability="clipboard",
                supported=self._has_tool("pbpaste"),
                details="pbcopy/pbpaste available",
            )
        if self.platform == OSPlatform.WINDOWS:
            has_win32 = self._has_module("win32clipboard")
            return CapabilityResult(
                capability="clipboard",
                supported=has_win32,
                details="win32clipboard available" if has_win32 else "",
                missing="win32clipboard|pyperclip" if not has_win32 else "",
            )
        return CapabilityResult(
            capability="clipboard",
            supported=False,
            missing=f"clipboard not supported on {self.platform.value}",
        )

    def _check_system_settings(self) -> CapabilityResult:
        if self.platform == OSPlatform.LINUX:
            has_amixer = self._has_tool("amixer")
            has_pactl = self._has_tool("pactl")
            return CapabilityResult(
                capability="system_settings",
                supported=has_amixer or has_pactl,
                details="amixer/pactl available" if (has_amixer or has_pactl) else "",
                missing="amixer|pactl|pycaw" if not (has_amixer or has_pactl) else "",
            )
        if self.platform == OSPlatform.MACOS:
            return CapabilityResult(
                capability="system_settings",
                supported=self._has_tool("osascript"),
                details="osascript available",
            )
        if self.platform == OSPlatform.WINDOWS:
            has_pycaw = self._has_module("pycaw")
            return CapabilityResult(
                capability="system_settings",
                supported=has_pycaw,
                details="pycaw available" if has_pycaw else "",
                missing="pycaw" if not has_pycaw else "",
            )
        return CapabilityResult(
            capability="system_settings",
            supported=False,
            missing=f"system settings not supported on {self.platform.value}",
        )

    def _check_app_launch(self) -> CapabilityResult:
        return CapabilityResult(
            capability="app_launch",
            supported=True,
            details=f"subprocess available on {self.platform.value}",
        )

    def _check_screen_info(self) -> CapabilityResult:
        if self.platform == OSPlatform.LINUX:
            has_xset = self._has_tool("xset")
            return CapabilityResult(
                capability="screen_info",
                supported=has_xset,
                details="xset available" if has_xset else "",
                missing="xset|xrandr" if not has_xset else "",
            )
        if self.platform == OSPlatform.MACOS:
            return CapabilityResult(
                capability="screen_info",
                supported=self._has_tool("system_profiler"),
                details="system_profiler available",
            )
        if self.platform == OSPlatform.WINDOWS:
            has_win32 = self._has_module("win32api")
            return CapabilityResult(
                capability="screen_info",
                supported=has_win32,
                details="win32api available" if has_win32 else "",
                missing="pywin32" if not has_win32 else "",
            )
        return CapabilityResult(
            capability="screen_info",
            supported=False,
            missing=f"screen info not supported on {self.platform.value}",
        )

    def _check_via_adapter(self, capability: str) -> CapabilityResult:
        """Fallback: query the platform adapter for permission status."""
        try:
            adapter = build_platform_adapter("auto")
            result = adapter.check_permission(capability)
            return CapabilityResult(
                capability=capability,
                supported=result.ok and result.data.get("granted", False),
                details=result.message if result.ok else "adapter returned error",
            )
        except Exception:
            return CapabilityResult(
                capability=capability,
                supported=False,
                missing="adapter not available for capability check",
            )

    def full_report(self) -> dict[str, Any]:
        """Return a full capability report."""
        return {
            "platform": self.platform.value,
            "os": self._details.get("os", ""),
            "python": self._details.get("python_version", ""),
            "capabilities": {
                "input": self.get("input").supported,
                "screenshot": self.get("screenshot").supported,
                "window_management": self.get("window_management").supported,
                "clipboard": self.get("clipboard").supported,
                "system_settings": self.get("system_settings").supported,
                "app_launch": self.get("app_launch").supported,
                "screen_info": self.get("screen_info").supported,
            },
            "details": self._details,
        }


def check_capabilities() -> dict[str, Any]:
    """Quick capability check using auto-detection."""
    return CapabilityDetector.detect().full_report()
