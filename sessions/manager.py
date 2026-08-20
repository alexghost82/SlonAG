"""Lifecycle orchestration for durable logical sessions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Mapping
import threading
import builtins
from collections.abc import Callable
from uuid import uuid4

from sessions.contracts import (
    ModelPolicy,
    RunStatus,
    Session,
    SessionRun,
    SessionStatus,
    TranscriptEntry,
    TranscriptKind,
    TranscriptState,
)
from sessions.store import SessionInactiveError, SessionStore


class SessionNotFoundError(KeyError):
    pass


class SessionStateError(RuntimeError):
    pass


class SessionManager:
    """Canonical API over a workspace-scoped SessionStore."""

    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._runtime_lock = threading.Lock()
        self._cancellers: dict[str, set[Callable[[], None]]] = {}

    def create(
        self,
        *,
        title: str,
        agent_id: str,
        model_policy: ModelPolicy,
        workspace_id: str,
        context_state: Mapping[str, object] | None = None,
        memory_scope: str = "session",
        permissions_profile: str = "default",
    ) -> Session:
        if not all((title.strip(), agent_id.strip(), workspace_id.strip())):
            raise ValueError("title, agent_id, and workspace_id must be non-empty")
        now = _now()
        session = Session(
            id=str(uuid4()), created_at=now, updated_at=now, title=title.strip(),
            agent_id=agent_id.strip(), model_policy=model_policy,
            workspace_id=workspace_id.strip(), status=SessionStatus.ACTIVE,
            context_state=dict(context_state or {}), memory_scope=memory_scope,
            permissions_profile=permissions_profile,
        )
        self.store.insert_session(session)
        return session

    def get(self, session_id: str, *, workspace_id: str) -> Session:
        session = self.store.get_session(session_id, workspace_id=workspace_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def list(self, *, workspace_id: str) -> builtins.list[Session]:
        return self.store.list_sessions(workspace_id=workspace_id)

    def search(self, query: str, *, workspace_id: str) -> builtins.list[Session]:
        return self.store.list_sessions(workspace_id=workspace_id, query=query.strip())

    def resume(self, session_id: str, *, workspace_id: str) -> Session:
        session = self.get(session_id, workspace_id=workspace_id)
        if session.status is SessionStatus.ARCHIVED:
            raise SessionStateError("archived session cannot be resumed")
        if session.status is SessionStatus.CLOSED:
            if not self.store.resume_session(
                session_id, workspace_id=workspace_id, updated_at=_now()
            ):
                raise SessionStateError("session could not be resumed")
        return self.get(session_id, workspace_id=workspace_id)

    def close(self, session_id: str, *, workspace_id: str) -> Session:
        session = self.get(session_id, workspace_id=workspace_id)
        if session.status is SessionStatus.ARCHIVED:
            raise SessionStateError("archived session cannot be closed")
        if session.status is not SessionStatus.CLOSED:
            with self._runtime_lock:
                cancellers = tuple(self._cancellers.pop(session_id, ()))
            for cancel in cancellers:
                cancel()
            try:
                self.store.close_session(
                    session_id, workspace_id=workspace_id, updated_at=_now()
                )
            except SessionInactiveError as exc:
                raise SessionStateError("session is not active") from exc
        return self.get(session_id, workspace_id=workspace_id)

    def archive(self, session_id: str, *, workspace_id: str) -> Session:
        session = self.get(session_id, workspace_id=workspace_id)
        if session.status is not SessionStatus.ARCHIVED:
            try:
                changed = self.store.archive_session(
                    session_id, workspace_id=workspace_id, updated_at=_now()
                )
            except SessionInactiveError as exc:
                raise SessionStateError("session with active runs cannot be archived") from exc
            if not changed:
                raise SessionStateError("session could not be archived")
        return self.get(session_id, workspace_id=workspace_id)

    def delete(self, session_id: str, *, workspace_id: str) -> bool:
        session = self.get(session_id, workspace_id=workspace_id)
        if session.status is not SessionStatus.ARCHIVED:
            raise SessionStateError("only archived sessions can be deleted")
        return self.store.delete_session(session_id, workspace_id=workspace_id)

    def append_event(
        self,
        session_id: str,
        *,
        workspace_id: str,
        turn_id: str,
        kind: TranscriptKind,
        state: TranscriptState = TranscriptState.COMPLETED,
        role: str | None = None,
        text: str | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        data: object | None = None,
        artifacts: tuple[Mapping[str, object], ...] = (),
        media_references: tuple[Mapping[str, object], ...] = (),
    ) -> TranscriptEntry:
        session = self.get(session_id, workspace_id=workspace_id)
        if session.status is not SessionStatus.ACTIVE:
            raise SessionStateError("session is not active")
        entry = TranscriptEntry(
            id=str(uuid4()), session_id=session_id, turn_id=turn_id, sequence=1,
            kind=kind, state=state, created_at=_now(), role=role, text=text,
            tool_call_id=tool_call_id, tool_name=tool_name, data=data,
            artifacts=artifacts, media_references=media_references,
        )
        try:
            return self.store.append_entry(entry, workspace_id=workspace_id)
        except SessionInactiveError as exc:
            raise SessionStateError("session is not active") from exc

    def start_run(
        self,
        session_id: str,
        *,
        workspace_id: str,
        effective_provider_id: str | None = None,
        effective_model_id: str | None = None,
        turn_id: str | None = None,
    ) -> SessionRun:
        session = self.get(session_id, workspace_id=workspace_id)
        if session.status is not SessionStatus.ACTIVE:
            raise SessionStateError("session is not active")
        now = _now()
        run = SessionRun(
            id=str(uuid4()), session_id=session_id, turn_id=turn_id or str(uuid4()),
            status=RunStatus.ACTIVE, started_at=now, updated_at=now,
            effective_provider_id=effective_provider_id,
            effective_model_id=effective_model_id,
        )
        try:
            self.store.insert_run(run, workspace_id=workspace_id)
        except SessionInactiveError as exc:
            raise SessionStateError("session is not active") from exc
        return run

    def finish_run(self, run: SessionRun, status: RunStatus) -> SessionRun:
        if status is RunStatus.ACTIVE:
            raise ValueError("finish status must be terminal")
        now = _now()
        changed = self.store.update_run_status(run.id, status, now)
        return replace(run, status=status, updated_at=now) if changed else run

    def record_effective_model(
        self, run: SessionRun, *, provider_id: str, model_id: str
    ) -> SessionRun:
        now = _now()
        self.store.update_run_effective_model(run.id, provider_id, model_id, now)
        return replace(
            run, effective_provider_id=provider_id,
            effective_model_id=model_id, updated_at=now,
        )

    def recover(self) -> int:
        """Mark uncertain work interrupted; never replay provider/tools."""
        return self.store.recover_interrupted(_now())

    def register_canceller(
        self, session_id: str, cancel: Callable[[], None]
    ) -> Callable[[], None]:
        with self._runtime_lock:
            self._cancellers.setdefault(session_id, set()).add(cancel)

        def unregister() -> None:
            with self._runtime_lock:
                callbacks = self._cancellers.get(session_id)
                if callbacks is not None:
                    callbacks.discard(cancel)
                    if not callbacks:
                        self._cancellers.pop(session_id, None)

        return unregister


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "SessionManager", "SessionNotFoundError", "SessionStateError",
]
