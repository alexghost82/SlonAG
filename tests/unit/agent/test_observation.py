"""Unit tests for agent/observation.py."""

import pytest
from agent.observation import Observation, ObservationKind
from acta.tools.contracts import ArtifactRef, ToolResult


def test_observation_kind_enum_members():
    """Verify ObservationKind enum members and string values."""
    assert ObservationKind.SUCCESS == "success"
    assert ObservationKind.TOOL_ERROR == "tool_error"
    assert ObservationKind.SAFETY_DENIAL == "safety_denial"
    assert ObservationKind.TIMEOUT == "timeout"
    assert ObservationKind.SYSTEM == "system"


def test_observation_kind_lookup():
    """Verify ObservationKind case-insensitive lookup."""
    assert ObservationKind("success") == ObservationKind.SUCCESS
    assert ObservationKind("SUCCESS") == ObservationKind.SUCCESS
    assert ObservationKind("tool_error") == ObservationKind.TOOL_ERROR
    assert ObservationKind("TOOL_ERROR") == ObservationKind.TOOL_ERROR


def test_observation_dataclass_defaults():
    """Verify default values and post-init conversion."""
    obs = Observation(
        tool_call_id="call_1",
        tool_name="test_tool",
        kind="success",  # string converted in __post_init__
        ok=True,
    )

    assert obs.tool_call_id == "call_1"
    assert obs.tool_name == "test_tool"
    assert obs.kind == ObservationKind.SUCCESS
    assert obs.ok is True
    assert obs.content is None
    assert obs.artifacts == []
    assert obs.error is None


def test_observation_to_model_dict():
    """Verify formatting of observation for model context consumption."""
    obs = Observation(
        tool_call_id="call_123",
        tool_name="read_file",
        kind=ObservationKind.SUCCESS,
        ok=True,
        content={"data": "hello world"},
        artifacts=[{"kind": "file", "path": "/path/to/file.txt"}],
        error=None,
    )

    payload = obs.to_model_dict()
    assert payload == {
        "tool_call_id": "call_123",
        "tool_name": "read_file",
        "kind": "success",
        "ok": True,
        "content": {"data": "hello world"},
        "artifacts": [{"kind": "file", "path": "/path/to/file.txt"}],
        "error": None,
    }


def test_from_tool_result_success():
    """Verify factory mapping for successful ToolResult with artifacts."""
    art = ArtifactRef(kind="text", path="/tmp/log.txt", uri="file:///tmp/log.txt", mime_type="text/plain")
    res = ToolResult(
        ok=True,
        code="ok",
        message="Done",
        data={"result": 42},
        artifacts=(art,),
    )

    obs = Observation.from_tool_result("call_abc", "calculator", res)

    assert obs.tool_call_id == "call_abc"
    assert obs.tool_name == "calculator"
    assert obs.kind == ObservationKind.SUCCESS
    assert obs.ok is True
    assert obs.content == {"result": 42}
    assert obs.error is None
    assert obs.artifacts == [
        {
            "kind": "text",
            "path": "/tmp/log.txt",
            "uri": "file:///tmp/log.txt",
            "mime_type": "text/plain",
        }
    ]


def test_from_tool_result_message_content():
    """Verify content falls back to message when data is None."""
    res = ToolResult(
        ok=True,
        code="ok",
        message="Execution finished successfully",
        data=None,
    )

    obs = Observation.from_tool_result("call_msg", "run_script", res)
    assert obs.content == "Execution finished successfully"


def test_from_tool_result_errors():
    """Verify auto-detection of ObservationKind for various failure modes."""
    # Tool error
    res_err = ToolResult(ok=False, code="handler_error", message="Division by zero")
    obs_err = Observation.from_tool_result("c1", "t1", res_err)
    assert obs_err.kind == ObservationKind.TOOL_ERROR
    assert obs_err.ok is False
    assert obs_err.error == "Division by zero"

    # Timeout error
    res_timeout = ToolResult(ok=False, code="timeout", message="Execution timed out")
    obs_timeout = Observation.from_tool_result("c2", "t2", res_timeout)
    assert obs_timeout.kind == ObservationKind.TIMEOUT
    assert obs_timeout.ok is False
    assert obs_timeout.error == "Execution timed out"

    # Safety denial error
    res_safety = ToolResult(ok=False, code="confirmation_declined", message="Action denied")
    obs_safety = Observation.from_tool_result("c3", "t3", res_safety)
    assert obs_safety.kind == ObservationKind.SAFETY_DENIAL
    assert obs_safety.ok is False
    assert obs_safety.error == "Action denied"

    # System error
    res_sys = ToolResult(ok=False, code="system_error", message="Internal fault")
    obs_sys = Observation.from_tool_result("c4", "t4", res_sys)
    assert obs_sys.kind == ObservationKind.SYSTEM
    assert obs_sys.ok is False
    assert obs_sys.error == "Internal fault"


def test_from_tool_result_explicit_kind_override():
    """Verify passing an explicit kind override to from_tool_result."""
    res = ToolResult(ok=False, code="custom_code", message="Custom failure")
    obs = Observation.from_tool_result("c5", "t5", res, kind=ObservationKind.SYSTEM)
    assert obs.kind == ObservationKind.SYSTEM
    assert obs.ok is False
