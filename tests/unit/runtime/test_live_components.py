from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.live_session import receive_live_session
from runtime.audio import AudioPipeline


def test_audio_pipeline_owns_connection_queues_without_audio_dependency() -> None:
    pipeline = AudioPipeline(
        ui=SimpleNamespace(muted=False),
        set_speaking=lambda _value: None,
        latency_trace=SimpleNamespace(mark=lambda _event: None),
        speaking_lock=threading.Lock(),
        is_speaking=lambda: False,
    )
    session = SimpleNamespace()
    pipeline.bind(session)
    assert pipeline.session is session
    assert pipeline.audio_in_queue is not None
    assert pipeline.out_queue is not None
    pipeline.unbind()
    assert pipeline.session is None
    assert pipeline.audio_in_queue is None


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.send_tool_response = AsyncMock()

    async def receive(self):
        for response in self.responses:
            yield response


@pytest.mark.asyncio
async def test_receive_live_session_routes_audio_transcript_and_tool_result() -> None:
    function_call = SimpleNamespace(id="call-1", name="read_file", args={})
    content = SimpleNamespace(
        output_transcription=SimpleNamespace(text="answer"),
        input_transcription=SimpleNamespace(text="question long enough"),
        turn_complete=True,
    )
    responses = [
        SimpleNamespace(data=b"pcm", server_content=content, tool_call=None),
        SimpleNamespace(
            data=None,
            server_content=None,
            tool_call=SimpleNamespace(function_calls=[function_call]),
        ),
    ]
    session = FakeSession(responses)
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
    ui = SimpleNamespace(write_log=lambda message: logs.append(message))
    logs: list[str] = []
    speaking: list[bool] = []
    memory: list[tuple[str, str]] = []
    marks: list[str] = []
    trace = SimpleNamespace(mark=lambda event: marks.append(event))

    async def execute_tool(call):
        assert call.id == "call-1"
        return "native-result"

    await receive_live_session(
        session=session,
        audio_in_queue=audio_queue,
        ui=ui,
        set_speaking=speaking.append,
        execute_tool=execute_tool,
        update_memory=lambda user, assistant: memory.append((user, assistant)),
        latency_trace=trace,
    )

    assert await audio_queue.get() == b"pcm"
    assert logs == ["You: question long enough", "Slon: answer"]
    assert "tool_call_received" in marks
    session.send_tool_response.assert_awaited_once_with(
        function_responses=["native-result"]
    )
