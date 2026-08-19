"""GET /v1/approvals and POST decision — store updates only (no tool execution)."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import unquote

from server.routes._common import (
    DevicePrincipal,
    IdempotencyStore,
    RouteResponse,
    error_response,
    require_active_principal,
    sanitize_body,
    schema_error_response,
)
from server.schemas import (
    CODE_NOT_FOUND,
    ApprovalDecisionRequest,
    ApprovalInfo,
    ApprovalListResponse,
    SchemaValidationError,
)

_ALLOWED_DECISIONS = frozenset({"approve", "deny", "allow", "reject"})


class ApprovalStore:
    """Injected approval store. Decisions update records only — never run tools."""

    def __init__(self) -> None:
        self._items: dict[str, ApprovalInfo] = {}

    def seed(self, info: ApprovalInfo) -> None:
        self._items[info.id] = info

    def list_approvals(self) -> tuple[ApprovalInfo, ...]:
        return tuple(self._items.values())

    def get(self, approval_id: str) -> ApprovalInfo | None:
        return self._items.get(approval_id)

    def decide(self, approval_id: str, decision: str) -> ApprovalInfo | None:
        existing = self._items.get(approval_id)
        if existing is None:
            return None
        status = "approved" if decision in {"approve", "allow"} else "denied"
        updated = ApprovalInfo(
            id=existing.id,
            tool_name=existing.tool_name,
            risk=existing.risk,
            status=status,
            source=existing.source,
            intent=existing.intent,
        )
        self._items[approval_id] = updated
        return updated


class ApprovalsHandler:
    """List pending approvals and record decisions against the injected store."""

    def __init__(
        self,
        *,
        store: ApprovalStore | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self.store = store or ApprovalStore()
        self._idempotency = idempotency or IdempotencyStore()

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    def list_approvals(
        self,
        *,
        principal: DevicePrincipal | None,
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied
        payload = ApprovalListResponse(approvals=self.store.list_approvals())
        return RouteResponse(status_code=200, body=sanitize_body(payload.to_dict()))

    def decide(
        self,
        *,
        principal: DevicePrincipal | None,
        approval_id: str,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = ApprovalDecisionRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        decision = request.decision.strip().lower()
        if decision not in _ALLOWED_DECISIONS:
            return error_response(
                400,
                "invalid_request",
                "Field 'decision' must be approve/deny (or allow/reject).",
                field="decision",
            )

        resolved_id = unquote(approval_id)
        fingerprint = {"approval_id": resolved_id, "decision": decision}

        def _decide() -> RouteResponse:
            updated = self.store.decide(resolved_id, decision)
            if updated is None:
                return error_response(404, CODE_NOT_FOUND, "Approval not found.")
            return RouteResponse(
                status_code=200,
                body=sanitize_body(
                    {
                        "id": updated.id,
                        "decision": decision,
                        "status": updated.status,
                        "tool_name": updated.tool_name,
                        "risk": updated.risk,
                    }
                ),
            )

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"approvals_decision:{request.idempotency_key}",
            factory=_decide,
        )


__all__ = ["ApprovalStore", "ApprovalsHandler"]
