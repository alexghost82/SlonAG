"""Tests for the observability package.

Covers:
- RuntimeStatus dataclass and to_dict()
- get_status() returns valid structure
- get_capability_report() includes validation metadata
- is_capable() returns bool
"""

from __future__ import annotations

try:
    import tkinter  # noqa: F401
    _HAS_TKINTER = True
except ImportError:
    _HAS_TKINTER = False

import pytest

from observability import RuntimeStatus, get_status, get_capability_report, is_capable


def test_runtime_status_defaults():
    """Verify default values are safe (false) — no false capabilities."""
    status = RuntimeStatus()
    assert status.online is False
    assert status.paired is False
    assert status.provider_id is None
    assert status.model_id is None
    assert status.network_mode == "offline"
    assert status.privacy_profile == "fully_local"
    assert status.active_tasks == 0
    assert status.capabilities_ok is False


def test_runtime_status_to_dict():
    """Verify to_dict includes all fields."""
    status = RuntimeStatus(
        online=True,
        paired=True,
        provider_id="local",
        model_id="test-model",
        network_mode="internet",
        privacy_profile="local_only",
        active_tasks=3,
        pending_approvals=1,
        capabilities_ok=True,
    )
    d = status.to_dict()
    assert d["online"] is True
    assert d["paired"] is True
    assert d["provider_id"] == "local"
    assert d["model_id"] == "test-model"
    assert d["network_mode"] == "internet"
    assert d["privacy_profile"] == "local_only"
    assert d["active_tasks"] == 3
    assert d["pending_approvals"] == 1
    assert d["capabilities_ok"] is True


@pytest.mark.skipif(not _HAS_TKINTER, reason="tkinter not available")
def test_get_status_returns_structure():
    """get_status() returns a RuntimeStatus with expected fields."""
    status = get_status()
    assert isinstance(status, RuntimeStatus)
    d = status.to_dict()
    # Must have capabilities_ok — this is the key new field for "no false capabilities"
    assert "capabilities_ok" in d
    assert isinstance(d["capabilities_ok"], bool)
    # Must have all standard status fields
    for key in ("online", "paired", "provider_id", "model_id",
                "network_mode", "privacy_profile",
                "active_tasks", "pending_approvals"):
        assert key in d, f"Missing key in to_dict: {key}"


@pytest.mark.skipif(not _HAS_TKINTER, reason="tkinter not available")
def test_get_capability_report_has_validation():
    """capability report includes runtime validation metadata."""
    report = get_capability_report()
    assert isinstance(report, dict)
    assert "platform" in report
    assert "capabilities" in report
    assert "validated_at_runtime" in report
    assert report["validated_at_runtime"] is True
    assert "validated_capabilities" in report


@pytest.mark.skipif(not _HAS_TKINTER, reason="tkinter not available")
def test_is_capable_returns_bool():
    """is_capable() returns a bool for known capabilities."""
    for cap in ("input", "screenshot", "clipboard",
                "window_management", "clipboard",
                "system_settings", "app_launch", "screen_info", "platform"):
        result = is_capable(cap)
        assert isinstance(result, bool), f"is_capable({cap!r}) returned {type(result)}"


@pytest.mark.skipif(not _HAS_TKINTER, reason="tkinter not available")
def test_capability_report_platform():
    """Report includes platform info from the detector."""
    report = get_capability_report()
    assert report["platform"] in ("linux", "macos", "windows", "unknown")
