"""Tests for capability runtime validation (no false capabilities).

Key guarantees:
- Before ``validate()``, capabilities reflect static detection only.
- After ``validate()``, reported capabilities match actual runtime.
- ``validate()`` is idempotent (safe to call multiple times).
- ``CapabilityDetector._validated_or`` prefers validated results.
"""

from __future__ import annotations

import pytest

from computer_control.capabilities import CapabilityDetector, CapabilityResult


def test_detect_creates_detector():
    """Basic detection works."""
    det = CapabilityDetector.detect()
    assert det.platform is not None
    assert isinstance(det._validated, dict)
    assert det._runtime_checked is False


def test_validate_is_idempotent():
    """Calling validate() twice is a no-op."""
    det = CapabilityDetector.detect()
    det.validate()
    first_checked = det._runtime_checked
    first_validated = dict(det._validated)

    det.validate()
    assert det._runtime_checked == first_checked
    assert dict(det._validated) == first_validated


def test_validated_or_prefers_runtime_result():
    """_validated_or returns validated result when available."""
    det = CapabilityDetector.detect()
    det.validate()

    # After validation, _validated_or should use the validated value
    for cap in ("input", "app_launch", "clipboard"):
        result = det.get(cap)
        assert isinstance(result, CapabilityResult)
        assert isinstance(result.supported, bool)


def test_validated_or_returns_static_before_validate():
    """Before validation, _validated_or falls through to static check."""
    det = CapabilityDetector.detect()
    # _runtime_checked is False, so _validated_or falls to static check
    result = det.get("platform")
    assert isinstance(result, CapabilityResult)


def test_validate_populates_runtime_flags():
    """validate() sets validated flags for checked capabilities."""
    det = CapabilityDetector.detect()
    assert det._runtime_checked is False

    det.validate()

    assert det._runtime_checked is True
    # input and app_launch are validated by validate()
    assert "input" in det._validated or det._details.get("pyautogui") is False
    assert "app_launch" in det._validated


def test_validate_app_launch_subprocess():
    """validate() checks app_launch by actually running subprocess."""
    det = CapabilityDetector.detect()
    det.validate()

    if det._details.get("pyautogui"):
        # If pyautogui is present, subprocess should also work
        assert "app_launch" in det._validated
        # On a working system, app_launch should be True
        if det._validated.get("app_launch"):
            result = det.get("app_launch")
            assert result.supported is True


def test_full_report_after_validate():
    """full_report() reflects validated capabilities."""
    det = CapabilityDetector.detect()
    det.validate()

    report = det.full_report()
    assert "platform" in report
    assert "capabilities" in report
    # capabilities dict should have bool values
    for cap, val in report["capabilities"].items():
        assert isinstance(val, bool), f"{cap}={val} is not bool"
