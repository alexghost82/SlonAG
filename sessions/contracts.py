"""Canonical, persistence-neutral Session Engine contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class SessionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscriptKind(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ARTIFACT = "artifact"
    MEDIA_REFERENCE = "media_reference"


class TranscriptState(StrEnum):
    STREAMING = "streaming"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    ERROR = "error"


@dataclass(frozen=True)
class ModelPolicy:
    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        if not self.provider_id or not self.model_id:
            raise ValueError("model policy requires provider_id and model_id")


@dataclass(frozen=True)
class TranscriptEntry:
    id: str
    session_id: str
    turn_id: str
    sequence: int
    kind: TranscriptKind
    state: TranscriptState
    created_at: str
    role: str | None = None
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    data: object | None = None
    artifacts: tuple[Mapping[str, object], ...] = ()
    media_references: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.session_id or not self.turn_id:
            raise ValueError("transcript identity must be non-empty")
        if self.sequence < 1:
            raise ValueError("transcript sequence must be positive")
        if self.kind in {TranscriptKind.TOOL_CALL, TranscriptKind.TOOL_RESULT}:
            if not self.tool_call_id or not self.tool_name:
                raise ValueError("tool transcript entries require call id and name")


@dataclass(frozen=True)
class SessionRun:
    id: str
    session_id: str
    turn_id: str
    status: RunStatus
    started_at: str
    updated_at: str
    effective_provider_id: str | None = None
    effective_model_id: str | None = None


@dataclass(frozen=True)
class Session:
    id: str
    created_at: str
    updated_at: str
    title: str
    agent_id: str
    model_policy: ModelPolicy
    workspace_id: str
    status: SessionStatus
    transcript: tuple[TranscriptEntry, ...] = ()
    context_state: Mapping[str, object] = field(default_factory=dict)
    memory_scope: str = "session"
    permissions_profile: str = "default"
    active_runs: tuple[SessionRun, ...] = ()


__all__ = [
    "ModelPolicy",
    "RunStatus",
    "Session",
    "SessionRun",
    "SessionStatus",
    "TranscriptEntry",
    "TranscriptKind",
    "TranscriptState",
]
