from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sessions import (
    ModelPolicy,
    RunStatus,
    SessionManager,
    SessionStatus,
    SessionStore,
    TranscriptKind,
)
from sessions.manager import SessionStateError
from sessions.transcript import messages_from_entries


def _manager(tmp_path: Path) -> SessionManager:
    return SessionManager(SessionStore(tmp_path / "sessions.sqlite3"))


def _create(manager: SessionManager, workspace: str = "desk"):
    return manager.create(
        title="Chat",
        agent_id="slon",
        model_policy=ModelPolicy("test", "model"),
        workspace_id=workspace,
    )


def test_crash_recover_resume_keeps_history(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    manager = SessionManager(SessionStore(path))
    session = _create(manager)
    run = manager.start_run(session.id, workspace_id="desk")
    manager.append_event(
        session.id,
        workspace_id="desk",
        turn_id=run.turn_id,
        kind=TranscriptKind.TEXT,
        role="user",
        text="hello",
    )
    manager.store.close()

    restarted = SessionManager(SessionStore(path))
    recovered = restarted.recover()
    assert recovered == 1
    loaded = restarted.get(session.id, workspace_id="desk")
    assert loaded.status is SessionStatus.ACTIVE
    assert loaded.transcript[0].text == "hello"
    assert loaded.active_runs == ()
    resumed = restarted.resume(session.id, workspace_id="desk")
    assert resumed.status is SessionStatus.ACTIVE
    restarted.append_event(
        session.id,
        workspace_id="desk",
        turn_id="turn-2",
        kind=TranscriptKind.TEXT,
        role="user",
        text="again",
    )
    assert [item.text for item in restarted.get(session.id, workspace_id="desk").transcript] == [
        "hello",
        "again",
    ]


def test_duplicate_tool_events_are_idempotent(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    first = manager.append_event(
        session.id,
        workspace_id="desk",
        turn_id="t1",
        kind=TranscriptKind.TOOL_CALL,
        tool_call_id="call-1",
        tool_name="shell_exec",
        data={"argv": ["true"]},
    )
    second = manager.append_event(
        session.id,
        workspace_id="desk",
        turn_id="t1",
        kind=TranscriptKind.TOOL_CALL,
        tool_call_id="call-1",
        tool_name="shell_exec",
        data={"argv": ["false"]},
    )
    assert first.id == second.id
    entries = manager.get(session.id, workspace_id="desk").transcript
    assert len(entries) == 1
    assert entries[0].data == {"argv": ["true"]}
    rebuilt = messages_from_entries(entries)
    assert rebuilt[0].tool_calls[0].id == "call-1"  # type: ignore[union-attr]


def test_disconnect_during_tool_cancels_and_run_can_finish(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager)
    run = manager.start_run(session.id, workspace_id="desk")
    cancelled = []
    manager.register_canceller(session.id, lambda: cancelled.append("x"))
    manager.close(session.id, workspace_id="desk")
    assert cancelled == ["x"]
    finished = manager.finish_run(run, RunStatus.CANCELLED)
    assert finished.status is RunStatus.CANCELLED
    resumed = manager.resume(session.id, workspace_id="desk")
    assert resumed.status is SessionStatus.ACTIVE


def test_expire_idle_closes_stale_but_keeps_fresh(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    stale = _create(manager)
    later = datetime.now(UTC) + timedelta(hours=2)
    closed = manager.expire_idle(
        workspace_id="desk",
        max_idle_seconds=60,
        now=later,
    )
    assert closed == 1
    assert manager.get(stale.id, workspace_id="desk").status is SessionStatus.CLOSED
    fresh = _create(manager)
    assert manager.expire_idle(workspace_id="desk", max_idle_seconds=3600) == 0
    assert manager.get(fresh.id, workspace_id="desk").status is SessionStatus.ACTIVE


def test_foreign_workspace_cannot_resume(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    session = _create(manager, "alpha")
    with pytest.raises(Exception):
        manager.resume(session.id, workspace_id="beta")
    manager.close(session.id, workspace_id="alpha")
    with pytest.raises(SessionStateError):
        manager.append_event(
            session.id,
            workspace_id="alpha",
            turn_id="t",
            kind=TranscriptKind.TEXT,
            text="nope",
        )
