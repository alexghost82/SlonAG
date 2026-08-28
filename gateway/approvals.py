"""One durable, fail-closed approval lifecycle for Gateway and compatibility UI."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from gateway.store import GatewayStore


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    workspace_id: str
    session_id: str | None
    run_id: str | None
    tool_call_id: str
    tool_name: str
    expires_at: float


class DurableApprovalCoordinator:
    def __init__(self, store: GatewayStore) -> None:
        self.store = store
        self._lock = threading.RLock()
        self._waiters: dict[str, tuple[threading.Event, list[bool]]] = {}

    def request(
        self, *, workspace_id: str, tool_name: str, reason: str,
        timeout: float, session_id: str | None = None, run_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> ApprovalRequest:
        if not tool_call_id:
            raise ValueError("durable approval requires canonical tool_call_id")
        now = time.time()
        approval_id = str(uuid4())
        self.store.create_approval(
            approval_id=approval_id, workspace_id=workspace_id,
            session_id=session_id, run_id=run_id, tool_call_id=tool_call_id,
            tool_name=tool_name, reason=reason[:1000], created_at=now,
            expires_at=now + max(0.01, timeout),
        )
        with self._lock:
            self._waiters[approval_id] = (threading.Event(), [])
        return ApprovalRequest(
            approval_id, workspace_id, session_id, run_id, tool_call_id,
            tool_name, now + max(0.01, timeout),
        )

    def wait(self, request: ApprovalRequest, *, timeout: float) -> bool:
        with self._lock:
            waiter = self._waiters.get(request.approval_id)
        if waiter is None:
            return False
        event, result = waiter
        if not event.wait(max(0.0, timeout)):
            self.store.decide_approval(
                approval_id=request.approval_id, workspace_id=request.workspace_id,
                decision="expired", device_id=None, now=time.time(),
            )
        with self._lock:
            self._waiters.pop(request.approval_id, None)
        row = self.store.approval(request.approval_id)
        return bool(
            result and result[0]
            and row is not None
            and row["status"] == "allowed"
            and row["workspace_id"] == request.workspace_id
            and row["session_id"] == request.session_id
            and row["run_id"] == request.run_id
            and row["tool_call_id"] == request.tool_call_id
        )

    def decide(
        self, *, approval_id: str, workspace_id: str, allow: bool,
        device_id: str,
    ) -> bool:
        accepted = self.store.decide_approval(
            approval_id=approval_id, workspace_id=workspace_id,
            decision="allowed" if allow else "denied", device_id=device_id,
            now=time.time(),
        )
        if not accepted:
            return False
        with self._lock:
            waiter = self._waiters.get(approval_id)
        if waiter is not None:
            event, result = waiter
            result.append(bool(allow))
            event.set()
        return True

    def cancel(self, approval_id: str, *, workspace_id: str) -> None:
        self.store.decide_approval(
            approval_id=approval_id, workspace_id=workspace_id,
            decision="cancelled", device_id=None, now=time.time(),
        )
        with self._lock:
            waiter = self._waiters.pop(approval_id, None)
        if waiter is not None:
            waiter[0].set()

    def close(self) -> None:
        with self._lock:
            approval_ids = tuple(self._waiters)
        for approval_id in approval_ids:
            row = self.store.approval(approval_id)
            if row is not None:
                self.cancel(approval_id, workspace_id=str(row["workspace_id"]))


__all__ = ["ApprovalRequest", "DurableApprovalCoordinator"]


# E2E test compatibility shims

@dataclass
class ApprovalGate:
    """Approval gate for Gateway tool/result flow E2E tests."""
    name: str = "approval_gate"
    pending: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pending is None:
            self.pending = []

    def request_approval(self, tool_call_id: str, tool_name: str, workspace_id: str = "default") -> str:
        approval_id = uuid4().hex
        self.pending.append({
            "approval_id": approval_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "workspace_id": workspace_id,
            "approved": False,
        })
        return approval_id

    def get_status(self, approval_id: str) -> dict:
        for p in self.pending:
            if p["approval_id"] == approval_id:
                return p
        return {"approval_id": approval_id, "approved": False}

    def approve(self, approval_id: str) -> None:
        for p in self.pending:
            if p["approval_id"] == approval_id:
                p["approved"] = True
                break

    async def request(self, tool: str, args: dict,
        user_id: str = "", workspace: str = "",
    ) -> str:
        """Alias for request_approval with E2E-friendly kwargs."""
        return self.request_approval(
            tool_call_id=f"{tool}-{uuid4().hex[:8]}",
            tool_name=tool,
            workspace_id=workspace or "default",
        )

    async def await_one(self, request_id: str, timeout: float = 5.0) -> dict | None:
        """Wait for approval with timeout. Returns status dict or None on timeout."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.get_status(request_id)
            if status.get("approved"):
                return status
            await asyncio.sleep(0.05)
        return None  # timeout

    def list_pending(self) -> list[dict]:
        return [p for p in self.pending if not p["approved"]]
