"""Compatibility adapters for the existing :mod:`actions` entry points."""

from mark.tools.legacy.adapters import (
    LEGACY_HANDLERS,
    agent_task_handler,
    normalize_legacy_result,
)

__all__ = ["LEGACY_HANDLERS", "agent_task_handler", "normalize_legacy_result"]
