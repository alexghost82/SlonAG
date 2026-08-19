"""Load and save non-secret settings from ``config/settings.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import Settings, SettingsValidationError, default_settings, validate_settings

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    """Return persisted settings, or defaults when the file is missing."""
    target = path or SETTINGS_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default_settings()
    except OSError as exc:
        raise SettingsValidationError("unable to read settings") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SettingsValidationError("settings file is not valid JSON") from exc
    return validate_settings(payload)


def save_settings(settings: Settings | dict[str, Any], path: Path | None = None) -> Settings:
    """Validate and write non-secret settings. Never stores API keys."""
    validated = settings if isinstance(settings, Settings) else validate_settings(settings)
    target = path or SETTINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(validated.to_dict(), indent=2, ensure_ascii=False) + "\n"
    target.write_text(payload, encoding="utf-8")
    return validated
