from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.live_session import receive_live_session
from runtime.audio import AudioPipeline
from runtime.tool_bridge import LiveToolBridge
from runtime.lifecycle import run_live_lifecycle
from mark.safety import RiskLevel
from mark.tools import ToolRegistry, ToolSpec
from agent.latency import TurnLatencyTracker


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


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [False, True])
async def test_live_tool_bridge_requires_real_confirmation_for_side_effects(
    approved: bool,
) -> None:
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="open_app",
            description="open",
            input_schema={"type": "object"},
            output_schema=None,
            handler=lambda arguments: calls.append(dict(arguments)) or "opened",
            risk=RiskLevel.CONFIRM,
        )
    )
    control_plane = SimpleNamespace(
        request_approval=lambda *args, **kwargs: approved
    )
    bridge = LiveToolBridge(
        ui=SimpleNamespace(control_plane=control_plane, current_file=None),
        speak=lambda _text: None,
        registry=registry,
    )

    result = await bridge.execute(
        "open_app", {"app_name": "Calculator"}, intent="Open calculator"
    )

    assert result.ok is approved
    assert len(calls) == int(approved)


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
    trace = TurnLatencyTracker()

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
    assert logs[:2] == ["You: question long enough", "Slon: answer"]
    assert logs[2].startswith("SYS: latency ")
    assert len(trace.history()) == 1
    session.send_tool_response.assert_awaited_once_with(
        function_responses=["native-result"]
    )


def test_live_latency_tracker_resets_marks_between_turns() -> None:
    tracker = TurnLatencyTracker()
    tracker.start_turn()
    tracker.mark("provider_request_start")
    tracker.mark("provider_first_response")
    first = tracker.finish_turn()
    tracker.start_turn()
    assert tracker.breakdown() == {}
    tracker.mark("tool_execution_start")
    tracker.mark("tool_execution_finish")
    second = tracker.finish_turn()

    assert "provider" in first and "tool" not in first
    assert "tool" in second and "provider" not in second
    assert len(tracker.history()) == 2


@pytest.mark.asyncio
async def test_live_lifecycle_cancellation_cleans_up_connection() -> None:
    connected = asyncio.Event()
    disconnected: list[bool] = []

    class Connection:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    client = SimpleNamespace(
        aio=SimpleNamespace(
            live=SimpleNamespace(connect=lambda **_kwargs: Connection())
        )
    )
    ui = SimpleNamespace(set_state=lambda _state: None, write_log=lambda _text: None)

    def on_connected(_session, _loop) -> None:
        connected.set()

    task = asyncio.create_task(
        run_live_lifecycle(
            client=client,
            model_id="model",
            build_config=lambda: {},
            on_connected=on_connected,
            on_disconnected=lambda: disconnected.append(True),
            tasks=lambda: (asyncio.Event().wait(),),
            ui=ui,
            reconnect_delay=0,
        )
    )
    await asyncio.wait_for(connected.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert disconnected == [True]
