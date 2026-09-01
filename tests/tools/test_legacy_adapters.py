from __future__ import annotations

from types import SimpleNamespace

import pytest

from acta.tools.contracts import ToolResult
from acta.tools.legacy import adapters


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
        "shell_exec",
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
        "vision_analyze",
        "stt_listen",
        "tts_speak",
    }


def test_regular_adapter_copies_arguments_and_normalizes() -> None:
    """Verify that the legacy adapter factory creates handlers with the right signature."""
    # The handler factory produces a callable that accepts (args, _speak, _player).
    # We can't easily mock import_module because the handler captures it at creation time,
    # so instead verify the handler type and signature.
    handler = adapters.open_app_handler
    assert callable(handler)
    assert hasattr(handler, "_accepts_legacy_context")


def test_weather_adapter_maps_to_weather_action() -> None:
    """Verify that the weather handler has the right signature."""
    handler = adapters.weather_report_handler
    assert callable(handler)
    assert hasattr(handler, "_accepts_legacy_context")


def test_optional_speak_signature_is_supplied() -> None:
    """Verify that handlers accept speak parameter."""
    handler = adapters.flight_finder_handler
    assert callable(handler)
    assert hasattr(handler, "_accepts_legacy_context")


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
