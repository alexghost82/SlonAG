"""Session-owned adapter around the provider-neutral AgentLoop."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from providers.contracts import ConversationMessage, ModelInfo
from sessions.contracts import RunStatus, SessionStatus, TranscriptState
from sessions.manager import SessionManager
from sessions.transcript import entry_fields, messages_from_entries


class SessionAgentBinding:
    def __init__(self, manager: SessionManager, runtime_stack: Any) -> None:
        self.manager = manager
        self.runtime_stack = runtime_stack

    async def run(
        self,
        session_id: str,
        user_goal: str,
        *,
        workspace_id: str,
        model: ModelInfo,
        budget: Any | None = None,
    ) -> Any:
        session = self.manager.get(session_id, workspace_id=workspace_id)
        if (model.provider_id, model.model_id) != (
            session.model_policy.provider_id, session.model_policy.model_id
        ):
            raise ValueError("selected model does not match session model policy")
        run = self.manager.start_run(
            session_id, workspace_id=workspace_id,
            effective_provider_id=model.provider_id, effective_model_id=model.model_id,
        )
        history = messages_from_entries(session.transcript)

        def persist(message: ConversationMessage) -> None:
            for fields in entry_fields(message):
                self.manager.append_event(
                    session_id, workspace_id=workspace_id, turn_id=run.turn_id,
                    kind=fields["kind"], state=TranscriptState.COMPLETED,
                    role=fields.get("role"), text=fields.get("text"),
                    tool_call_id=fields.get("tool_call_id"),
                    tool_name=fields.get("tool_name"), data=fields.get("data"),
                    artifacts=fields.get("artifacts", ()),
                )

        cancel_event = threading.Event()
        task = asyncio.current_task()
        event_loop = asyncio.get_running_loop()

        def cancel() -> None:
            cancel_event.set()
            if task is not None:
                event_loop.call_soon_threadsafe(task.cancel)

        unregister = self.manager.register_canceller(session_id, cancel)
        if self.manager.get(session_id, workspace_id=workspace_id).status is not SessionStatus.ACTIVE:
            unregister()
            cancel_event.set()
            raise RuntimeError("session closed before provider dispatch")
        loop = self.runtime_stack.create_agent_loop(
            model=model, budget=budget, cancel_event=cancel_event
        )
        try:
            result = await loop.run(user_goal, history=history, on_message=persist)
        except asyncio.CancelledError:
            self.manager.finish_run(run, RunStatus.CANCELLED)
            raise
        except BaseException:
            self.manager.finish_run(run, RunStatus.INTERRUPTED)
            raise
        finally:
            unregister()
        if result.effective_provider_id and result.effective_model_id:
            run = self.manager.record_effective_model(
                run,
                provider_id=result.effective_provider_id,
                model_id=result.effective_model_id,
            )
        self.manager.finish_run(
            run, RunStatus.COMPLETED if result.ok else RunStatus.FAILED
        )
        return result


__all__ = ["SessionAgentBinding"]
