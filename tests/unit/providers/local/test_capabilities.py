from __future__ import annotations

import pytest

from providers.local import (
    LocalModelCapabilities,
    OllamaChatProvider,
    OpenAICompatibleChatProvider,
    resolve_local_capabilities,
)
from tests.unit.providers.local.fakes import FakeTransport


def test_unknown_model_uses_conservative_defaults() -> None:
    assert resolve_local_capabilities("local", "unknown", None) == (
        LocalModelCapabilities()
    )


def test_sources_merge_per_field_and_runtime_has_highest_priority() -> None:
    capabilities = resolve_local_capabilities(
        "ollama",
        "llama3.1:8b",
        {"tool_calling": False, "vision": True, "context_length": 8192},
        {"tool_calling": True, "structured_output": True, "context_length": 4096},
    )

    assert capabilities.tool_calling is False
    assert capabilities.structured_output is True
    assert capabilities.vision is True
    assert capabilities.context_length == 8192


def test_known_model_fact_does_not_make_unknown_models_optimistic() -> None:
    assert resolve_local_capabilities("ollama", "llama3.1:8b", None).tool_calling
    unknown = resolve_local_capabilities("ollama", "custom-llama", None)
    assert unknown.tool_calling is False
    assert unknown.structured_output is False
    assert unknown.vision is False


def test_runtime_capability_list_is_model_specific_evidence() -> None:
    capabilities = resolve_local_capabilities(
        "ollama", "custom", {"capabilities": ["completion", "tools", "vision"]}
    )
    assert capabilities.tool_calling is True
    assert capabilities.vision is True
    assert capabilities.structured_output is False


def test_malformed_runtime_metadata_is_ignored_conservatively() -> None:
    capabilities = resolve_local_capabilities(
        "local",
        "unknown",
        {"tool_calling": "yes", "vision": 1, "context_length": -1},
    )
    assert capabilities == LocalModelCapabilities()


@pytest.mark.parametrize(
    "override",
    ({"tool_calling": "yes"}, {"context_length": -1}, {"context_length": True}),
)
def test_invalid_explicit_override_is_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="local model override"):
        resolve_local_capabilities("local", "model", None, override)


async def test_openai_catalog_metadata_populates_model_info() -> None:
    transport = FakeTransport(
        models={
            "data": [
                {
                    "id": "runtime-described",
                    "owned_by": "local-user",
                    "tool_calling": True,
                    "structured_output": True,
                    "context_length": 32768,
                }
            ]
        }
    )
    model = (await OpenAICompatibleChatProvider(transport=transport).list_models())[0]

    assert model.tool_calling is True
    assert model.structured_output is True
    assert model.context_length == 32768
    assert model.source == "local-user"


async def test_ollama_catalog_without_model_evidence_stays_conservative() -> None:
    transport = FakeTransport(
        models={"models": [{"name": "private-model", "details": {"family": "llama"}}]}
    )
    model = (await OllamaChatProvider(transport=transport).list_models())[0]

    assert model.text is True
    assert model.streaming is True
    assert model.tool_calling is False
    assert model.structured_output is False
    assert model.vision is False
