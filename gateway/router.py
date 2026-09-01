"""Namespaced Gateway routing with server-owned authorization context."""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from gateway.contracts import GatewayEnvelope, GatewayProtocolError, utc_timestamp


@dataclass(frozen=True)
class GatewayContext:
    device_id: str
    workspace_id: str
    connection_id: str


GatewayHandler = Callable[
    [GatewayContext, GatewayEnvelope], GatewayEnvelope | Awaitable[GatewayEnvelope]
]


class GatewayRouter:
    def __init__(self, *, idempotency_store=None) -> None:
        self._handlers: dict[str, GatewayHandler] = {}
        self._idempotency_store = idempotency_store

    def register(self, message_type: str, handler: GatewayHandler) -> None:
        if message_type in self._handlers:
            raise ValueError(f"duplicate Gateway route: {message_type}")
        # Contract validation also enforces the official namespace list.
        GatewayEnvelope("route-check", message_type, utc_timestamp(), None, None, {})
        self._handlers[message_type] = handler

    async def dispatch(
        self, context: GatewayContext, envelope: GatewayEnvelope
    ) -> GatewayEnvelope:
        handler = self._handlers.get(envelope.type)
        if handler is None:
            raise GatewayProtocolError("unknown_route", "Gateway route is unavailable.")
        mutating = envelope.type not in {
            "session.list", "session.get", "node.list", "automation.list",
            "approval.list", "media.get", "system.health",
        }
        if mutating and not envelope.request_id:
            raise GatewayProtocolError("missing_request_id", "Mutating request needs request_id.")
        if mutating and self._idempotency_store is not None:
            cached = self._idempotency_store.cached_response(
                device_id=context.device_id, workspace_id=context.workspace_id,
                request_id=envelope.request_id,
            )
            if cached is not None:
                return GatewayEnvelope(**cached)
            if not self._idempotency_store.reserve_request(
                device_id=context.device_id, workspace_id=context.workspace_id,
                request_id=envelope.request_id, now=time.time(),
            ):
                # A concurrent reservation or uncertain prior attempt is never replayed.
                cached = self._idempotency_store.cached_response(
                    device_id=context.device_id, workspace_id=context.workspace_id,
                    request_id=envelope.request_id,
                )
                if cached is not None:
                    return GatewayEnvelope(**cached)
                raise GatewayProtocolError("replay_denied", "Request replay denied.")
        response = handler(context, envelope)
        if inspect.isawaitable(response):
            response = await response
        if not isinstance(response, GatewayEnvelope):
            raise TypeError("Gateway handler must return GatewayEnvelope")
        if mutating and self._idempotency_store is not None:
            self._idempotency_store.cache_response(
                device_id=context.device_id, workspace_id=context.workspace_id,
                request_id=envelope.request_id, response=response.to_dict(), now=time.time(),
            )
        return response


def response_envelope(
    request: GatewayEnvelope, response_type: str, payload: dict[str, object]
) -> GatewayEnvelope:
    return GatewayEnvelope(
        id=str(uuid4()), type=response_type, timestamp=utc_timestamp(),
        session_id=request.session_id, request_id=request.request_id or request.id,
        payload=payload,
    )


def bind_session_routes(router: GatewayRouter, manager) -> None:
    def require_id(envelope: GatewayEnvelope) -> str:
        if not envelope.session_id:
            raise GatewayProtocolError("missing_session", "session_id is required.")
        return envelope.session_id

    def session_list(context: GatewayContext, request: GatewayEnvelope) -> GatewayEnvelope:
        sessions = manager.list(workspace_id=context.workspace_id)
        return response_envelope(request, "session.listed", {
            "sessions": [
                {"id": item.id, "title": item.title, "status": item.status.value,
                 "updated_at": item.updated_at}
                for item in sessions
            ]
        })

    def session_get(context: GatewayContext, request: GatewayEnvelope) -> GatewayEnvelope:
        item = manager.get(require_id(request), workspace_id=context.workspace_id)
        return response_envelope(request, "session.loaded", {
            "id": item.id, "title": item.title, "status": item.status.value,
            "model_policy": {
                "provider_id": item.model_policy.provider_id,
                "model_id": item.model_policy.model_id,
            },
        })

    def lifecycle(method: str, response_type: str) -> GatewayHandler:
        def execute(context: GatewayContext, request: GatewayEnvelope) -> GatewayEnvelope:
            item = getattr(manager, method)(
                require_id(request), workspace_id=context.workspace_id
            )
            return response_envelope(
                request, response_type, {"id": item.id, "status": item.status.value}
            )
        return execute

    router.register("session.list", session_list)
    router.register("session.get", session_get)
    router.register("session.resume", lifecycle("resume", "session.resumed"))
    router.register("session.close", lifecycle("close", "session.closed"))
    router.register("session.archive", lifecycle("archive", "session.archived"))


__all__ = [
    "GatewayContext", "GatewayHandler", "GatewayRouter", "bind_session_routes",
    "response_envelope",
]
