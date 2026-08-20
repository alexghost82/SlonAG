from __future__ import annotations

from types import SimpleNamespace

from runtime.events import RuntimeEventBus, RuntimeEventKind, UIRuntimeEventSink


def test_runtime_events_are_ordered_monotonic_and_payload_free() -> None:
    events = []
    bus = RuntimeEventBus()
    unsubscribe = bus.subscribe(events.append)
    bus.emit(RuntimeEventKind.THINKING, turn_id="turn-1")
    bus.emit(
        RuntimeEventKind.TOOL_STARTED,
        turn_id="turn-1",
        tool_call_id="call-1",
        tool_name="weather_report",
    )
    bus.emit(RuntimeEventKind.TOOL_FINISHED, tool_call_id="call-1", code="ok")
    unsubscribe()
    bus.emit(RuntimeEventKind.SPEAKING)

    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.monotonic_at for event in events] == sorted(
        event.monotonic_at for event in events
    )
    assert not hasattr(events[1], "arguments")
    assert not hasattr(events[2], "result")


def test_failing_runtime_event_sink_is_isolated() -> None:
    received = []
    bus = RuntimeEventBus()
    bus.subscribe(lambda _event: (_ for _ in ()).throw(RuntimeError("sink")))
    bus.subscribe(received.append)
    bus.emit(RuntimeEventKind.CANCELLED)
    assert [event.kind for event in received] == [RuntimeEventKind.CANCELLED]


def test_ui_runtime_event_sink_adapts_state_and_control_plane() -> None:
    states = []
    published = []
    ui = SimpleNamespace(
        set_state=states.append,
        control_plane=SimpleNamespace(
            publish=lambda event, payload: published.append((event, payload))
        ),
    )
    bus = RuntimeEventBus()
    bus.subscribe(UIRuntimeEventSink(ui))
    bus.emit(RuntimeEventKind.SPEAKING, turn_id="turn-1")
    assert states == ["SPEAKING"]
    assert published[0][0] == "runtime_event"
    assert published[0][1]["kind"] == "speaking"
