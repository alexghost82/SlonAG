from __future__ import annotations

import pytest

from providers.capabilities import (
    require_capabilities,
    require_capability,
    supports,
)
from providers.contracts import ModelInfo
from providers.errors import CapabilityError


def _model(**flags: bool) -> ModelInfo:
    return ModelInfo(
        provider_id="local",
        model_id="cap-check",
        display_name="Capability check",
        text=flags.get("text", False),
        streaming=flags.get("streaming", False),
        structured_output=flags.get("structured_output", False),
        tool_calling=flags.get("tool_calling", False),
        vision=flags.get("vision", False),
        audio_input=flags.get("audio_input", False),
        audio_output=flags.get("audio_output", False),
        embeddings=flags.get("embeddings", False),
    )


@pytest.mark.parametrize(
    ("flag", "role"),
    [
        ("text", "chat"),
        ("text", "planning"),
        ("text", "code"),
        ("vision", "vision"),
        ("embeddings", "embeddings"),
        ("audio_input", "stt"),
        ("audio_output", "tts"),
    ],
)
def test_supports_accepts_matching_role(flag: str, role: str) -> None:
    model = _model(**{flag: True})
    assert supports(model, role) is True
    require_capability(model, role)


@pytest.mark.parametrize(
    ("flag", "role"),
    [
        ("text", "chat"),
        ("text", "planning"),
        ("text", "code"),
        ("vision", "vision"),
        ("embeddings", "embeddings"),
        ("audio_input", "stt"),
        ("audio_output", "tts"),
    ],
)
def test_supports_rejects_missing_capability(flag: str, role: str) -> None:
    model = _model(**{flag: False})
    assert supports(model, role) is False
    with pytest.raises(CapabilityError) as exc_info:
        require_capability(model, role)
    assert exc_info.value.role == role
    assert exc_info.value.model_id == "cap-check"
    assert exc_info.value.provider_id == "local"


def test_unknown_role_is_unsupported() -> None:
    model = _model(text=True)
    assert supports(model, "music") is False
    with pytest.raises(CapabilityError, match="music"):
        require_capability(model, "music")


def test_text_model_does_not_serve_vision() -> None:
    model = _model(text=True, vision=False)
    assert supports(model, "chat") is True
    assert supports(model, "vision") is False
    with pytest.raises(CapabilityError, match="vision"):
        require_capability(model, "vision")


def test_require_capabilities_accepts_all_supported_flags() -> None:
    require_capabilities(
        _model(text=True, tool_calling=True),
        {"text", "tool_calling"},
    )


def test_require_capabilities_rejects_missing_and_unknown_flags() -> None:
    model = _model(text=True, tool_calling=False)
    with pytest.raises(CapabilityError, match="tool_calling") as exc_info:
        require_capabilities(model, ("text", "tool_calling", "future_capability"))
    assert exc_info.value.role == "tool_calling"
    assert exc_info.value.model_id == model.model_id
