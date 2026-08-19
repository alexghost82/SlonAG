"""Fixtures for the OpenRouter adapter tests. No live HTTP."""

from __future__ import annotations

import pytest

from providers.contracts import ChatMessage, ChatRequest, ModelInfo


@pytest.fixture
def text_model() -> ModelInfo:
    return ModelInfo(
        provider_id="openrouter",
        model_id="test/model",
        display_name="Test model",
        text=True,
        streaming=True,
    )


@pytest.fixture
def chat_request(text_model: ModelInfo) -> ChatRequest:
    return ChatRequest(
        model=text_model,
        messages=(ChatMessage(role="user", content="ping"),),
        role="chat",
    )
