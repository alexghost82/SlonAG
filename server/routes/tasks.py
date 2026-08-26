"""GET/POST /v1/tasks and cancel — in-process task stubs."""

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
    CODE_APPROVAL_REQUIRED,
    CODE_NOT_FOUND,
    SchemaValidationError,
    TaskCancelRequest,
    TaskCreateRequest,
    TaskInfo,
    TaskListResponse,
)


class TaskStore:
    """Injected in-memory task store. No desktop tool execution."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}
        self._seq = 0

    def list_tasks(self) -> tuple[TaskInfo, ...]:
        return tuple(self._tasks.values())

    def get(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

    def create(self, *, prompt: str, approval_required: bool = True) -> TaskInfo:
        self._seq += 1
        task_id = f"task_{self._seq}"
        info = TaskInfo(
            id=task_id,
            status=CODE_APPROVAL_REQUIRED if approval_required else "queued",
            prompt=prompt,
            approval_required=approval_required,
        )
        self._tasks[task_id] = info
        return info

    def cancel(self, task_id: str, *, approval_required: bool = True) -> TaskInfo | None:
        existing = self._tasks.get(task_id)
        if existing is None:
            return None
        updated = TaskInfo(
            id=existing.id,
            status=CODE_APPROVAL_REQUIRED if approval_required else "cancelled",
            prompt=existing.prompt,
            approval_required=approval_required,
        )
        self._tasks[task_id] = updated
        return updated

    def set_status(
        self,
        task_id: str,
        status: str,
        *,
        approval_required: bool = False,
    ) -> TaskInfo | None:
        existing = self._tasks.get(task_id)
        if existing is None:
            return None
        updated = TaskInfo(
            id=existing.id,
            status=status,
            prompt=existing.prompt,
            approval_required=approval_required,
        )
        self._tasks[task_id] = updated
        return updated


class TasksHandler:
    """List / create / cancel tasks with auth + idempotency."""

    def __init__(
        self,
        *,
        store: TaskStore | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self.store = store or TaskStore()
        self._idempotency = idempotency or IdempotencyStore()

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    def list_tasks(
        self,
        *,
        principal: DevicePrincipal | None,
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied
        payload = TaskListResponse(tasks=self.store.list_tasks())
        return RouteResponse(status_code=200, body=sanitize_body(payload.to_dict()))

    def create(
        self,
        *,
        principal: DevicePrincipal | None,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = TaskCreateRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        fingerprint = {"prompt": request.prompt}

        def _create() -> RouteResponse:
            # Mutating create goes through approval gate stub — no tools run.
            info = self.store.create(prompt=request.prompt, approval_required=True)
            return RouteResponse(status_code=202, body=sanitize_body(info.to_dict()))

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"tasks_create:{request.idempotency_key}",
            factory=_create,
        )

    def cancel(
        self,
        *,
        principal: DevicePrincipal | None,
        task_id: str,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = TaskCancelRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        resolved_id = unquote(task_id)
        fingerprint = {"task_id": resolved_id}

        def _cancel() -> RouteResponse:
            info = self.store.cancel(resolved_id, approval_required=True)
            if info is None:
                return error_response(404, CODE_NOT_FOUND, "Задача не найдена.")
            return RouteResponse(status_code=202, body=sanitize_body(info.to_dict()))

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"tasks_cancel:{request.idempotency_key}",
            factory=_cancel,
        )


__all__ = ["TaskStore", "TasksHandler"]
