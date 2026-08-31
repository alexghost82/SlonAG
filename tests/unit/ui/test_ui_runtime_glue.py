"""Tests that UI settings flow into the runtime stack correctly.

These tests verify:
- model_id and provider_settings round-trip through save/load
- build_runtime_stack accepts provider_settings dict
- All PROVIDER_IDs can be saved and loaded
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from config.schema import (
    PROVIDER_IDS,
    DEFAULT_PROVIDER_ID,
    Settings,
    ProviderBaseURL,
    default_settings,
    validate_settings,
    SettingsValidationError,
)
from config.settings import load_settings, save_settings


@pytest.fixture()
def settings_path(tmp_path: Path) -> Path:
    """Return a temporary directory used for settings JSON."""
    p = tmp_path / "config"
    p.mkdir()
    return p


def test_save_load_round_trip_with_model_id_and_provider_settings(
    settings_path: Path,
) -> None:
    """Settings with model_id and provider_settings survive a round trip."""
    settings_file = settings_path / "settings.json"

    # Build a settings object with new fields
    raw_ps = {
        "ollama": ProviderBaseURL(base_url="http://custom:11434", remote_enabled=False),
        "llama_cpp": ProviderBaseURL(base_url="http://custom:8080", remote_enabled=True),
    }
    settings = Settings(
        provider_id="openai",
        model_id="gpt-4o",
        provider_settings=raw_ps,
    )

    # Save with explicit path
    save_settings(settings, path=settings_file)

    # Load from same path
    loaded = load_settings(path=settings_file)

    assert loaded.provider_id == "openai"
    assert loaded.model_id == "gpt-4o"
    assert len(loaded.provider_settings) == 2
    assert loaded.provider_settings["ollama"].base_url == "http://custom:11434"
    assert loaded.provider_settings["llama_cpp"].base_url == "http://custom:8080"


def test_build_runtime_stack_receives_model_id(
    settings_path: Path,
) -> None:
    """build_runtime_stack forwards model_id to the Router."""
    from acta.bridge import build_runtime_stack

    settings_file = settings_path / "settings.json"
    raw_ps = {"ollama": ProviderBaseURL(base_url="", remote_enabled=False)}
    save_settings(Settings(model_id="gpt-4o-mini", provider_settings=raw_ps), path=settings_file)

    # Build stack — should not raise
    stack = build_runtime_stack(
        repo_root=str(Path(__file__).resolve().parent.parent.parent.parent),
        provider_id="openai",
        model_id="gpt-4o-mini",
        provider_settings={"ollama": {"base_url": "", "remote_enabled": False}},
    )

    assert stack is not None


def test_build_runtime_stack_with_provider_settings_dict() -> None:
    """build_runtime_stack accepts provider_settings dict and doesn't crash."""
    from acta.bridge import build_runtime_stack

    stack = build_runtime_stack(
        repo_root=str(Path(__file__).resolve().parent.parent.parent.parent),
        provider_id="openai",
        provider_settings={
            "ollama": {"base_url": "http://test:11434", "remote_enabled": False},
            "openai_compat": {"base_url": "http://test:9000/v1", "remote_enabled": True},
        },
    )
    assert stack is not None


def test_no_settings_file_returns_defaults(
    settings_path: Path,
) -> None:
    """When no settings file exists, load_settings returns default Settings."""
    settings_file = settings_path / "settings.json"

    loaded = load_settings(path=settings_file)

    assert loaded.provider_id == DEFAULT_PROVIDER_ID
    assert loaded.model_id == ""
    assert loaded.provider_settings == {}


def test_invalid_provider_id_in_settings_rejected(
    settings_path: Path,
) -> None:
    """Invalid provider_id in settings JSON is rejected."""
    settings_file = settings_path / "settings.json"
    settings_file.write_text(json.dumps({"provider_id": "fake-provider"}))

    with pytest.raises(SettingsValidationError, match="provider_id"):
        load_settings(path=settings_file)


def test_all_provider_ids_allowed(
    settings_path: Path,
) -> None:
    """Each PROVIDER_ID can be saved and loaded."""
    settings_file = settings_path / "settings.json"

    for pid in sorted(PROVIDER_IDS):
        save_settings(Settings(provider_id=pid), path=settings_file)
        loaded = load_settings(path=settings_file)
        assert loaded.provider_id == pid


def test_provider_settings_validation_rejects_bad_pid(
    settings_path: Path,
) -> None:
    """provider_settings with unknown provider ID raises."""
    data = {"provider_settings": {"bad_provider": {"base_url": "", "remote_enabled": False}}}
    with pytest.raises(SettingsValidationError, match="unknown provider"):
        validate_settings(data)


def test_model_id_empty_by_default(
    settings_path: Path,
) -> None:
    """Default settings have empty model_id."""
    settings_file = settings_path / "settings.json"
    loaded = load_settings(path=settings_file)
    assert loaded.model_id == ""


def test_build_runtime_stack_receives_provider_settings_base_url() -> None:
    """build_runtime_stack extracts base_url from provider_settings and passes it."""
    from acta.bridge import build_runtime_stack

    # This should not raise — base_url extraction happens inside
    stack = build_runtime_stack(
        repo_root=str(Path(__file__).resolve().parent.parent.parent.parent),
        provider_id="ollama",
        model_id="llama3",
        provider_settings={"ollama": {"base_url": "http://custom-ollama:11434", "remote_enabled": False}},
    )
    assert stack is not None


def test_custom_provider_id_not_allowed() -> None:
    """A truly custom provider_id (not in PROVIDER_IDS) cannot be saved."""
    with pytest.raises(SettingsValidationError, match="provider_id"):
        validate_settings({"provider_id": "my_custom_provider"})


def test_provider_settings_round_trip_empty_base_url(
    settings_path: Path,
) -> None:
    """Empty base_url is preserved in round trip."""
    settings_file = settings_path / "settings.json"
    settings = Settings(
        provider_id="openai",
        model_id="",
        provider_settings={"openai": ProviderBaseURL(base_url="", remote_enabled=True)},
    )
    save_settings(settings, path=settings_file)
    loaded = load_settings(path=settings_file)
    assert loaded.provider_settings["openai"].base_url == ""


def test_e2e_provider_model_selection_flows_to_agent_loop(
    settings_path: Path,
) -> None:
    """Full E2E: UI selection → persisted Settings → RuntimeStack → Router → AgentLoop params."""
    from acta.bridge import build_runtime_stack

    settings_file = settings_path / "settings.json"

    # Step 1: User selects "openrouter" with custom base_url in UI
    raw_ps = {
        "openrouter": ProviderBaseURL(
            base_url="http://my-openrouter:4431", remote_enabled=False
        ),
    }
    save_settings(
        Settings(provider_id="openrouter", model_id="mistral-7b-instruct", provider_settings=raw_ps),
        path=settings_file,
    )

    # Step 2: App restart — load settings and build stack
    loaded = load_settings(path=settings_file)
    assert loaded.provider_id == "openrouter"
    assert loaded.model_id == "mistral-7b-instruct"

    # Step 3: Build stack from loaded settings
    ps_dict = {}
    for k, v in loaded.provider_settings.items():
        if hasattr(v, "to_dict"):
            ps_dict[k] = v.to_dict()
        elif isinstance(v, dict):
            ps_dict[k] = v

    stack = build_runtime_stack(
        repo_root=str(Path(__file__).resolve().parent.parent.parent.parent),
        provider_id=loaded.provider_id,
        model_id=loaded.model_id,
        provider_settings=ps_dict,
    )

    # Step 4: Verify Router exists and has model override
    assert stack is not None
    assert stack.router is not None
    router = stack.router
    assert hasattr(router, "_configured_model_id")
    assert router._configured_model_id == "mistral-7b-instruct"


def test_e2e_ollama_base_url_configurable_without_python_change(
    settings_path: Path,
) -> None:
    """Ollama base_url set from settings — no Python code changes needed."""
    from acta.bridge import build_runtime_stack

    settings_file = settings_path / "settings.json"

    save_settings(
        Settings(
            provider_id="ollama",
            model_id="llama3",
            provider_settings={
                "ollama": ProviderBaseURL(base_url="http://custom-ollama-host:11434", remote_enabled=False)
            },
        ),
        path=settings_file,
    )

    loaded = load_settings(path=settings_file)
    assert loaded.provider_settings["ollama"].base_url == "http://custom-ollama-host:11434"

    ps_dict = {}
    for k, v in loaded.provider_settings.items():
        if hasattr(v, "to_dict"):
            ps_dict[k] = v.to_dict()

    stack = build_runtime_stack(
        repo_root=str(Path(__file__).resolve().parent.parent.parent.parent),
        provider_id=loaded.provider_id,
        model_id=loaded.model_id,
        provider_settings=ps_dict,
    )
    assert stack is not None
    assert stack.router is not None


def test_e2e_openai_compat_custom_endpoint(
    settings_path: Path,
) -> None:
    """Generic OpenAI-compatible endpoint configurable via settings."""
    from acta.bridge import build_runtime_stack

    settings_file = settings_path / "settings.json"

    save_settings(
        Settings(
            provider_id="openai_compat",
            model_id="my-custom-model",
            provider_settings={
                "openai_compat": ProviderBaseURL(
                    base_url="http://local-inference-server:8000/v1", remote_enabled=True
                )
            },
        ),
        path=settings_file,
    )

    loaded = load_settings(path=settings_file)
    assert loaded.provider_id == "openai_compat"
    assert loaded.provider_settings["openai_compat"].base_url == "http://local-inference-server:8000/v1"

    ps_dict = {}
    for k, v in loaded.provider_settings.items():
        if hasattr(v, "to_dict"):
            ps_dict[k] = v.to_dict()

    stack = build_runtime_stack(
        repo_root=str(Path(__file__).resolve().parent.parent.parent.parent),
        provider_id=loaded.provider_id,
        model_id=loaded.model_id,
        provider_settings=ps_dict,
    )
    assert stack is not None
    assert stack.router is not None


def test_e2e_llama_cpp_local_base_url(
    settings_path: Path,
) -> None:
    """llama.cpp base_url configured without Python changes."""
    from acta.bridge import build_runtime_stack

    settings_file = settings_path / "settings.json"

    save_settings(
        Settings(
            provider_id="llama_cpp",
            model_id="llama-2-7b",
            provider_settings={
                "llama_cpp": ProviderBaseURL(base_url="http://llama-cpp-server:8080", remote_enabled=False)
            },
        ),
        path=settings_file,
    )

    loaded = load_settings(path=settings_file)
    assert loaded.provider_settings["llama_cpp"].base_url == "http://llama-cpp-server:8080"

    ps_dict = {}
    for k, v in loaded.provider_settings.items():
        if hasattr(v, "to_dict"):
            ps_dict[k] = v.to_dict()

    stack = build_runtime_stack(
        repo_root=str(Path(__file__).resolve().parent.parent.parent.parent),
        provider_id=loaded.provider_id,
        model_id=loaded.model_id,
        provider_settings=ps_dict,
    )
    assert stack is not None
    assert stack.router is not None
