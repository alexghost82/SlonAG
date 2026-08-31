"""Gateway composition root and anti-corruption adapters into Slon runtime."""

from __future__ import annotations

import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from gateway.artifacts import ArtifactTransferService
from gateway.approvals import DurableApprovalCoordinator
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
from acta.automation.engine import AutomationEngine, AutomationRecord, TriggerType


class SlonGateway:
    """One canonical Gateway stack; internal runtime remains gateway-unaware."""

    def __init__(
        self, *, database_path: str | Path, artifact_root: str | Path,
        signing_key: bytes, session_manager=None, runtime_stack=None,
        automation_engine: AutomationEngine | None = None,
        approval_handler: Callable[[GatewayContext, GatewayEnvelope], Any] | None = None,
        agent_runner: Callable[[GatewayContext, GatewayEnvelope], Awaitable[GatewayEnvelope]] | None = None,
    ) -> None:
        self.store = GatewayStore(database_path)
        self.store.recover_uncertain(time.time())
        self.auth = GatewayAuthService(store=self.store, signing_key=signing_key)
        self.approvals = DurableApprovalCoordinator(self.store)
        self.router = GatewayRouter(idempotency_store=self.store)
        if session_manager is not None:
            bind_session_routes(self.router, session_manager)
        if approval_handler is not None:
            self.router.register("approval.decide", approval_handler)
        if agent_runner is not None:
            self.router.register("agent.run", agent_runner)
        self.router.register("system.health", self._health)
        self.router.register("node.list", self._node_list)
        self.router.register("automation.list", self._automation_list)
        self.router.register("approval.list", self._approval_list)
        if approval_handler is None:
            self.router.register("approval.decide", self._approval_decide)
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
        self.session_manager = session_manager
        self._automation = None
        self._jobs = ThreadPoolExecutor(max_workers=4, thread_name_prefix="slon-gateway-job")
        if session_manager is not None and runtime_stack is not None:
            if agent_runner is None:
                self.router.register("agent.run", self._agent_run)
        if automation_engine is not None:
            self._automation = automation_engine
            self.router.register("automation.list", self._automation_list)
            self.router.register("automation.create", self._automation_create)
            self.router.register("automation.cancel", self._automation_cancel)
            self.router.register("automation.delete", self._automation_delete)
            self.router.register("automation.list_all", self._automation_list_all)

    def _health(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        return response_envelope(request, "system.health_status", {
            "alive": True,
            "runtime_composed": self.runtime_stack is not None,
        })

    def _node_list(self, context: GatewayContext, request: GatewayEnvelope) -> GatewayEnvelope:
        return response_envelope(request, "node.listed", {"nodes": [{
            "id": "local-runtime", "kind": "desktop", "online": True,
        }]})

    def _automation_list(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        if self._automation is None:
            return response_envelope(request, "automation.listed", {"automations": []})
        records = self._automation.list(workspace_id=context.workspace_id)
        return response_envelope(request, "automation.listed", {"automations": [{
            "id": r.id, "name": r.name, "trigger_type": r.trigger_type,
            "goal": r.goal, "status": r.status, "run_count": r.run_count,
            "last_run_at": r.last_run_at, "next_run_at": r.next_run_at,
            "enabled": r.enabled, "recovery_attempts": r.recovery_attempts,
        } for r in records]})

    def _automation_list_all(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        if self._automation is None:
            return response_envelope(request, "automation.listed", {"automations": []})
        records = self._automation.list()
        return response_envelope(request, "automation.listed", {"automations": [{
            "id": r.id, "name": r.name, "trigger_type": r.trigger_type,
            "goal": r.goal, "status": r.status, "run_count": r.run_count,
            "workspace_id": r.workspace_id, "enabled": r.enabled,
        } for r in records]})

    def _automation_create(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        if self._automation is None:
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("automation_unavailable", "Automation engine not configured.")
        payload = request.payload or {}
        name = payload.get("name", "")
        goal = payload.get("goal", "")
        trigger_type = payload.get("trigger_type", "one_shot")
        if not name or not goal:
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("invalid_payload", "name and goal are required.")
        record = self._automation.create(
            name=name,
            trigger_type=TriggerType(trigger_type),
            payload=payload.get("config", {}),
            goal=goal,
            workspace_id=context.workspace_id,
        )
        return response_envelope(request, "automation.created", {
            "id": record.id, "name": record.name, "status": record.status,
        })

    def _automation_cancel(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        if self._automation is None:
            return response_envelope(request, "automation.cancelled", {"id": "", "success": False})
        record_id = request.payload.get("id", "")
        success = self._automation.cancel(record_id)
        return response_envelope(request, "automation.cancelled", {"id": record_id, "success": success})

    def _automation_delete(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        if self._automation is None:
            return response_envelope(request, "automation.deleted", {"id": "", "success": False})
        record_id = request.payload.get("id", "")
        success = self._automation.delete(record_id)
        return response_envelope(request, "automation.deleted", {"id": record_id, "success": success})

    async def _agent_run(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        if not request.session_id:
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("missing_session", "session_id is required.")
        goal = request.payload.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("invalid_payload", "goal is required.")
        session = self.session_manager.get(
            request.session_id, workspace_id=context.workspace_id
        )
        models = await self.runtime_stack.router.list_models(
            session.model_policy.provider_id
        )
        model = next((item for item in models if (
            item.provider_id == session.model_policy.provider_id
            and item.model_id == session.model_policy.model_id
        )), None)
        if model is None:
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("model_unavailable", "Session model is unavailable.")
        operation_id = request.request_id or request.id
        self.store.put_operation(
            operation_id=operation_id, kind="job", device_id=context.device_id,
            workspace_id=context.workspace_id, session_id=request.session_id,
            status="running", payload={
                "type": "agent.run", "job_id": operation_id,
                "request_id": request.request_id, "session_id": request.session_id,
            }, now=time.time(),
        )
        self._jobs.submit(
            self._run_agent_job, context, request, goal.strip(), model, operation_id
        )
        return response_envelope(request, "agent.accepted", {
            "job_id": operation_id, "status": "running",
        })

    def _run_agent_job(
        self, context: GatewayContext, request: GatewayEnvelope, goal: str,
        model, operation_id: str,
    ) -> None:
        from acta.tools import ToolExecutor

        def confirm(decision) -> bool:
            if not decision.tool_call_id:
                return False
            pending = self.approvals.request(
                workspace_id=context.workspace_id, session_id=request.session_id,
                run_id=operation_id, tool_call_id=decision.tool_call_id,
                tool_name=decision.tool_name,
                reason=decision.reason or "Safety confirmation required", timeout=120,
            )
            event = GatewayEnvelope(
                id=str(uuid4()), type="approval.requested", timestamp=utc_timestamp(),
                session_id=request.session_id, request_id=request.request_id,
                payload={
                    "approval_id": pending.approval_id,
                    "job_id": operation_id,
                    "tool_call_id": pending.tool_call_id,
                    "tool_name": decision.tool_name,
                    "expires_at": pending.expires_at,
                },
            )
            self.websocket.publish_now(context.workspace_id, event)
            allowed = self.approvals.wait(pending, timeout=120)
            operation = self.store.operation(
                operation_id, workspace_id=context.workspace_id
            )
            return bool(allowed and operation and operation["status"] == "running")

        executor = ToolExecutor(
            self.runtime_stack.tool_registry, self.runtime_stack.safety,
            confirmer=confirm,
        )
        scoped_stack = replace(self.runtime_stack, tool_executor=executor)
        try:
            result = asyncio.run(scoped_stack.create_session_binding().run(
                request.session_id, goal, workspace_id=context.workspace_id,
                model=model,
            ))
            status = "completed" if result.ok else "failed"
            payload = {
                "job_id": operation_id, "ok": bool(result.ok),
                "answer": result.final_answer, "stop_reason": result.reason,
            }
        except BaseException as exc:
            status = "interrupted"
            payload = {
                "job_id": operation_id, "ok": False, "code": "interrupted",
                "error_type": type(exc).__name__,
            }
        if not self.store.update_operation(operation_id, status, time.time()):
            return
        self.websocket.publish_now(context.workspace_id, GatewayEnvelope(
            id=str(uuid4()), type="agent.completed", timestamp=utc_timestamp(),
            session_id=request.session_id, request_id=request.request_id,
            payload=payload,
        ))

    def _approval_list(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        values = self.store.approvals(workspace_id=context.workspace_id)
        return response_envelope(request, "approval.listed", {"approvals": [
            {"id": item["approval_id"], "status": item["status"],
             "session_id": item["session_id"], "run_id": item["run_id"],
             "tool_call_id": item["tool_call_id"], "tool_name": item["tool_name"]}
            for item in values
        ]})

    def _approval_decide(
        self, context: GatewayContext, request: GatewayEnvelope
    ) -> GatewayEnvelope:
        approval_id = request.payload.get("approval_id")
        decision = request.payload.get("decision")
        if not isinstance(approval_id, str) or decision not in {"allow", "deny"}:
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("invalid_payload", "approval decision is invalid.")
        if not self.approvals.decide(
            approval_id=approval_id, workspace_id=context.workspace_id,
            allow=decision == "allow", device_id=context.device_id,
        ):
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("approval_unavailable", "Approval is unavailable.")
        approval = self.store.approval(approval_id)
        if approval is None:  # A successful CAS must still resolve its row.
            from gateway.contracts import GatewayProtocolError
            raise GatewayProtocolError("approval_unavailable", "Approval is unavailable.")
        return response_envelope(request, "approval.decided", {
            "approval_id": approval_id, "decision": decision,
            "tool_call_id": approval["tool_call_id"],
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
        self.approvals.close()
        self._jobs.shutdown(wait=True, cancel_futures=True)
        self.websocket.close()
        self.store.close()


__all__ = ["SlonGateway"]
