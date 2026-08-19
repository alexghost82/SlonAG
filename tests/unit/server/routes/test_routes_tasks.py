"""Unit tests for tasks route handlers."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.tasks import TasksHandler
from server.schemas import CODE_APPROVAL_REQUIRED, CODE_MISSING_FIELD


def test_tasks_list_unauthenticated_returns_401() -> None:
    handler = TasksHandler()
    response = handler.list_tasks(principal=None)
    assert response.status_code == 401


def test_tasks_create_idempotency() -> None:
    handler = TasksHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    body = {"prompt": "plan", "idempotency_key": "task-1"}
    first = handler.create(principal=principal, body=body)
    second = handler.create(principal=principal, body=body)
    assert first.status_code == 202
    assert first.body == second.body
    assert first.body.get("approval_required") is True
    assert first.body.get("status") == CODE_APPROVAL_REQUIRED
    assert handler.idempotency.side_effect_count("tasks_create:task-1") == 1
    listed = handler.list_tasks(principal=principal)
    assert listed.status_code == 200
    assert len(listed.body["tasks"]) == 1  # type: ignore[arg-type]


def test_tasks_create_requires_idempotency_key() -> None:
    handler = TasksHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.create(principal=principal, body={"prompt": "x"})
    assert response.status_code == 400
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_MISSING_FIELD


def test_tasks_cancel_updates_store() -> None:
    handler = TasksHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    created = handler.create(
        principal=principal,
        body={"prompt": "do", "idempotency_key": "t-create"},
    )
    task_id = str(created.body["id"])
    cancelled = handler.cancel(
        principal=principal,
        task_id=task_id,
        body={"idempotency_key": "t-cancel"},
    )
    assert cancelled.status_code == 202
    assert cancelled.body["id"] == task_id
    assert cancelled.body.get("approval_required") is True
