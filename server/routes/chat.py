"""POST /v1/chat — mutating; approval-gate + agent loop execution."""

from __future__ import annotations

import asyncio
from typing import Mapping

from mark.tools.contracts import ToolResult
from providers.contracts import UserMessage

from server.routes._common import (
    DevicePrincipal,
    IdempotencyStore,
    RouteResponse,
    require_active_principal,
    schema_error_response,
)
from server.schemas import (
    CODE_APPROVAL_REQUIRED,
    ApiError,
    ChatRequest,
    SchemaValidationError,
)


class ChatHandler:
    """In-process chat entry that always routes mutating work through approval.

    This base implementation is a safe stub used for tests and for the
    ``DesktopControlApp`` mock dispatcher.  Production code should use
    ``ChatHandlerWithRuntime`` instead.
    """

    def __init__(self, *, idempotency: IdempotencyStore | None = None) -> None:
        self._idempotency = idempotency or IdempotencyStore()

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    def post(
        self,
        *,
        principal: DevicePrincipal | None,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = ChatRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        fingerprint = {
            "message": request.message,
            "conversation_id": request.conversation_id,
        }

        def _create() -> RouteResponse:
            # Approval gate stub: never execute tools or call cloud providers.
            return RouteResponse(
                status_code=202,
                body={
                    "event": "approval_required",
                    "conversation_id": request.conversation_id or "conv_pending",
                    "approval_id": f"appr_chat_{request.idempotency_key}",
                    "approval_required": True,
                    "status": CODE_APPROVAL_REQUIRED,
                    "error": ApiError.of(CODE_APPROVAL_REQUIRED).to_dict(),
                },
            )

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"chat:{request.idempotency_key}",
            factory=_create,
        )


class ChatHandlerWithRuntime:
    """Chat handler wired into the canonical Slon runtime stack.

    Accepts a ``runtime_stack`` (``mark.bridge.RuntimeStack``) or ``gateway``
    object and executes the full agent loop (model call → tool execution →
    observation → next turn).

    When the runtime stack is unavailable the handler degrades to the same
    approval_required stub as ``ChatHandler`` so the API surface is consistent.
    """

    def __init__(
        self,
        *,
        idempotency: IdempotencyStore | None = None,
        runtime_stack=None,  # mark.bridge.RuntimeStack or SlonGateway
    ) -> None:
        self._idempotency = idempotency or IdempotencyStore()
        self.runtime_stack = runtime_stack

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    def post(
        self,
        *,
        principal: DevicePrincipal | None,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = ChatRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        fingerprint = {
            "message": request.message,
            "conversation_id": request.conversation_id,
        }

        def _create() -> RouteResponse:
            stack = self.runtime_stack
            if stack is None:
                # Degrade gracefully
                return self._stub_response(request)

            agent_loop = getattr(stack, "agent_loop", None)
            if agent_loop is None:
                # Degrade gracefully
                return self._stub_response(request)

            try:
                result = self._run_agent_loop(agent_loop, request)
                return result
            except Exception as exc:
                return RouteResponse(
                    status_code=500,
                    body={
                        "event": "error",
                        "error": ApiError.of("runtime_error", str(exc)).to_dict(),
                    },
                )

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"chat:{request.idempotency_key}",
            factory=_create,
        )

    @staticmethod
    def _stub_response(request: ChatRequest) -> RouteResponse:
        """Return the approval_required stub."""
        return RouteResponse(
            status_code=202,
            body={
                "event": "approval_required",
                "conversation_id": request.conversation_id or "conv_pending",
                "approval_id": f"appr_chat_{request.idempotency_key}",
                "approval_required": True,
                "status": CODE_APPROVAL_REQUIRED,
                "error": ApiError.of(CODE_APPROVAL_REQUIRED).to_dict(),
            },
        )

    @staticmethod
    def _run_agent_loop(agent_loop, request: ChatRequest) -> RouteResponse:
        """Run one turn of the AgentLoop in a thread.

        The agent loop may make multiple provider calls (tool calls loop).
        We use asyncio.new_event_loop to keep the HTTP handler non-blocking.
        """
        messages = [UserMessage(content=request.message)]

        async def _run() -> dict:
            from agent.observation import ObservationKind
            from mark.tools.contracts import ToolResult as TR

            # Run the agent loop one turn (tool calls included)
            result = await agent_loop.run_once(messages)
            return {
                "ok": result.ok,
                "answer": result.final_answer,
                "steps": [
                    {
                        "turn": s.turn_index,
                        "observation": (
                            {
                                "ok": s.observation.ok,
                                "kind": s.observation.kind,
                                "content": (
                                    s.observation.content
                                    if s.observation.kind == ObservationKind.TEXT
                                    else None
                                ),
                                "error": s.observation.error,
                            }
                            if s.observation is not None
                            else None
                        ),
                        "assistant_text": (
                            s.assistant_text if s.assistant_text else None
                        ),
                    }
                    for s in result.steps
                ],
            }

        loop = asyncio.new_event_loop()
        try:
            run_result = loop.run_until_complete(_run())
        finally:
            loop.close()

        answer = run_result.get("answer") or ""
        steps = run_result.get("steps") or []

        # Build observation summary
        observations = []
        for s in steps:
            if s.get("observation"):
                obs = s["observation"]
                if obs.get("content"):
                    observations.append(obs["content"])
                elif obs.get("error"):
                    observations.append(f"Ошибка инструмента: {obs['error']}")

        return RouteResponse(
            status_code=200,
            body={
                "event": "agent_response",
                "conversation_id": request.conversation_id or "conv_0",
                "answer": answer,
                "tool_calls": [
                    {
                        "tool_name": s.get("tool_name"),
                        "ok": s.get("tool_ok"),
                    }
                    for s in steps
                    if s.get("tool_name")
                ],
                "observations": observations,
                "ok": run_result.get("ok", False),
            },
        )


def post_chat(
    *,
    principal: DevicePrincipal | None,
    body: Mapping[str, object],
    handler: ChatHandler | ChatHandlerWithRuntime | None = None,
) -> RouteResponse:
    """Module-level convenience wrapper around the chat handler."""
    if handler is None:
        handler = ChatHandler()
    return handler.post(principal=principal, body=body)


__all__ = ["ChatHandler", "ChatHandlerWithRuntime", "post_chat"]
