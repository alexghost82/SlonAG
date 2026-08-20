from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.live_session import receive_live_session
from runtime.audio import AudioPipeline, FreshAudioQueue, PLAYBACK_QUEUE_CHUNKS
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
    assert pipeline.audio_in_queue.maxsize == PLAYBACK_QUEUE_CHUNKS
    pipeline.unbind()
    assert pipeline.session is None
    assert pipeline.audio_in_queue is None


def test_audio_queue_drops_oldest_chunk_when_full() -> None:
    queue = FreshAudioQueue(maxsize=2)
    queue.put_nowait(b"oldest")
    queue.put_nowait(b"middle")
    queue.put_nowait(b"fresh")

    assert queue.dropped_chunks == 1
    assert queue.get_nowait() == b"middle"
    assert queue.get_nowait() == b"fresh"


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control_plane",
    [
        None,
        SimpleNamespace(
            request_approval=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("boom")
            )
        ),
    ],
)
async def test_live_tool_bridge_approval_failure_fails_closed(control_plane) -> None:
    calls: list[dict[str, object]] = []
    bridge = LiveToolBridge(
        ui=SimpleNamespace(control_plane=control_plane, current_file=None),
        speak=lambda _text: None,
        registry=_side_effect_registry(calls),
        approval_timeout_seconds=0.1,
    )

    result = await bridge.execute(
        "open_app", {"app_name": "Calculator"}, intent="approval failure"
    )

    assert result.ok is False
    assert calls == []


@pytest.mark.asyncio
async def test_live_tool_bridge_approval_timeout_fails_closed() -> None:
    calls: list[dict[str, object]] = []
    release = threading.Event()
    registry = _side_effect_registry(calls)
    control_plane = SimpleNamespace(
        request_approval=lambda *args, **kwargs: release.wait(1)
    )
    bridge = LiveToolBridge(
        ui=SimpleNamespace(control_plane=control_plane, current_file=None),
        speak=lambda _text: None,
        registry=registry,
        approval_timeout_seconds=0.02,
    )

    result = await bridge.execute(
        "open_app", {"app_name": "Calculator"},
        intent="test timeout", call_id="approval-timeout"
    )
    release.set()

    assert result.ok is False
    assert result.code == "confirmation_declined"
    assert calls == []


@pytest.mark.asyncio
async def test_live_tool_bridge_cancellation_during_approval_prevents_execution(
) -> None:
    calls: list[dict[str, object]] = []
    approval_started = threading.Event()
    release = threading.Event()

    def approve(*args, **kwargs) -> bool:
        approval_started.set()
        return release.wait(1)

    bridge = LiveToolBridge(
        ui=SimpleNamespace(
            control_plane=SimpleNamespace(request_approval=approve), current_file=None
        ),
        speak=lambda _text: None,
        registry=_side_effect_registry(calls),
        approval_timeout_seconds=1,
    )
    task = asyncio.create_task(
        bridge.execute(
            "open_app", {"app_name": "Calculator"},
            intent="cancel", call_id="cancelled-call"
        )
    )
    await asyncio.to_thread(approval_started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await asyncio.sleep(0.05)

    assert calls == []
    duplicate = await bridge.execute(
        "open_app", {"app_name": "Calculator"},
        intent="duplicate", call_id="cancelled-call"
    )
    assert duplicate.code == "cancelled"
    assert calls == []


@pytest.mark.asyncio
async def test_live_tool_bridge_deduplicates_side_effect_call_id() -> None:
    calls: list[dict[str, object]] = []
    bridge = LiveToolBridge(
        ui=SimpleNamespace(
            control_plane=SimpleNamespace(request_approval=lambda *a, **k: True),
            current_file=None,
        ),
        speak=lambda _text: None,
        registry=_side_effect_registry(calls),
    )

    arguments = {"app_name": "Calculator"}
    first = await bridge.execute(
        "open_app", arguments, intent="first", call_id="same-id"
    )
    second = await bridge.execute(
        "open_app", arguments, intent="second", call_id="same-id"
    )

    assert first.ok is True and second.ok is True
    assert len(calls) == 1


def _side_effect_registry(calls: list[dict[str, object]]) -> ToolRegistry:
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
    return registry


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


def test_live_latency_tracker_reports_distribution_without_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter((0.0, 0.1, 0.2, 1.0, 1.3, 1.4))
    monkeypatch.setattr("agent.latency.time.monotonic", lambda: next(timestamps))
    tracker = TurnLatencyTracker()
    for _ in range(2):
        tracker.start_turn()
        tracker.mark("provider_request_start")
        tracker.mark("provider_first_response")
        tracker.finish_turn()

    stats = tracker.statistics()

    assert stats["provider"] == {
        "count": 2,
        "min": 100.0,
        "median": 200.0,
        "p95": 300.0,
        "max": 300.0,
    }
    assert set(stats) == {"provider", "total"}


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
