from __future__ import annotations

from types import SimpleNamespace

import pytest

from mark.tools.contracts import ToolResult
from mark.tools.legacy import adapters


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        (None, ToolResult(ok=True, code="legacy.ok")),
        ("done", ToolResult(ok=True, code="legacy.ok", message="done")),
        ({"value": 3}, ToolResult(ok=True, code="legacy.ok", data={"value": 3})),
    ],
)
def test_normalize_legacy_result(legacy: object, expected: ToolResult) -> None:
    assert adapters.normalize_legacy_result(legacy) == expected


def test_normalizer_preserves_native_tool_result() -> None:
    native = ToolResult(ok=False, code="denied", message="no")
    assert adapters.normalize_legacy_result(native) is native


def test_normalizer_does_not_report_false_as_success() -> None:
    result = adapters.normalize_legacy_result(False)

    assert result.ok is False
    assert result.code == "legacy.failed"


def test_all_required_handlers_are_exposed() -> None:
    assert set(adapters.LEGACY_HANDLERS) == {
        "read_file",
        "open_app",
        "web_search",
        "browser_control",
        "file_controller",
        "desktop_control",
        "computer_control",
        "computer_settings",
        "cmd_control",
        "screen_process",
        "reminder",
        "weather_report",
        "flight_finder",
        "youtube_video",
        "file_processor",
        "game_updater",
        "send_message",
        "code_helper",
        "dev_agent",
        "agent_task",
    }


def test_regular_adapter_copies_arguments_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, object] = {}

    def action(**kwargs: object) -> str:
        received.update(kwargs)
        return "opened"

    monkeypatch.setattr(
        adapters,
        "import_module",
        lambda name: SimpleNamespace(open_app=action),
    )
    original = {"app_name": "Calculator"}

    result = adapters.open_app_handler(original)

    assert result == ToolResult(ok=True, code="legacy.ok", message="opened")
    assert received == {"parameters": original, "player": None}
    assert received["parameters"] is not original


def test_weather_adapter_maps_to_weather_action(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def weather_action(**kwargs: object) -> dict[str, object]:
        called.update(kwargs)
        return {"forecast": "sunny"}

    monkeypatch.setattr(
        adapters,
        "import_module",
        lambda name: SimpleNamespace(weather_action=weather_action),
    )

    result = adapters.weather_report_handler({"city": "Haifa"})

    assert result.data == {"forecast": "sunny"}
    assert called["parameters"] == {"city": "Haifa"}


def test_optional_speak_signature_is_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def flight_finder(**kwargs: object) -> None:
        called.update(kwargs)

    monkeypatch.setattr(
        adapters,
        "import_module",
        lambda name: SimpleNamespace(flight_finder=flight_finder),
    )

    adapters.flight_finder_handler({"origin": "TLV"})

    assert called["speak"] is None


def test_agent_task_preserves_queue_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: dict[str, object] = {}

    class Priority:
        LOW = 1
        NORMAL = 2
        HIGH = 3

    class Queue:
        def submit(self, **kwargs: object) -> str:
            submitted.update(kwargs)
            return "task-42"

    fake_module = SimpleNamespace(TaskPriority=Priority, get_queue=lambda: Queue())
    monkeypatch.setattr(adapters, "import_module", lambda name: fake_module)

    result = adapters.agent_task_handler({"goal": "research", "priority": "high"})

    assert submitted == {"goal": "research", "priority": Priority.HIGH, "speak": None}
    assert result.message == "Task started (ID: task-42)."
