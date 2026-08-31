"""Capability report — delegates to computer_control with runtime validation.

This module exposes a clean, stable API for querying capabilities
so that every caller gets the same truth: capabilities reflect
*actual runtime state, not static detection.
"""

from __future__ import annotations

from computer_control.capabilities import CapabilityDetector, check_capabilities


def get_capability_report() -> dict:
    """Return the current capability report.

    Unlike the raw ``check_capabilities()``, this version runs
    runtime validation (``detect().validate()``) so that the
    reported capabilities match what actually works at this moment.
    """
    det = CapabilityDetector.detect()
    det.validate()  # ensures runtime-checked results are used

    report = det.full_report()

    # ── Add validation metadata ────────────────────────────────
    report["validated_at_runtime"] = det._runtime_checked
    report["validated_capabilities"] = dict(det._validated)

    return report


def is_capable(capability: str) -> bool:
    """Quick check: does the system actually support *capability*?

    After validation, this returns the runtime-confirmed result
    (not the static tool-presence result).
    """
    det = CapabilityDetector.detect()
    det.validate()
    return det.get(capability).supported


__all__ = [
    "get_capability_report",
    "is_capable",
]
