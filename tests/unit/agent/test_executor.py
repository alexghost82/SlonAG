"""Executor must not run model-written Python or fall back to generated_code."""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from agent.executor import AgentExecutor, ToolDeniedError, _call_tool
from mark.safety import (
    DecisionKind,
    RiskLevel,
    SafetyDecision,
    SafetyPolicyError,
    UnknownToolError,
    UntrustedSource,
)


SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"


class _DenyPolicy:
    def authorize(self, tool_name, args, *, source, intent=""):
        copied = dict(args) if isinstance(args, dict) else {}
        return SafetyDecision(
            kind=DecisionKind.DENY,
            tool_name=tool_name,
            risk=RiskLevel.READ,
            source=UntrustedSource.USER,
            intent=intent,
            args=copied,
            reason="denied by test policy",
        )

    def validate_args(self, tool_name, args):
        return dict(args)


def _guard_api_keys_open(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    api_keys = (repo_root / "config" / "api_keys.json").resolve()
    original_open = open

    def guarded_open(file, *args, **kwargs):
        try:
            path = Path(file).resolve()
        except TypeError:
            return original_open(file, *args, **kwargs)
        if path == api_keys or path.name == "api_keys.json":
            raise AssertionError("must not read config/api_keys.json")
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)


def _boom_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("must not spawn a process")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "call", boom)


def _boom_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def __getattr__(self, name: str):
            raise AssertionError(f"google.generativeai.{name} must not be used")

        def configure(self, *args, **kwargs):
            raise AssertionError("google.generativeai.configure must not be used")

        def GenerativeModel(self, *args, **kwargs):
            raise AssertionError("GenerativeModel must not be used")

    monkeypatch.setitem(sys.modules, "google.generativeai", Boom())
    monkeypatch.setitem(sys.modules, "google.genai", Boom())


def test_unknown_tool_raises_unknown_tool_error() -> None:
    with pytest.raises(UnknownToolError) as exc_info:
        _call_tool("not_a_real_tool", {"foo": "bar"}, None)
    assert exc_info.value.tool_name == "not_a_real_tool"
    assert SECRET not in str(exc_info.value)


def test_unknown_tool_does_not_run_generated_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.executor as executor_mod

    assert not hasattr(executor_mod, "_run_generated_code")
    _boom_subprocess(monkeypatch)
    _boom_gemini(monkeypatch)

    with pytest.raises(UnknownToolError):
        _call_tool("run_code", {"description": "print(1)"}, None)


def test_generated_code_is_denied_without_running_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _boom_subprocess(monkeypatch)
    with pytest.raises(ToolDeniedError) as exc_info:
        _call_tool("generated_code", {"description": "print('hello')"}, None)
    assert exc_info.value.tool_name == "generated_code"
    assert isinstance(exc_info.value, SafetyPolicyError)


def test_generated_code_does_not_call_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    _boom_gemini(monkeypatch)
    with pytest.raises(ToolDeniedError):
        _call_tool(
            "generated_code",
            {"description": "import os; os.system('id')"},
            None,
        )


def test_authorize_deny_prevents_the_action(monkeypatch: pytest.MonkeyPatch) -> None:
    import actions.web_search as web_search_mod

    ran: list[object] = []

    def fake_web_search(parameters=None, player=None):
        ran.append(parameters)
        return "ran"

    monkeypatch.setattr(web_search_mod, "web_search", fake_web_search)

    with pytest.raises(ToolDeniedError) as exc_info:
        _call_tool(
            "web_search",
            {"query": "weather"},
            None,
            policy=_DenyPolicy(),  # type: ignore[arg-type]
        )
    assert ran == []
    assert exc_info.value.tool_name == "web_search"


def test_untrusted_source_deny_does_not_call_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import actions.open_app as open_app_mod

    def fake_open_app(parameters=None, player=None):
        raise AssertionError("open_app must not run")

    monkeypatch.setattr(open_app_mod, "open_app", fake_open_app)

    with pytest.raises(ToolDeniedError):
        _call_tool(
            "open_app",
            {"app_name": "Safari"},
            None,
            source=UntrustedSource.WEB,
        )


def test_unknown_and_generated_code_do_not_read_api_keys(
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
) -> None:
    _guard_api_keys_open(monkeypatch, repo_root)
    _boom_gemini(monkeypatch)
    _boom_subprocess(monkeypatch)

    with pytest.raises(UnknownToolError):
        _call_tool("totally_unknown", {"x": 1}, None)

    with pytest.raises(ToolDeniedError):
        _call_tool("generated_code", {"description": "print(1)"}, None)


def test_confirm_without_confirmer_does_not_run_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import actions.open_app as open_app_mod

    ran: list[object] = []

    def fake_open_app(parameters=None, player=None):
        ran.append(parameters)
        return "opened"

    monkeypatch.setattr(open_app_mod, "open_app", fake_open_app)

    with pytest.raises(ToolDeniedError):
        _call_tool("open_app", {"app_name": "Safari"}, None)
    assert ran == []


def test_injected_confirmer_can_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    import actions.open_app as open_app_mod

    monkeypatch.setattr(
        open_app_mod,
        "open_app",
        lambda parameters=None, player=None: "opened",
    )

    result = _call_tool(
        "open_app",
        {"app_name": "Safari"},
        None,
        confirmer=lambda _decision: True,
    )
    assert result == "opened"


def test_injected_confirmer_can_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    import actions.open_app as open_app_mod

    ran: list[object] = []

    def _open(parameters=None, player=None):
        ran.append(1)
        return "opened"

    monkeypatch.setattr(open_app_mod, "open_app", _open)

    with pytest.raises(ToolDeniedError):
        _call_tool(
            "open_app",
            {"app_name": "Safari"},
            None,
            confirmer=lambda _decision: False,
        )
    assert ran == []


def test_allow_decision_runs_mocked_action(monkeypatch: pytest.MonkeyPatch) -> None:
    import actions.web_search as web_search_mod

    monkeypatch.setattr(
        web_search_mod,
        "web_search",
        lambda parameters=None, player=None: "ok-search",
    )
    result = _call_tool("web_search", {"query": "weather"}, None)
    assert result == "ok-search"


def test_agent_executor_keeps_execute_signature_and_injected_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import actions.web_search as web_search_mod

    monkeypatch.setattr(
        web_search_mod,
        "web_search",
        lambda parameters=None, player=None: "from-instance",
    )

    executor = AgentExecutor(
        policy=None,
        confirmer=lambda _decision: False,
        source=UntrustedSource.USER,
    )
    signature = inspect.signature(executor.execute)
    assert list(signature.parameters) == ["goal", "speak", "cancel_flag"]
    assert signature.parameters["speak"].default is None
    assert signature.parameters["cancel_flag"].default is None

    result = executor._call_tool("web_search", {"query": "x"}, None)
    assert result == "from-instance"


def test_call_tool_name_remains_public() -> None:
    import agent.executor as executor_mod

    assert callable(executor_mod._call_tool)
    assert callable(AgentExecutor.execute)
    assert callable(AgentExecutor._call_tool)


def test_executor_module_does_not_import_planner_at_load() -> None:
    import agent.executor as executor_mod

    source = inspect.getsource(executor_mod)
    assert "from agent.planner" not in source.split("def execute")[0]
    assert "_run_generated_code" not in source


@pytest.mark.asyncio
async def test_execute_agent_loop_convenience_function() -> None:
    from unittest.mock import MagicMock
    from agent.executor import execute_agent_loop
    from agent.runtime import AgentLoopResult
    from providers.contracts import ChatResponse, ModelInfo

    mock_provider = MagicMock()
    mock_provider.chat.return_value = ChatResponse(
        text="Loop answer", provider_id="test", model_id="test"
    )

    model = ModelInfo(
        provider_id="test", model_id="test", display_name="Test", text=True
    )
    res = await execute_agent_loop(
        "test goal", model=model, provider=mock_provider
    )
    assert isinstance(res, AgentLoopResult)
    assert res.ok is True
    assert res.final_answer == "Loop answer"


def test_execute_plan_convenience_function(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock
    import agent.executor as executor_mod

    mock_exec = MagicMock()
    mock_exec.execute.return_value = "Plan completed"
    monkeypatch.setattr(executor_mod, "AgentExecutor", lambda *args, **kwargs: mock_exec)

    result = executor_mod.execute_plan("legacy goal")
    assert result == "Plan completed"
    mock_exec.execute.assert_called_once_with("legacy goal", speak=None, cancel_flag=None)
