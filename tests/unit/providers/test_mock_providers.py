from __future__ import annotations

import pytest

from providers.contracts import ChatEvent, ChatMessage, ChatProvider, ChatRequest
from providers.errors import CapabilityError
from providers.registry import get

from tests.unit.providers.mocks import REPLY_PREFIX, MockChatProvider, mock_model

USER_TEXT = "ping from contract tests"


async def _request_for(
    provider: ChatProvider, *, role: str = "chat"
) -> ChatRequest:
    models = await provider.list_models()
    return ChatRequest(
        model=models[0],
        messages=(ChatMessage(role="user", content=USER_TEXT),),
        role=role,
    )


async def test_same_chat_request_works_against_all_registered_mocks(registered_mocks) -> None:
    expected_ids = (
        "gemini",
        "llama_cpp",
        "local",
        "ollama",
        "openai",
        "openrouter",
    )
    assert registered_mocks == expected_ids

    responses = []
    for provider_id in expected_ids:
        factory = get(provider_id)
        provider = factory()
        assert isinstance(provider, ChatProvider)
        request = await _request_for(provider)
        response = await provider.chat(request)
        responses.append(response)
        assert response.provider_id == provider_id
        assert response.model_id == f"{provider_id}-mock"
        assert response.text == f"{REPLY_PREFIX} {USER_TEXT}"

    assert len({item.text for item in responses}) == 1


async def test_stream_yields_chat_events(registered_mocks) -> None:
    shapes: list[list[tuple[str, str]]] = []
    for provider_id in registered_mocks:
        provider = get(provider_id)()
        events = [
            event async for event in provider.stream(await _request_for(provider))
        ]
        assert events
        assert all(isinstance(event, ChatEvent) for event in events)
        assert {event.type for event in events} <= {"delta", "done"}
        assert events[-1].type == "done"
        assert events[-1].text == ""
        deltas = [event.text for event in events if event.type == "delta"]
        assert "".join(deltas) == f"{REPLY_PREFIX} {USER_TEXT}"
        shapes.append([(event.type, event.text) for event in events])

    first = shapes[0]
    assert all(shape == first for shape in shapes)


async def test_capability_failure_happens_before_chat() -> None:
    model = mock_model("openai", text=False, vision=False)
    provider = MockChatProvider("openai", models=[model])
    request = ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content=USER_TEXT),),
        role="chat",
    )
    with pytest.raises(CapabilityError) as exc_info:
        await provider.chat(request)
    assert provider.chat_calls == 0
    assert exc_info.value.role == "chat"
    assert exc_info.value.model_id == model.model_id


async def test_capability_failure_happens_before_stream() -> None:
    model = mock_model("gemini", text=True, vision=False)
    provider = MockChatProvider("gemini", models=[model])
    request = ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content=USER_TEXT),),
        role="vision",
    )
    with pytest.raises(CapabilityError, match="vision"):
        async for _event in provider.stream(request):
            pytest.fail("stream must not yield after a capability failure")
    assert provider.stream_calls == 0


async def test_validate_and_list_models_are_local(registered_mocks) -> None:
    for provider_id in registered_mocks:
        provider = get(provider_id)()
        status = await provider.validate()
        assert status.ok is True
        assert status.provider_id == provider_id
        models = await provider.list_models()
        assert len(models) == 1
        assert models[0].provider_id == provider_id
        assert models[0].local is (provider_id == "local")
