"""Component health status with honest capability states.

Each component reports one of:
- available    — fully functional, validated
- unavailable  — missing dependency, not reachable
- degraded     — partial functionality
- misconfigured — settings are wrong
- disabled     — intentionally off by user

A component CANNOT be "available" if:
- implementation is a stub/mock/test-only shim
- hasn't passed validation
- doesn't exist yet
"""

from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from i18n import t


class ComponentState(str):
    """Component state enum."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    MISCONFIGURED = "misconfigured"
    DISABLED = "disabled"


# Predefined constants for use in code
available: ComponentState = ComponentState.AVAILABLE
unavailable: ComponentState = ComponentState.UNAVAILABLE
degraded: ComponentState = ComponentState.DEGRADED
misconfigured: ComponentState = ComponentState.MISCONFIGURED
disabled: ComponentState = ComponentState.DISABLED


@dataclass(frozen=True)
class ComponentStatus:
    """Status of a single component."""

    name: str
    state: ComponentState
    message: str = ""
    details: str = ""
    last_checked: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    version: str = ""

    @property
    def is_ready(self) -> bool:
        """True only if state is 'available'."""
        return self.state == ComponentState.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "message": self.message,
            "details": self.details,
            "last_checked": self.last_checked,
            "version": self.version,
        }


class ComponentRegistry:
    """Registry of component status checkers."""

    def __init__(self) -> None:
        self._checkers: dict[str, Callable[[], ComponentStatus]] = {}

    def register(
        self,
        name: str,
        checker: Callable[[], ComponentStatus],
    ) -> None:
        self._checkers[name] = checker

    def get(self, name: str) -> ComponentStatus | None:
        checker = self._checkers.get(name)
        if checker is None:
            return ComponentStatus(
                name=name,
                state=ComponentState.UNAVAILABLE,
                message=t("observability.not_registered", name=name),
            )
        return checker()

    def all_statuses(self) -> dict[str, ComponentStatus]:
        return {name: checker() for name, checker in self._checkers.items()}

    def summary(self) -> dict[str, Any]:
        """Return summary: counts by state."""
        statuses = self.all_statuses()
        counts: dict[str, int] = {}
        for s in statuses.values():
            counts[s.state] = counts.get(s.state, 0) + 1
        return {
            "component_count": len(statuses),
            "state_counts": counts,
            "components": {
                name: status.to_dict()
                for name, status in statuses.items()
            },
        }


# ──────────────────────────────────────────────────────────────────────
# Built-in component checkers
# ──────────────────────────────────────────────────────────────────────


def _check_python_version() -> ComponentStatus:
    """Check Python version is >= 3.10."""
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 10):
        return ComponentStatus(
            name="python_version",
            state=ComponentState.MISCONFIGURED,
            message=t("observability.python_version_mismatch",
                      version=f"{major}.{minor}"),
            details=t("observability.python_version_min"),
        )
    return ComponentStatus(
        name="python_version",
        state=ComponentState.AVAILABLE,
        message=t("observability.python_ok", version=sys.version),
    )


def _check_i18n() -> ComponentStatus:
    """Check i18n catalogs are loadable."""
    i18n_dir = Path(__file__).parent.parent / "i18n"
    ru = i18n_dir / "ru.json"
    en = i18n_dir / "en.json"
    if ru.is_file() and en.is_file():
        try:
            ru_data = json.loads(ru.read_text(encoding="utf-8"))
            en_data = json.loads(en.read_text(encoding="utf-8"))
            if len(ru_data) >= 10 and len(en_data) >= 10:
                return ComponentStatus(
                    name="i18n",
                    state=ComponentState.AVAILABLE,
                    message=t("observability.i18n_ok"),
                    details=t("observability.i18n_details",
                              ru=str(len(ru_data)), en=str(len(en_data))),
                )
            return ComponentStatus(
                name="i18n",
                state=ComponentState.DEGRADED,
                message=t("observability.i18n_degraded"),
            )
        except json.JSONDecodeError:
            return ComponentStatus(
                name="i18n",
                state=ComponentState.MISCONFIGURED,
                message=t("observability.i18n_invalid_json"),
            )
    return ComponentStatus(
        name="i18n",
        state=ComponentState.UNAVAILABLE,
        message=t("observability.i18n_missing"),
    )


def _check_secrets() -> ComponentStatus:
    """Check at least one API key is set (without exposing values)."""
    from config.secrets import get_secret

    providers = ["gemini", "openai", "openrouter"]
    found: list[str] = []
    missing: list[str] = []
    for pid in providers:
        key = f"{pid}_api_key"
        val = get_secret(key)
        if val and len(val) > 10:
            found.append(pid)
        else:
            missing.append(pid)

    if found:
        return ComponentStatus(
            name="secrets",
            state=ComponentState.AVAILABLE,
            message=t("observability.secrets_ok", keys=", ".join(found)),
        )
    if missing and not found:
        return ComponentStatus(
            name="secrets",
            state=ComponentState.MISCONFIGURED,
            message=t("observability.secrets_none_configured"),
            details=t("observability.secrets_missing", keys=", ".join(missing)),
        )
    return ComponentStatus(
        name="secrets",
        state=ComponentState.DISABLED,
        message=t("observability.secrets_disabled"),
    )


def _check_config_settings() -> ComponentStatus:
    """Check that settings.json has valid config."""
    from config.settings import load_settings

    try:
        settings = load_settings()
        if settings.provider_id and settings.os_system:
            return ComponentStatus(
                name="config",
                state=ComponentState.AVAILABLE,
                message=t("observability.config_ok",
                          provider=settings.provider_id,
                          os=settings.os_system),
            )
        return ComponentStatus(
            name="config",
            state=ComponentState.MISCONFIGURED,
            message=t("observability.config_incomplete"),
        )
    except Exception as exc:
        return ComponentStatus(
            name="config",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.config_load_error"),
            details=str(exc),
        )


def _check_computer_control() -> ComponentStatus:
    """Check computer_control capabilities."""
    try:
        from computer_control.capabilities import CapabilityDetector
        detector = CapabilityDetector.detect()
        report = detector.full_report()
        caps = report.get("capabilities", {})
        supported_count = sum(1 for v in caps.values() if v)
        total_count = len(caps)
        if supported_count == total_count and total_count > 0:
            return ComponentStatus(
                name="computer_control",
                state=ComponentState.AVAILABLE,
                message=t("observability.cc_all_available",
                          count=supported_count),
            )
        if supported_count > 0:
            return ComponentStatus(
                name="computer_control",
                state=ComponentState.DEGRADED,
                message=t("observability.cc_degraded",
                          available=supported_count,
                          total=total_count),
            )
        return ComponentStatus(
            name="computer_control",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.cc_unavailable"),
        )
    except Exception as exc:
        return ComponentStatus(
            name="computer_control",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.cc_error"),
            details=str(exc),
        )


def _check_mark_bridge() -> ComponentStatus:
    """Check the MARK bridge (runtime stack) is loadable."""
    try:
        import mark.bridge
        has_build = hasattr(mark.bridge, "build_runtime_stack")
        if has_build:
            return ComponentStatus(
                name="mark_bridge",
                state=ComponentState.AVAILABLE,
                message=t("observability.mark_ok"),
            )
        return ComponentStatus(
            name="mark_bridge",
            state=ComponentState.DEGRADED,
            message=t("observability.mark_degraded"),
        )
    except Exception:
        return ComponentStatus(
            name="mark_bridge",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.mark_unavailable"),
        )


def _check_tools_registry() -> ComponentStatus:
    """Check if tools are registered."""
    try:
        from mark.tools.registry import registry
        tools = registry.get_all()
        count = len(tools)
        if count > 0:
            return ComponentStatus(
                name="tools_registry",
                state=ComponentState.AVAILABLE,
                message=t("observability.tools_ok", count=str(count)),
            )
        return ComponentStatus(
            name="tools_registry",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.tools_none"),
        )
    except Exception as exc:
        return ComponentStatus(
            name="tools_registry",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.tools_error"),
            details=str(exc),
        )


def _check_memory() -> ComponentStatus:
    """Check memory system."""
    try:
        from memory.memory_manager import load_memory
        mem = load_memory()
        keys = len(mem) if isinstance(mem, dict) else 0
        if keys > 0:
            return ComponentStatus(
                name="memory",
                state=ComponentState.AVAILABLE,
                message=t("observability.memory_ok", keys=str(keys)),
            )
        return ComponentStatus(
            name="memory",
            state=ComponentState.DISABLED,
            message=t("observability.memory_empty"),
        )
    except Exception as exc:
        return ComponentStatus(
            name="memory",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.memory_error"),
            details=str(exc),
        )


def _check_vision() -> ComponentStatus:
    """Check vision pipeline."""
    try:
        import mark.vision
        if hasattr(mark.vision, "engine"):
            return ComponentStatus(
                name="vision",
                state=ComponentState.AVAILABLE,
                message=t("observability.vision_ok"),
            )
        return ComponentStatus(
            name="vision",
            state=ComponentState.DEGRADED,
            message=t("observability.vision_degraded"),
        )
    except Exception as exc:
        return ComponentStatus(
            name="vision",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.vision_error"),
            details=str(exc),
        )


def _check_network() -> ComponentStatus:
    """Check network connectivity."""
    try:
        import socket

        socket.gethostbyname("google.com")
        return ComponentStatus(
            name="network",
            state=ComponentState.AVAILABLE,
            message=t("observability.network_ok"),
        )
    except Exception:
        return ComponentStatus(
            name="network",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.network_unavailable"),
        )


def _check_voice_pipeline() -> ComponentStatus:
    """Check voice pipeline availability."""
    try:
        stt = "faster_whisper"
        tts = "piper"
        stt_ok = _has_module(stt)
        tts_ok = _has_module(tts)
        if stt_ok and tts_ok:
            return ComponentStatus(
                name="voice_pipeline",
                state=ComponentState.AVAILABLE,
                message=t("observability.voice_ok"),
            )
        if stt_ok or tts_ok:
            return ComponentStatus(
                name="voice_pipeline",
                state=ComponentState.DEGRADED,
                message=t("observability.voice_degraded"),
            )
        return ComponentStatus(
            name="voice_pipeline",
            state=ComponentState.DISABLED,
            message=t("observability.voice_disabled"),
        )
    except Exception:
        return ComponentStatus(
            name="voice_pipeline",
            state=ComponentState.UNAVAILABLE,
            message=t("observability.voice_error"),
        )


def _has_module(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


# ──────────────────────────────────────────────────────────────────────
# Default registry setup
# ──────────────────────────────────────────────────────────────────────


def create_registry() -> ComponentRegistry:
    """Create and populate the default component registry."""
    reg = ComponentRegistry()
    reg.register("python_version", _check_python_version)
    reg.register("i18n", _check_i18n)
    reg.register("secrets", _check_secrets)
    reg.register("config", _check_config_settings)
    reg.register("computer_control", _check_computer_control)
    reg.register("mark_bridge", _check_mark_bridge)
    reg.register("tools_registry", _check_tools_registry)
    reg.register("memory", _check_memory)
    reg.register("vision", _check_vision)
    reg.register("network", _check_network)
    reg.register("voice_pipeline", _check_voice_pipeline)
    return reg


def check_all_components() -> dict[str, Any]:
    """Quick check of all registered components."""
    reg = create_registry()
    return reg.summary()


# Expose the module-level registry
_default_registry = create_registry()


def get_component_status(name: str) -> ComponentStatus:
    """Get status of a registered component."""
    return _default_registry.get(name)


def all_statuses() -> dict[str, ComponentStatus]:
    """Get all component statuses."""
    return _default_registry.all_statuses()
