from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from config.secrets import (
    SecretStoreError,
    get_secret,
    set_secret,
)
from config.settings import load_settings, save_settings


SENTINEL = "dummy-not-a-live-key-XYZ-4242"


def test_production_code_does_not_access_legacy_key_file_directly() -> None:
    root = Path(__file__).resolve().parents[3]
    forbidden_names = ("API_FILE", "API_CONFIG_PATH", "API_KEY_PATH")
    violations: list[str] = []
    candidates = [root / "main.py", root / "or_client.py", root / "setup.py"]
    for package in ("actions", "agent", "runtime", "providers", "acta"):
        candidates.extend((root / package).rglob("*.py"))

    for path in candidates:
        source = path.read_text(encoding="utf-8")
        if any(name in source for name in forbidden_names):
            violations.append(str(path.relative_to(root)))

    assert violations == []


@pytest.fixture
def file_fallback(isolated_paths, monkeypatch):
    import config.secrets as secrets

    monkeypatch.setattr(secrets, "_system_store_available", lambda: False)
    return isolated_paths / "api_keys.json"


def test_file_fallback_writes_mode_0600(file_fallback):
    if os.name == "nt":
        pytest.skip("POSIX 0600 mode is not applicable on Windows")
    set_secret("gemini_api_key", SENTINEL)
    assert file_fallback.is_file()
    mode = stat.S_IMODE(file_fallback.stat().st_mode)
    assert mode == 0o600
    assert get_secret("gemini_api_key") == SENTINEL
    assert SENTINEL not in file_fallback.name


def test_file_fallback_round_trip(file_fallback):
    set_secret("openrouter_api_key", SENTINEL)
    assert get_secret("openrouter_api_key") == SENTINEL
    assert get_secret("openai_api_key") is None


def test_file_fallback_repairs_existing_permissions(file_fallback):
    if os.name == "nt":
        pytest.skip("POSIX modes are not applicable on Windows")
    file_fallback.write_text(
        '{"gemini_api_key": "' + SENTINEL + '"}', encoding="utf-8"
    )
    file_fallback.chmod(0o644)

    assert get_secret("gemini_api_key") == SENTINEL
    assert stat.S_IMODE(file_fallback.stat().st_mode) == 0o600


def test_missing_fallback_file_returns_none(file_fallback):
    assert not file_fallback.exists()
    assert get_secret("gemini_api_key") is None


def test_secret_helpers_do_not_echo_values(file_fallback, monkeypatch):
    import config.secrets as secrets

    def boom(_name: str, _value: str) -> None:
        raise RuntimeError(f"backend exploded while writing {SENTINEL}")

    monkeypatch.setattr(secrets, "_file_set", boom)
    with pytest.raises(SecretStoreError) as exc_info:
        set_secret("gemini_api_key", SENTINEL)
    message = str(exc_info.value)
    assert SENTINEL not in message
    assert SENTINEL not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_unknown_secret_name_rejected(file_fallback):
    with pytest.raises(ValueError, match="unknown secret name"):
        get_secret("not_a_real_secret")


def test_settings_save_does_not_store_api_keys(isolated_paths):
    settings_path = isolated_paths / "settings.json"
    save_settings(
        {
            "privacy_profile": "cloud",
            "provider_id": "openai",
            "language": "ru",
        }
    )
    loaded = load_settings()
    assert loaded.provider_id == "openai"
    text = settings_path.read_text(encoding="utf-8")
    assert "api_key" not in text
    assert SENTINEL not in text


def test_set_secret_does_not_use_file_when_system_store_available(
    isolated_paths, monkeypatch
):
    import config.secrets as secrets

    stored: dict[str, str] = {}

    monkeypatch.setattr(secrets, "_system_store_available", lambda: True)
    monkeypatch.setattr(
        secrets, "_system_set", lambda name, value: stored.update({name: value})
    )
    monkeypatch.setattr(secrets, "_system_get", lambda name: stored.get(name))

    set_secret("openai_api_key", SENTINEL)
    assert get_secret("openai_api_key") == SENTINEL
    assert not (isolated_paths / "api_keys.json").exists()
