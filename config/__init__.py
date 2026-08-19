"""Application configuration facade.

``get_config()`` is a compatibility helper for non-secret values such as
``os_system``. New code should use ``load_settings`` and ``get_secret``.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from .schema import (
    Settings,
    SettingsValidationError,
    default_settings,
    validate_settings,
)
from .secrets import (
    KNOWN_SECRET_NAMES,
    SecretStoreError,
    get_secret,
    set_secret,
)
from .settings import load_settings, save_settings

_LEGACY_KEYS_PATH = Path(__file__).resolve().parent / "api_keys.json"

__all__ = [
    "KNOWN_SECRET_NAMES",
    "SecretStoreError",
    "Settings",
    "SettingsValidationError",
    "default_settings",
    "get_config",
    "get_os",
    "get_secret",
    "is_linux",
    "is_mac",
    "is_windows",
    "load_settings",
    "save_settings",
    "set_secret",
    "validate_settings",
]


def _detect_host_os() -> str:
    system = platform.system().lower()
    plat = sys.platform.lower()
    if system == "darwin" or plat == "darwin":
        return "mac"
    if system == "windows" or plat.startswith("win"):
        return "windows"
    return "linux"


def get_os() -> str:
    """Return ``windows``, ``mac``, or ``linux``.

    Host detection uses ``platform`` / ``sys.platform``. A valid ``os_system``
    value in settings overlays the detected host when present.
    """
    detected = _detect_host_os()
    try:
        overlay = load_settings().os_system
    except SettingsValidationError:
        overlay = None
    if overlay in {"windows", "mac", "linux"}:
        return overlay
    return detected


def get_config() -> dict:
    """Return non-secret config. Missing ``api_keys.json`` is not an error.

    Live API keys are not read here. ``os_system`` is always present so older
    callers keep working.
    """
    try:
        data = load_settings().to_dict()
    except (OSError, json.JSONDecodeError, SettingsValidationError):
        data = default_settings().to_dict()
    data["os_system"] = get_os()
    return data


def is_windows() -> bool:
    return get_os() == "windows"


def is_mac() -> bool:
    return get_os() == "mac"


def is_linux() -> bool:
    return get_os() == "linux"
