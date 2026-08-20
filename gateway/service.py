"""Gateway composition root and anti-corruption adapters into Slon runtime."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from gateway.artifacts import ArtifactTransferService
from gateway.auth import GatewayAuthService
from gateway.contracts import GatewayEnvelope, utc_timestamp
from gateway.router import (
    GatewayContext,
    GatewayRouter,
    bind_session_routes,
    response_envelope,
)
from gateway.store import GatewayStore
from gateway.websocket import GatewayWebSocketRuntime


class SlonGateway:
    """One canonical Gateway stack; internal runtime remains gateway-unaware."""

    def __init__(
        self, *, database_path: str | Path, artifact_root: str | Path,
        signing_key: bytes, session_manager=None, runtime_stack=None,
        approval_handler: Callable[[GatewayContext, GatewayEnvelope], Any] | None = None,
        agent_runner: Callable[[GatewayContext, GatewayEnvelope], Awaitable[GatewayEnvelope]] | None = None,
    ) -> None:
        self.store = GatewayStore(database_path)
        self.store.recover_uncertain(time.time())
        self.auth = GatewayAuthService(store=self.store, signing_key=signing_key)
        self.router = GatewayRouter(idempotency_store=self.store)
        if session_manager is not None:
            bind_session_routes(self.router, session_manager)
        if approval_handler is not None:
            self.router.register("approval.decide", approval_handler)
        if agent_runner is not None:
            self.router.register("agent.run", agent_runner)
        self.router.register("system.health", self._health)
        self.artifacts = ArtifactTransferService(
            store=self.store, root=artifact_root, signing_key=signing_key
        )
        self.router.register("media.issue_upload", self._issue_upload)
        self.router.register("media.issue_download", self._issue_download)
        self.websocket = GatewayWebSocketRuntime(
            store=self.store, router=self.router,
            is_active=lambda device_id: bool(
                (record := self.store.device(device_id)) and record["active"]
            ),
            workspace_for=self.auth.workspace_for,
        )
        self.runtime_stack = runtime_stack

    def _health(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        return response_envelope(request, "system.health_status", {
            "alive": True,
            "runtime_composed": self.runtime_stack is not None,
        })

    def _issue_upload(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        mime_type = request.payload.get("mime_type")
        max_bytes = request.payload.get("max_bytes")
        if not isinstance(mime_type, str) or not isinstance(max_bytes, int):
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("invalid_payload", "mime_type/max_bytes are required.")
        grant = self.artifacts.issue(
            device_id=context.device_id, workspace_id=context.workspace_id,
            operation="upload", mime_type=mime_type, max_bytes=max_bytes,
        )
        return response_envelope(request, "media.upload_granted", {
            "artifact_id": grant.artifact_id, "ticket": grant.ticket,
            "expires_at": grant.expires_at, "max_bytes": grant.max_bytes,
            "mime_type": grant.mime_type,
        })

    def _issue_download(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        artifact_id = request.payload.get("artifact_id")
        mime_type = request.payload.get("mime_type")
        max_bytes = request.payload.get("max_bytes")
        if not isinstance(artifact_id, str) or not isinstance(mime_type, str) or not isinstance(max_bytes, int):
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("invalid_payload", "artifact fields are required.")
        grant = self.artifacts.issue_download(
            artifact_id=artifact_id, device_id=context.device_id,
            workspace_id=context.workspace_id, mime_type=mime_type,
            max_bytes=max_bytes,
        )
        return response_envelope(request, "media.download_granted", {
            "artifact_id": grant.artifact_id, "ticket": grant.ticket,
            "expires_at": grant.expires_at,
        })

    def publish_runtime_event(self, event, *, workspace_id: str | None = None) -> int:
        payload = {
            "kind": event.kind.value,
            "sequence": event.sequence,
            "turn_id": event.turn_id,
            "tool_call_id": event.tool_call_id,
            "tool_name": event.tool_name,
            "progress": event.progress,
            "code": event.code,
            "connection_generation": event.connection_generation,
        }
        envelope = GatewayEnvelope(
            id=str(uuid4()), type="system.runtime_event", timestamp=utc_timestamp(),
            session_id=event.session_id, request_id=None, payload=payload,
        )
        # Workspace is resolved by the session-owning adapter; runtime events
        # never trust a workspace from an external client.
        if workspace_id is None and event.session_id is not None:
            manager = getattr(self.runtime_stack, "session_manager", None)
            if manager is None:
                raise ValueError("runtime event session workspace cannot be resolved")
            workspace_id = manager.get(event.session_id).workspace_id
        if workspace_id is None:
            raise ValueError("runtime event workspace is required")
        return self.websocket.publish_now(workspace_id, envelope)

    def publish_control_event(
        self, event: dict[str, object], *, workspace_id: str
    ) -> int:
        safe_payload = {
            key: value for key, value in event.items()
            if key in {"event", "timestamp", "kind", "sequence", "session_id",
                       "connection_generation", "turn_id", "tool_call_id",
                       "tool_name", "progress", "code", "assistant_state"}
        }
        session_id = safe_payload.get("session_id")
        envelope = GatewayEnvelope(
            id=str(uuid4()), type="system.runtime_event", timestamp=utc_timestamp(),
            session_id=session_id if isinstance(session_id, str) else None,
            request_id=None, payload=safe_payload,
        )
        return self.websocket.publish_now(workspace_id, envelope)

    def close(self) -> None:
        self.websocket.close()
        self.store.close()


__all__ = ["SlonGateway"]
