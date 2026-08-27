from i18n import t
"""Headless runtime bridge: assemble new-stack pieces with graceful degrade.

Does not import UI, open sockets, or download models. Secrets are read only
through an injected ``key_provider`` callable — this package never opens
``api_keys.json`` itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mark.bridge.control_plane import ControlPlaneUnavailable, DesktopControlPlane

KeyProvider = Callable[[str], str | None]


@dataclass
class RuntimeStack:
    """Optional subsystems for desktop main/UI glue."""

    provider_id: str
    network_mode: str
    router: Any | None = None
    memory: Any | None = None
    safety: Any | None = None
    tool_registry: Any | None = None
    tool_executor: Any | None = None
    session_manager: Any | None = None
    network: Any | None = None
    tts_ready: bool = False
    tts_message: str = ""
    stt_ready: bool = False
    stt_message: str = ""
    status_lines: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        return list(self.status_lines)

    def create_agent_loop(
        self, *, model: Any, budget: Any | None = None, cancel_event: Any = None
    ) -> Any:
        """Create the canonical AgentLoop from composition-owned dependencies."""
        if self.router is None or self.tool_executor is None:
            raise RuntimeError("runtime stack is missing provider or tool runtime")
        from agent.runtime import AgentLoop

        return AgentLoop(
            model=model,
            provider=self.router,
            tool_executor=self.tool_executor,
            budget=budget,
            cancel_event=cancel_event,
        )

    def create_session_binding(self) -> Any:
        if self.session_manager is None:
            raise RuntimeError("runtime stack is missing SessionManager")
        from sessions.binding import SessionAgentBinding

        return SessionAgentBinding(self.session_manager, self)


def _try(label: str, fn: Callable[[], Any], status: list[str]) -> Any | None:
    try:
        value = fn()
        status.append(f"{label}: ok")
        return value
    except Exception as exc:  # noqa: BLE001 — degrade path
        status.append(f"{label}: unavailable ({type(exc).__name__})")
        return None


def build_runtime_stack(
    *,
    repo_root: str | Path | None = None,
    provider_id: str = "gemini",
    network_mode: str = "hybrid",
    privacy_profile: str | None = None,
    key_provider: KeyProvider | None = None,
    memory_db_path: str | Path | None = None,
    session_db_path: str | Path | None = None,
    model_id: str = "",
    provider_settings: dict[str, Any] | None = None,
) -> RuntimeStack:
    """Best-effort assembly of router / memory / safety / network / speech."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    status: list[str] = []
    pid = (provider_id or "gemini").strip() or "gemini"
    mode = (network_mode or "hybrid").strip() or "hybrid"

    def _router() -> Any:
        from providers.router import Router

        # Resolve base_url override for this provider from provider_settings
        _base_url = ""
        _ps = provider_settings or {}
        if isinstance(_ps, dict):
            _psec = _ps.get(pid, {})
            if isinstance(_psec, dict):
                _base_url = _psec.get("base_url", "") or ""
        return Router(
            pid,
            network_mode=mode,
            privacy_profile=privacy_profile,
            key_provider=key_provider,
            configured_model_id=model_id if model_id else None,
        )

    def _memory() -> Any:
        from mark.memory import MemoryStore

        path = (
            Path(memory_db_path)
            if memory_db_path is not None
            else root / "memory" / "mark_memory.sqlite3"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return MemoryStore(path)

    def _safety() -> Any:
        from mark.safety import SafetyPolicy

        return SafetyPolicy()

    def _network() -> Any:
        from mark.network import NetworkPolicy

        return NetworkPolicy(mode=mode, privacy_profile=privacy_profile)

    router = _try("router", _router, status)
    memory = _try("memory", _memory, status)
    safety = _try("safety", _safety, status)

    def _tools() -> Any:
        from mark.tools.builtin import build_builtin_registry

        return build_builtin_registry()

    tool_registry = _try("tools", _tools, status)

    def _executor() -> Any:
        if tool_registry is None or safety is None:
            raise RuntimeError("tool registry or safety policy unavailable")
        from mark.tools import ToolExecutor

        return ToolExecutor(tool_registry, safety)

    tool_executor = _try("executor", _executor, status)
    network = _try("network", _network, status)

    def _sessions() -> Any:
        from sessions import SessionManager, SessionStore

        path = (
            Path(session_db_path)
            if session_db_path is not None
            else root / "memory" / "slon_sessions.sqlite3"
        )
        manager = SessionManager(SessionStore(path))
        recovered = manager.recover()
        status.append(f"sessions: recovered_runs={recovered}")
        return manager

    session_manager = _try("sessions", _sessions, status)

    tts_ready = False
    tts_message = "tts: not probed"
    try:
        from speech.tts.local_factory import try_build_local_tts

        built = try_build_local_tts(repo_root=root, validate=True)
        tts_ready = bool(built.ready)
        tts_message = built.message
        status.append(
            f"tts: {'ready' if tts_ready else 'unavailable'} — {built.message}"
        )
    except Exception as exc:  # noqa: BLE001
        tts_message = type(exc).__name__
        status.append(f"tts: unavailable ({type(exc).__name__})")

    stt_ready = False
    stt_message = "stt: not probed"
    try:
        from speech.stt.local_factory import try_build_local_stt

        built_stt = try_build_local_stt(repo_root=root, prefer_whisper=True)
        stt_ready = bool(built_stt.ready)
        stt_message = built_stt.message
        status.append(
            f"stt: {'ready' if stt_ready else 'unavailable'} — {built_stt.message}"
        )
    except Exception as exc:  # noqa: BLE001
        stt_message = type(exc).__name__
        status.append(f"stt: unavailable ({type(exc).__name__})")

    status.insert(0, f"provider_id={pid} network_mode={mode}")
    return RuntimeStack(
        provider_id=pid,
        network_mode=mode,
        router=router,
        memory=memory,
        safety=safety,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        session_manager=session_manager,
        network=network,
        tts_ready=tts_ready,
        tts_message=tts_message,
        stt_ready=stt_ready,
        stt_message=stt_message,
        status_lines=status,
    )


def authorize_tool(
    stack: RuntimeStack,
    tool_name: str,
    args: Mapping[str, object] | None = None,
    *,
    source: str = "desktop_ui",
) -> tuple[bool, str]:
    """Compatibility authorization facade; fail closed when policy is unavailable."""
    if stack.safety is None:
        return False, "safety unavailable"
    try:
        from mark.safety.types import DecisionKind

        decision = stack.safety.authorize(
            tool_name,
            dict(args or {}),
            source=source,
        )
        if decision.kind == DecisionKind.DENY:
            return False, decision.reason or "denied by SafetyPolicy"
        if decision.kind.name == "CONFIRM" or str(decision.kind).endswith("CONFIRM"):
            return False, decision.reason or "confirmation required"
        return True, decision.reason or "allowed"
    except Exception:  # noqa: BLE001
        return False, "safety authorization failed"


__all__ = [
    "ControlPlaneUnavailable",
    "DesktopControlPlane",
    "KeyProvider",
    "RuntimeStack",
    "authorize_tool",
    "build_runtime_stack",
]
