"""Unit tests for approvals route handlers."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.approvals import ApprovalStore, ApprovalsHandler
from server.schemas import ApprovalInfo


def test_approvals_list_unauthenticated_returns_401() -> None:
    handler = ApprovalsHandler()
    response = handler.list_approvals(principal=None)
    assert response.status_code == 401


def test_approvals_decision_updates_store() -> None:
    store = ApprovalStore()
    store.seed(
        ApprovalInfo(
            id="appr_1",
            tool_name="desktop.click",
            risk="high",
            status="pending",
            source="chat",
            intent="click button",
        )
    )
    handler = ApprovalsHandler(store=store)
    principal = DevicePrincipal(device_id="dev_ok")

    listed = handler.list_approvals(principal=principal)
    assert listed.status_code == 200
    assert len(listed.body["approvals"]) == 1  # type: ignore[arg-type]

    decided = handler.decide(
        principal=principal,
        approval_id="appr_1",
        body={"decision": "approve", "idempotency_key": "dec-1"},
    )
    assert decided.status_code == 200
    assert decided.body["status"] == "approved"
    assert decided.body["decision"] == "approve"

    # Store must reflect the decision; no tool execution occurred.
    updated = store.get("appr_1")
    assert updated is not None
    assert updated.status == "approved"

    # Idempotent replay does not flip status again unexpectedly.
    again = handler.decide(
        principal=principal,
        approval_id="appr_1",
        body={"decision": "approve", "idempotency_key": "dec-1"},
    )
    assert again.body == decided.body
    assert handler.idempotency.side_effect_count("approvals_decision:dec-1") == 1


def test_approvals_decision_unknown_id_404() -> None:
    handler = ApprovalsHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.decide(
        principal=principal,
        approval_id="missing",
        body={"decision": "deny", "idempotency_key": "dec-miss"},
    )
    assert response.status_code == 404
