from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
from config.schema import validate_settings
from config.settings import load_settings, save_settings


def test_missing_api_keys_does_not_raise_from_get_config(isolated_paths):
    missing = isolated_paths / "api_keys.json"
    assert not missing.exists()
    payload = config.get_config()
    assert isinstance(payload, dict)
    assert payload["os_system"] in {"windows", "mac", "linux"}
    assert "gemini_api_key" not in payload
    assert "openrouter_api_key" not in payload
    assert "openai_api_key" not in payload


def test_missing_api_keys_does_not_raise_from_get_os(isolated_paths):
    assert not (isolated_paths / "api_keys.json").exists()
    assert config.get_os() in {"windows", "mac", "linux"}


def test_get_os_returns_supported_host_value():
    assert config.get_os() in {"windows", "mac", "linux"}


def test_os_helpers_match_get_os(isolated_paths):
    current = config.get_os()
    assert config.is_windows() is (current == "windows")
    assert config.is_mac() is (current == "mac")
    assert config.is_linux() is (current == "linux")


def test_settings_overlay_changes_get_os(isolated_paths):
    save_settings(validate_settings({"os_system": "linux"}))
    assert config.get_os() == "linux"
    assert config.get_config()["os_system"] == "linux"


def test_settings_example_has_no_secret_values():
    example_path = Path(config.__file__).resolve().parent / "settings.example.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    markers = ("api_key", "token", "secret", "password")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_l = str(key).lower()
                if any(marker in key_l for marker in markers):
                    if isinstance(value, str) and value.strip():
                        pytest.fail(f"example secret-like field {key!r} is non-empty")
                    if isinstance(value, (dict, list)) and value:
                        pytest.fail(f"example secret-like field {key!r} is non-empty")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)


def test_local_model_settings_persist_offline(tmp_path):
    path = tmp_path / "settings.json"
    expected = validate_settings(
        {
            "network_mode": "offline",
            "routing_mode": "local_only",
            "local_models": {
                "default_provider": "ollama",
                "preferred": {"planning": "qwen-local"},
                "overrides": {
                    "qwen-local": {"tool_calling": True, "context_length": 8192}
                },
            },
        }
    )

    save_settings(expected, path)

    assert load_settings(path) == expected
