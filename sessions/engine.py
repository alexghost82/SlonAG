"""Session engine for isolation tests."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionContext:
    id: str  # public identifier (was session_id)
    session_id: str
    workspace: str
    title: str = ""
    agent_id: str = ""
    workspace_id: str = ""
    tools: list[str] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    isolation_key: str = ""

class SessionEngine:
    """Manages isolated sessions for workspace and session isolation tests."""
    def __init__(self) -> None:
        self.sessions: dict[str, SessionContext] = {}
        self._workspace_map: dict[str, str] = {}

    def create(
        self,
        title: str = "",
        agent_id: str = "",
        workspace_id: str = "",
        workspace: str = "",
        isolation_key: str = "",
        tools: list[str] | None = None,
    ) -> SessionContext:
        session_id = uuid.uuid4().hex
        ctx = SessionContext(
            id=session_id,
            session_id=session_id,
            workspace=workspace or workspace_id,
            title=title,
            agent_id=agent_id,
            workspace_id=workspace_id,
            tools=tools or [],
            isolation_key=isolation_key,
        )
        self.sessions[session_id] = ctx
        self._workspace_map[session_id] = workspace or workspace_id
        return ctx

    def get(
        self, session_id: str, workspace_id: str = ""
    ) -> SessionContext | None:
        ctx = self.sessions.get(session_id)
        if ctx is None:
            return None
        if workspace_id and ctx.workspace_id != workspace_id:
            return None
        return ctx

    def list_sessions(self) -> list[SessionContext]:
        return list(self.sessions.values())

    def workspace_of(self, session_id: str) -> str | None:
        return self._workspace_map.get(session_id)
