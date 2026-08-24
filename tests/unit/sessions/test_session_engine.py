from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from providers.contracts import (
    AssistantToolCallMessage,
    ChatResponse,
    ModelInfo,
    ToolCall,
    ToolResultMessage,
)
from sessions import (
    ModelPolicy,
    RunStatus,
    SessionCorruptionError,
    SessionManager,
    SessionStatus,
    SessionStore,
    TranscriptKind,
    TranscriptState,
)
from sessions.binding import SessionAgentBinding
from sessions.manager import SessionNotFoundError, SessionStateError
from sessions.store import SessionInactiveError
from sessions.transcript import entry_fields, messages_from_entries
from mark.safety import DecisionKind, RiskLevel, SafetyDecision, UntrustedSource
from mark.tools import ToolExecutor, ToolRegistry, ToolSpec


def _manager(tmp_path: Path) -> SessionManager:
    return SessionManager(SessionStore(tmp_path / "sessions.sqlite3"))


def _create(manager: SessionManager, workspace: str = "a"):
    return manager.create(
        title="Conversation", agent_id="slon",
        model_policy=ModelPolicy("test", "model"), workspace_id=workspace,
    )


def test_create_persist_reopen_and_workspace_isolation(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.sqlite3")
    manager = SessionManager(store)
    first = _create(manager, "workspace-a")
    second = _create(manager, "workspace-b")
    manager.append_event(
        first.id, workspace_id="workspace-a", turn_id="turn-a",
        kind=TranscriptKind.TEXT, role="user", text="hello",
    )
    store.close()

    reopened = SessionManager(SessionStore(tmp_path / "sessions.sqlite3"))
    loaded = reopened.get(first.id, workspace_id="workspace-a")
    assert loaded.transcript[0].text == "hello"
    assert [item.id for item in reopened.list(workspace_id="workspace-a")] == [first.id]
    with pytest.raises(SessionNotFoundError):
        reopened.get(second.id, workspace_id="workspace-a")


def test_state_transitions_close_idempotent_and_reject_work(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    run = manager.start_run(session.id, workspace_id="a")

    closed = manager.close(session.id, workspace_id="a")
    assert closed.status is SessionStatus.CLOSED
    assert closed.active_runs == ()
    assert manager.close(session.id, workspace_id="a").status is SessionStatus.CLOSED
    with pytest.raises(SessionStateError):
        manager.append_event(
            session.id, workspace_id="a", turn_id=run.turn_id,
            kind=TranscriptKind.TEXT, text="late",
        )
    resumed = manager.resume(session.id, workspace_id="a")
    assert resumed.status is SessionStatus.ACTIVE
    archived = manager.archive(session.id, workspace_id="a")
    assert archived.status is SessionStatus.ARCHIVED
    with pytest.raises(SessionStateError):
        manager.resume(session.id, workspace_id="a")
    assert manager.delete(session.id, workspace_id="a") is True


def test_concurrent_transcript_append_is_transactionally_ordered(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    barrier = threading.Barrier(8)

    def append(index: int) -> None:
        barrier.wait()
        manager.append_event(
            session.id, workspace_id="a", turn_id=f"turn-{index}",
            kind=TranscriptKind.TEXT, role="user", text=str(index),
        )

    threads = [threading.Thread(target=append, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    loaded = manager.get(session.id, workspace_id="a")
    assert [entry.sequence for entry in loaded.transcript] == list(range(1, 9))
    assert {entry.text for entry in loaded.transcript} == {str(i) for i in range(8)}


def test_typed_tool_transcript_round_trip_preserves_correlation(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    messages = (
        AssistantToolCallMessage((
            ToolCall("call-a", "read_file", {"path": "a"}),
            ToolCall("call-b", "read_file", {"path": "b"}),
        )),
        ToolResultMessage("call-a", "read_file", result="A"),
        ToolResultMessage("call-b", "read_file", error="missing"),
    )
    for message in messages:
        for fields in entry_fields(message):
            manager.append_event(
                session.id, workspace_id="a", turn_id="turn-tools", **fields
            )
    hydrated = messages_from_entries(manager.get(session.id, workspace_id="a").transcript)
    assert hydrated == messages


def test_orphan_tool_call_hydrates_as_error_without_replay(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    for fields in entry_fields(AssistantToolCallMessage((
        ToolCall("uncertain", "side_effect", {}),
    ))):
        manager.append_event(
            session.id, workspace_id="a", turn_id="crashed", **fields
        )
    hydrated = messages_from_entries(manager.get(session.id, workspace_id="a").transcript)
    assert isinstance(hydrated[-1], ToolResultMessage)
    assert hydrated[-1].tool_call_id == "uncertain"
    assert "not replayed" in (hydrated[-1].error or "")


def test_interrupted_assistant_partial_is_not_hydrated_as_completed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    manager.append_event(
        session.id, workspace_id="a", turn_id="interrupted",
        kind=TranscriptKind.TEXT, state=TranscriptState.INTERRUPTED,
        role="assistant", text="partial answer",
    )
    assert messages_from_entries(
        manager.get(session.id, workspace_id="a").transcript
    ) == ()


def test_orphan_or_duplicate_tool_results_are_rejected(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    manager.append_event(
        session.id, workspace_id="a", turn_id="bad",
        kind=TranscriptKind.TOOL_RESULT, role="tool",
        tool_call_id="orphan", tool_name="read", data={"result": "x"},
    )
    with pytest.raises(ValueError, match="orphan"):
        messages_from_entries(manager.get(session.id, workspace_id="a").transcript)


def test_tool_result_name_must_match_correlated_call(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    manager.append_event(
        session.id, workspace_id="a", turn_id="bad-name",
        kind=TranscriptKind.TOOL_CALL, role="assistant",
        tool_call_id="call", tool_name="read", data={},
    )
    manager.append_event(
        session.id, workspace_id="a", turn_id="bad-name",
        kind=TranscriptKind.TOOL_RESULT, role="tool",
        tool_call_id="call", tool_name="write", data={"result": "x"},
    )
    with pytest.raises(ValueError, match="name does not match"):
        messages_from_entries(manager.get(session.id, workspace_id="a").transcript)


def test_live_tool_transcript_append_is_idempotent_by_call_id(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    for _ in range(2):
        manager.append_event(
            session.id, workspace_id="a", turn_id="turn",
            kind=TranscriptKind.TOOL_CALL, role="assistant",
            tool_call_id="same", tool_name="read", data={},
        )
        manager.append_event(
            session.id, workspace_id="a", turn_id="turn",
            kind=TranscriptKind.TOOL_RESULT, role="tool",
            tool_call_id="same", tool_name="read", data={"result": "ok"},
        )
    transcript = manager.get(session.id, workspace_id="a").transcript
    assert len(transcript) == 2


def test_store_rejects_stale_append_and_run_after_close(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    manager.close(session.id, workspace_id="a")
    with pytest.raises(SessionStateError):
        manager.append_event(
            session.id, workspace_id="a", turn_id="late",
            kind=TranscriptKind.TEXT, role="user", text="late",
        )
    with pytest.raises(SessionStateError):
        manager.start_run(session.id, workspace_id="a")


def test_run_terminal_state_is_compare_and_set(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    run = manager.start_run(session.id, workspace_id="a")

    assert manager.store.update_run_status(run.id, RunStatus.COMPLETED, "first")
    assert not manager.store.update_run_status(run.id, RunStatus.INTERRUPTED, "late")
    assert manager.store.update_run_status(run.id, RunStatus.COMPLETED, "repeat")
    assert manager.get(session.id, workspace_id="a").active_runs == ()


def test_store_does_not_close_archived_session(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    manager.archive(session.id, workspace_id="a")

    with pytest.raises(SessionInactiveError):
        manager.store.close_session(
            session.id, workspace_id="a", updated_at="late"
        )
    assert manager.get(session.id, workspace_id="a").status is SessionStatus.ARCHIVED


def test_restart_recovery_interrupts_active_runs_and_streams(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    manager = SessionManager(SessionStore(path))
    session = _create(manager)
    run = manager.start_run(session.id, workspace_id="a")
    manager.append_event(
        session.id, workspace_id="a", turn_id=run.turn_id,
        kind=TranscriptKind.TEXT, state=TranscriptState.STREAMING,
        role="assistant", text="partial",
    )
    manager.store.close()

    recovered = SessionManager(SessionStore(path))
    assert recovered.recover() == 1
    loaded = recovered.get(session.id, workspace_id="a")
    assert loaded.active_runs == ()
    assert loaded.transcript[0].state is TranscriptState.INTERRUPTED


def test_future_schema_is_rejected_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE session_schema(version INTEGER NOT NULL)")
    connection.execute("INSERT INTO session_schema VALUES (999)")
    connection.commit()
    connection.close()
    with pytest.raises(Exception, match="unsupported session schema"):
        SessionStore(path)
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT version FROM session_schema").fetchone()[0] == 999
    connection.close()


def test_corrupt_database_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not sqlite")
    with pytest.raises(SessionCorruptionError) as caught:
        SessionStore(path)
    assert path.read_bytes() == b"not sqlite"
    assert caught.value.backup_path.read_bytes() == b"not sqlite"


def test_online_backup_reopens_with_integrity(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    target = manager.store.backup(tmp_path / "backup.sqlite3")
    backup = SessionManager(SessionStore(target))
    assert backup.get(session.id, workspace_id="a").id == session.id


def test_failed_backup_validation_preserves_target_and_removes_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    target = tmp_path / "backup.sqlite3"
    target.write_bytes(b"last-known-good")
    monkeypatch.setattr("sessions.store._backup_is_valid", lambda _connection: False)

    with pytest.raises(Exception, match="integrity check failed"):
        manager.store.backup(target)

    assert target.read_bytes() == b"last-known-good"
    assert not target.with_suffix(".sqlite3.tmp").exists()


@pytest.mark.asyncio
async def test_two_session_agent_bindings_keep_history_and_models_isolated(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    first = _create(manager, "a")
    second = _create(manager, "b")
    requests = []

    class Provider:
        async def chat(self, request):
            requests.append(request)
            return ChatResponse("done", "test", "model")

    from agent.runtime import AgentLoop

    provider = Provider()
    stack = SimpleNamespace(
        create_agent_loop=lambda model, budget=None, cancel_event=None: AgentLoop(
            model=model, provider=provider, budget=budget,
            cancel_event=cancel_event,
        )
    )
    binding = SessionAgentBinding(manager, stack)
    model = ModelInfo("test", "model", "Model", text=True)
    await asyncio.gather(
        binding.run(first.id, "first", workspace_id="a", model=model),
        binding.run(second.id, "second", workspace_id="b", model=model),
    )
    assert [entry.text for entry in manager.get(first.id, workspace_id="a").transcript] == ["first", "done"]
    assert [entry.text for entry in manager.get(second.id, workspace_id="b").transcript] == ["second", "done"]
    assert {request.messages[0].content for request in requests} == {"first", "second"}


def test_model_policy_rejects_mismatched_binding(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    binding = SessionAgentBinding(manager, SimpleNamespace())
    wrong = ModelInfo("other", "model", "Other", text=True)
    with pytest.raises(ValueError, match="model policy"):
        asyncio.run(binding.run(session.id, "x", workspace_id="a", model=wrong))


@pytest.mark.asyncio
async def test_close_during_approval_is_scoped_and_fails_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session_a = _create(manager, "a")
    session_b = _create(manager, "b")
    approval_started = threading.Event()
    release = threading.Event()
    handler_calls = []

    class Policy:
        def validate_args(self, _name, arguments):
            return dict(arguments)

        def authorize(self, name, arguments, **_kwargs):
            return SafetyDecision(
                DecisionKind.CONFIRM, name, RiskLevel.CONFIRM,
                UntrustedSource.USER, "effect", dict(arguments),
            )

    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="side_effect", description="effect", input_schema={"type": "object"},
        output_schema=None, handler=lambda args: handler_calls.append(args),
        risk=RiskLevel.CONFIRM,
    ))

    def confirm(_decision) -> bool:
        approval_started.set()
        return release.wait(1)

    executor = ToolExecutor(registry, Policy(), confirmer=confirm)  # type: ignore[arg-type]
    responses = [
        ChatResponse("", "test", "model", (
            ToolCall("same-provider-id", "side_effect", {}),
        )),
        ChatResponse("done", "test", "model"),
    ]

    class Provider:
        async def chat(self, _request):
            return responses.pop(0)

    from agent.runtime import AgentLoop

    stack = SimpleNamespace(create_agent_loop=lambda model, budget=None, cancel_event=None: AgentLoop(
        model=model, provider=Provider(), tool_executor=executor,
        budget=budget, cancel_event=cancel_event,
    ))
    binding = SessionAgentBinding(manager, stack)
    model = ModelInfo("test", "model", "Model", text=True, tool_calling=True)
    task = asyncio.create_task(
        binding.run(session_a.id, "effect", workspace_id="a", model=model)
    )
    await asyncio.to_thread(approval_started.wait, 1)
    manager.close(session_a.id, workspace_id="a")
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await asyncio.sleep(0.05)

    assert handler_calls == []
    assert manager.get(session_b.id, workspace_id="b").status is SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_same_tool_call_id_is_isolated_between_sessions(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    first = _create(manager, "a")
    second = _create(manager, "b")
    handler_calls = []

    class AllowPolicy:
        def validate_args(self, _name, arguments):
            return dict(arguments)

        def authorize(self, name, arguments, **_kwargs):
            return SafetyDecision(
                DecisionKind.ALLOW, name, RiskLevel.READ,
                UntrustedSource.USER, "read", dict(arguments),
            )

    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="read", description="read", input_schema={"type": "object"},
        output_schema=None,
        handler=lambda arguments: handler_calls.append(dict(arguments)) or "ok",
        risk=RiskLevel.READ, read_only=True, idempotent=True,
        side_effects=False, parallel_safe=True,
    ))
    executor = ToolExecutor(registry, AllowPolicy())  # type: ignore[arg-type]

    class Provider:
        async def chat(self, request):
            if any(isinstance(item, ToolResultMessage) for item in request.messages):
                return ChatResponse("done", "test", "model")
            return ChatResponse("", "test", "model", (
                ToolCall("same-id", "read", {"session": request.messages[-1].content}),
            ))

    from agent.runtime import AgentLoop

    stack = SimpleNamespace(create_agent_loop=lambda model, budget=None, cancel_event=None: AgentLoop(
        model=model, provider=Provider(), tool_executor=executor,
        budget=budget, cancel_event=cancel_event,
    ))
    binding = SessionAgentBinding(manager, stack)
    model = ModelInfo("test", "model", "Model", text=True, tool_calling=True)
    await asyncio.gather(
        binding.run(first.id, "A", workspace_id="a", model=model),
        binding.run(second.id, "B", workspace_id="b", model=model),
    )
    assert {item["session"] for item in handler_calls} == {"A", "B"}
    assert len(handler_calls) == 2


def test_sessions_package_is_the_only_contract_definition() -> None:
    import sessions
    import sessions.contracts as contracts

    root = Path(__file__).resolve().parents[3]
    assert not (root / "session_contracts.py").exists()
    assert sessions.Session is contracts.Session
    assert sessions.SessionRun is contracts.SessionRun
    assert sessions.TranscriptEntry is contracts.TranscriptEntry
