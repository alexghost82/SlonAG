from __future__ import annotations

import pytest

from config.schema import (
    DEFAULT_LANGUAGE,
    SettingsValidationError,
    default_settings,
    validate_settings,
)


def test_defaults_use_russian_language():
    settings = validate_settings({})
    assert settings.language == DEFAULT_LANGUAGE == "ru"
    assert settings.privacy_profile == "hybrid"
    assert settings.provider_id == "gemini"
    assert settings.network_mode == "hybrid"
    assert settings.routing_mode == "manual"
    assert settings.local_models.default_provider == "ollama"
    assert settings.local_models.ollama.base_url == "http://127.0.0.1:11434"
    assert settings.local_models.llama_cpp.base_url == "http://127.0.0.1:8080"
    assert settings.os_system is None
    assert settings.camera_index is None


def test_rejects_invalid_privacy_profile_type():
    with pytest.raises(SettingsValidationError, match="privacy_profile"):
        validate_settings({"privacy_profile": 1})


def test_rejects_unknown_privacy_profile():
    with pytest.raises(SettingsValidationError, match="privacy_profile"):
        validate_settings({"privacy_profile": "unknown-profile"})


def test_rejects_invalid_provider_type():
    with pytest.raises(SettingsValidationError, match="provider_id"):
        validate_settings({"provider_id": ["gemini"]})


def test_rejects_unknown_provider():
    with pytest.raises(SettingsValidationError, match="provider_id"):
        validate_settings({"provider_id": "not-a-provider"})


def test_rejects_invalid_language_type():
    with pytest.raises(SettingsValidationError, match="language"):
        validate_settings({"language": None})


def test_rejects_invalid_network_mode_type():
    with pytest.raises(SettingsValidationError, match="network_mode"):
        validate_settings({"network_mode": 0})


def test_rejects_invalid_model_roles_type():
    with pytest.raises(SettingsValidationError, match="model_roles"):
        validate_settings({"model_roles": "chat"})


def test_rejects_non_string_model_role():
    with pytest.raises(SettingsValidationError, match="model_roles.chat"):
        validate_settings({"model_roles": {"chat": 12}})


def test_rejects_unknown_model_role():
    with pytest.raises(SettingsValidationError, match="unknown role"):
        validate_settings({"model_roles": {"music": ""}})


def test_rejects_secret_fields():
    with pytest.raises(SettingsValidationError, match="secret field"):
        validate_settings({"gemini_api_key": "should-not-be-here"})


def test_rejects_invalid_os_system_type():
    with pytest.raises(SettingsValidationError, match="os_system"):
        validate_settings({"os_system": 3})


@pytest.mark.parametrize("value", [-1, True, "0"])
def test_rejects_invalid_camera_index(value):
    with pytest.raises(SettingsValidationError, match="camera_index"):
        validate_settings({"camera_index": value})


def test_camera_index_round_trip():
    settings = validate_settings({"camera_index": 2})
    assert settings.camera_index == 2
    assert validate_settings(settings.to_dict()) == settings


def test_rejects_non_object_payload():
    with pytest.raises(SettingsValidationError, match="object"):
        validate_settings(["not", "an", "object"])


def test_default_settings_round_trip():
    assert default_settings() == validate_settings(default_settings().to_dict())


def test_local_models_config_round_trip():
    settings = validate_settings(
        {
            "provider_id": "llama_cpp",
            "routing_mode": "local_only",
            "local_models": {
                "default_provider": "local",
                "ollama": {"enabled": False, "base_url": "http://localhost:11434"},
                "llama_cpp": {"enabled": True, "base_url": "http://127.0.0.1:9000"},
                "preferred": {"chat": "qwen", "utility": "tiny"},
                "overrides": {
                    "qwen": {
                        "tool_calling": True,
                        "structured_output": True,
                        "vision": False,
                        "context_length": 32768,
                    }
                },
            },
        }
    )

    assert settings == validate_settings(settings.to_dict())
    assert settings.local_models.preferred.chat == "qwen"
    assert settings.local_models.overrides["qwen"].tool_calling is True


@pytest.mark.parametrize("provider_id", ["local", "ollama", "llama_cpp"])
def test_all_local_provider_ids_are_supported(provider_id):
    assert validate_settings({"provider_id": provider_id}).provider_id == provider_id


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"routing_mode": "automatic"}, "routing_mode"),
        ({"local_models": []}, "local_models must be an object"),
        ({"local_models": {"ollama": {"enabled": 1}}}, "enabled"),
        ({"local_models": {"llama_cpp": {"base_url": ""}}}, "base_url"),
        (
            {"local_models": {"overrides": {"m": {"tool_calling": "yes"}}}},
            "tool_calling",
        ),
        (
            {"local_models": {"overrides": {"m": {"context_length": True}}}},
            "context_length",
        ),
        (
            {"local_models": {"overrides": {"m": {"context_length": 0}}}},
            "context_length",
        ),
        ({"local_models": {"overrides": {"": {}}}}, "model ids"),
        ({"local_models": {"preferred": {"vision": "m"}}}, "unknown field"),
    ],
)
def test_rejects_malformed_local_model_config(payload, match):
    with pytest.raises(SettingsValidationError, match=match):
        validate_settings(payload)


# ── Tests for model_id and provider_settings ──────────────────────────

def test_model_id_empty_by_default():
    s = validate_settings({})
    assert s.model_id == ""


def test_model_id_accepted_when_present():
    s = validate_settings({"model_id": "gpt-4o"})
    assert s.model_id == "gpt-4o"


def test_model_id_rejects_non_string():
    with pytest.raises(SettingsValidationError, match="model_id"):
        validate_settings({"model_id": 42})


def test_model_id_round_trip():
    s = validate_settings({"model_id": "claude-3-opus"})
    s2 = validate_settings(s.to_dict())
    assert s2.model_id == "claude-3-opus"


def test_provider_settings_empty_by_default():
    s = validate_settings({})
    assert s.provider_settings == {}


def test_provider_settings_accepted():
    raw = {"ollama": {"base_url": "http://localhost:11434", "remote_enabled": False}}
    s = validate_settings({"provider_settings": raw})
    assert "ollama" in s.provider_settings
    assert s.provider_settings["ollama"].base_url == "http://localhost:11434"


def test_provider_settings_rejects_unknown_provider():
    with pytest.raises(SettingsValidationError, match="unknown provider"):
        validate_settings({"provider_settings": {"fake": {"base_url": ""}}})


def test_provider_settings_rejects_invalid_remote_enabled():
    with pytest.raises(SettingsValidationError, match="remote_enabled"):
        validate_settings(
            {"provider_settings": {"ollama": {"remote_enabled": "yes"}}}
        )


def test_provider_settings_round_trip():
    raw = {"ollama": {"base_url": "http://custom:11434", "remote_enabled": True}}
    s = validate_settings({"provider_settings": raw})
    s2 = validate_settings(s.to_dict())
    assert s2.provider_settings["ollama"].base_url == "http://custom:11434"
    assert s2.provider_settings["ollama"].remote_enabled is True


def test_provider_settings_multiple_providers():
    raw = {
        "ollama": {"base_url": "http://a:11434", "remote_enabled": False},
        "llama_cpp": {"base_url": "http://b:8080", "remote_enabled": True},
    }
    s = validate_settings({"provider_settings": raw})
    assert len(s.provider_settings) == 2
    assert "ollama" in s.provider_settings
    assert "llama_cpp" in s.provider_settings


def test_provider_settings_rejects_non_object_value():
    with pytest.raises(SettingsValidationError, match="must be an object"):
        validate_settings({"provider_settings": {"ollama": "not-a-dict"}})


def test_provider_settings_rejects_unknown_keys_in_nested():
    # provider_settings.{pid} accepts base_url and remote_enabled only
    with pytest.raises(SettingsValidationError, match="unknown field"):
        validate_settings(
            {"provider_settings": {"ollama": {"unknown_key": "x", "base_url": ""}}}
        )


def test_openai_compat_provider_settings():
    s = validate_settings(
        {"provider_settings": {"openai_compat": {"base_url": "http://10.0.0.1:9000/v1", "remote_enabled": True}}}
    )
    assert s.provider_settings["openai_compat"].base_url == "http://10.0.0.1:9000/v1"


def test_full_round_trip_with_all_new_fields():
    raw = {
        "provider_id": "openai",
        "model_id": "gpt-4o-mini",
        "provider_settings": {
            "ollama": {"base_url": "http://127.0.0.1:11434", "remote_enabled": False},
            "llama_cpp": {"base_url": "http://127.0.0.1:8080", "remote_enabled": True},
        },
    }
    s = validate_settings(raw)
    assert s.provider_id == "openai"
    assert s.model_id == "gpt-4o-mini"
    assert len(s.provider_settings) == 2
    s2 = validate_settings(s.to_dict())
    assert s2.provider_id == "openai"
    assert s2.model_id == "gpt-4o-mini"
    assert s2.provider_settings == s.provider_settings
