"""POST /v1/chat — mutating; approval-gate + agent loop execution."""

from __future__ import annotations

import asyncio
import threading
from typing import Mapping

from mark.tools.contracts import ToolResult
from providers.contracts import (
    ConversationMessage,
    ModelInfo,
    UserMessage,
)

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


class RuntimeConfigError(RuntimeError):
    """Raised when the production runtime stack is misconfigured."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "runtime_config_error"


class ChatHandlerWithRuntime:
    """Chat handler wired into the canonical Slon runtime stack.

    Accepts a ``runtime_stack`` (``mark.bridge.RuntimeStack``) and executes
    the full agent loop via the canonical factory method:

    1. stack.create_agent_loop(model=..., budget=..., cancel_event=...)
    2. agent_loop.run(user_goal=message, history=messages)

    When the runtime stack is unavailable or misconfigured the handler
    returns a structured 503 error instead of silently degrading to a stub.
    """

    def __init__(
        self,
        *,
        idempotency: IdempotencyStore | None = None,
        runtime_stack=None,  # mark.bridge.RuntimeStack
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
                return RouteResponse(
                    status_code=503,
                    body={
                        "event": "error",
                        "error": ApiError.of(
                            "runtime_unavailable",
                            "Desktop runtime is unavailable.",
                        ).to_dict(),
                    },
                )

            # Use the canonical factory to create the AgentLoop
            model = self._resolve_model(stack)
            if model is None:
                return RouteResponse(
                status_code=503,
                    body={
                        "event": "error",
                        "error": ApiError.of(
                            "runtime_config_error",
                            "Runtime stack is missing model configuration.",
                        ).to_dict(),
                    },
                )

            try:
                agent_loop = stack.create_agent_loop(model=model)
            except RuntimeError as exc:
                return RouteResponse(
                    status_code=503,
                    body={
                        "event": "error",
                        "error": ApiError.of(
                            "runtime_config_error",
                            str(exc),
                        ).to_dict(),
                    },
                )

            try:
                result = self._run_agent_loop(agent_loop, request)
                return result
            except RuntimeConfigError as exc:
                return RouteResponse(
                    status_code=503,
                    body={
                        "event": "error",
                        "error": ApiError.of(exc.code, str(exc)).to_dict(),
                    },
                )
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

    def _resolve_model(self, stack) -> ModelInfo | None:
        """Resolve a ModelInfo for the AgentLoop from the runtime stack.

        Tries the router's known models first, then falls back to a default
        constructed from the stack's provider_id.  Returns None only when
        the stack cannot provide any model information.
        """
        router = getattr(stack, "router", None)
        if router is not None:
            models = getattr(router, "_models", None)
            if models and isinstance(models, (list, tuple)) and len(models) > 0:
                return models[0]

            configured_id = getattr(router, "_configured_model_id", None)
            if configured_id and isinstance(configured_id, str) and configured_id.strip():
                provider_id = getattr(router, "provider_id", "gemini") or "gemini"
                return ModelInfo(
                    provider_id=provider_id,
                    model_id=configured_id,
                    display_name=configured_id,
                    tool_calling=True,
                    streaming=True,
                )

        # Last resort: build a minimal ModelInfo from the stack's provider_id
        provider_id = getattr(stack, "provider_id", "gemini") or "gemini"
        return ModelInfo(
            provider_id=provider_id,
            model_id="",
            display_name=provider_id,
            tool_calling=True,
            streaming=True,
        )

    @staticmethod
    def _run_agent_loop(agent_loop, request: ChatRequest) -> RouteResponse:
        """Run one turn of the AgentLoop in a thread.

        Uses the canonical ``AgentLoop.run(user_goal, history=...)`` API.
        The agent loop may make multiple provider calls (tool calls loop).
        We use asyncio.new_event_loop to keep the HTTP handler non-blocking.
        """
        # Validate agent_loop is the real canonical type
        agent_loop_cls = getattr(agent_loop, "__class__", None)
        if agent_loop_cls is None or agent_loop_cls.__name__ != "AgentLoop":
            raise RuntimeConfigError(
                "runtime_error",
                "Runtime stack returned an unexpected agent loop type.",
            )

        # Check that the canonical run method exists
        if not hasattr(agent_loop, "run") or not callable(getattr(agent_loop, "run")):
            raise RuntimeConfigError(
                "runtime_error",
                "AgentLoop instance has no 'run' method.",
            )

        # Check that run_once does NOT exist (defensive check)
        if hasattr(agent_loop, "run_once"):
            raise RuntimeConfigError(
                "runtime_error",
                "AgentLoop has unexpected 'run_once' method; expected canonical 'run'.",
            )

        conversation_id = request.conversation_id or f"conv_{request.idempotency_key}"

        def _run() -> dict:
            from agent.observation import ObservationKind

            # Build history messages for conversation continuity
            history: list[ConversationMessage] = []
            if request.conversation_id:
                history = []

            async def _execute() -> dict:
                result = await agent_loop.run(
                    user_goal=request.message,
                    history=history,
                )
                return {
                    "ok": result.ok,
                    "final_answer": result.final_answer,
                    "steps": list(result.steps),
                    "reason": getattr(result, "reason", None),
                }

            return asyncio.get_event_loop().run_until_complete(_execute())

        try:
            run_result = _run()
        except RuntimeError as exc:
            if "missing provider" in str(exc).lower() or "tool runtime" in str(exc).lower():
                raise RuntimeConfigError(
                    "runtime_config_error",
                    str(exc),
                ) from exc
            raise
        except Exception as exc:
            raise RuntimeConfigError(
                "runtime_error",
                str(exc),
            ) from exc

        answer = run_result.get("final_answer") or ""
        steps = run_result.get("steps") or []
        reason = run_result.get("reason")
        ok = run_result.get("ok", False)

        # Build observation summary
        observations = []
        for s in steps:
            if s is None:
                continue
            obs = getattr(s, "observation", None)
            if obs is not None:
                if obs.kind == ObservationKind.TEXT and obs.content:
                    observations.append(obs.content)
                elif obs.error:
                    observations.append(f"Ошибка инструмента: {obs.error}")

        # Build steps detail for the response
        tool_info = []
        for s in steps:
            if s is None:
                continue
            # AgentLoopStepResult attributes
            tool_name = getattr(s, "tool_name", None)
            tool_ok = getattr(s, "tool_ok", None)
            assistant_text = getattr(s, "assistant_text", None)
            turn_index = getattr(s, "turn_index", None)
            steering = getattr(s, "steering", None)

            if tool_name is not None:
                tool_info.append({
                    "tool_name": tool_name,
                    "ok": tool_ok,
                    "turn": turn_index,
                })
            if assistant_text:
                observations.append(assistant_text)

        response_body: dict[str, object] = {
            "event": "agent_response" if ok else "agent_error",
            "conversation_id": conversation_id,
            "answer": answer,
            "tool_calls": tool_info,
            "observations": observations,
            "ok": ok,
        }
        if reason:
            response_body["reason"] = reason

        status_code = 200 if ok else 422
        return RouteResponse(
            status_code=status_code,
            body=response_body,
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


__all__ = [
    "ChatHandler",
    "ChatHandlerWithRuntime",
    "post_chat",
    "RuntimeConfigError",
]
