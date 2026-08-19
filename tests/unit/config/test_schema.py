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
