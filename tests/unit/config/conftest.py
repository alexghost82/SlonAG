from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Point settings and the secret fallback at a temporary directory."""
    import config
    import config.secrets as secrets
    import config.settings as settings

    settings_path = tmp_path / "settings.json"
    fallback_path = tmp_path / "api_keys.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(secrets, "FALLBACK_PATH", fallback_path)
    monkeypatch.setattr(config, "_LEGACY_KEYS_PATH", fallback_path)
    return tmp_path
