"""GET /v1/memory and DELETE /v1/memory/{id} via injected store.

Never reads or writes legacy ``memory/*.json`` files.
"""

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
    MemoryDeleteRequest,
    MemoryEntry,
    MemoryGetResponse,
    SchemaValidationError,
)


class MemoryStore:
    """In-process memory entries. Tests inject this; no filesystem I/O."""

    def __init__(self, entries: tuple[MemoryEntry, ...] | None = None) -> None:
        self._entries: dict[str, MemoryEntry] = {
            e.id: e for e in (entries or ())
        }

    def list_entries(self) -> tuple[MemoryEntry, ...]:
        return tuple(self._entries.values())

    def delete(self, memory_id: str) -> bool:
        if memory_id not in self._entries:
            return False
        del self._entries[memory_id]
        return True


class RuntimeMemoryStore(MemoryStore):
    """Adapter over ``mark.memory.MemoryStore`` used by the live desktop."""

    def __init__(self, backend: object) -> None:
        self._backend = backend

    def list_entries(self) -> tuple[MemoryEntry, ...]:
        records = self._backend.list()  # type: ignore[attr-defined]
        return tuple(
            MemoryEntry(
                id=str(record.id),
                kind=str(getattr(record.type, "value", record.type)),
                summary=str(record.value)[:1000],
            )
            for record in records
        )

    def delete(self, memory_id: str) -> bool:
        return bool(self._backend.delete(memory_id))  # type: ignore[attr-defined]


class MemoryHandler:
    """Memory get/delete against an injected store only."""

    def __init__(
        self,
        *,
        store: MemoryStore | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self.store = store or MemoryStore()
        self._idempotency = idempotency or IdempotencyStore()

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    def get_memory(
        self,
        *,
        principal: DevicePrincipal | None,
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied
        payload = MemoryGetResponse(entries=self.store.list_entries())
        return RouteResponse(status_code=200, body=sanitize_body(payload.to_dict()))

    def delete(
        self,
        *,
        principal: DevicePrincipal | None,
        memory_id: str,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = MemoryDeleteRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        resolved_id = unquote(memory_id)
        fingerprint = {"memory_id": resolved_id}

        def _delete() -> RouteResponse:
            deleted = self.store.delete(resolved_id)
            if not deleted:
                return error_response(404, CODE_NOT_FOUND, "Запись памяти не найдена.")
            return RouteResponse(
                status_code=200,
                body=sanitize_body(
                    {
                        "id": resolved_id,
                        "deleted": True,
                    }
                ),
            )

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"memory_delete:{request.idempotency_key}",
            factory=_delete,
        )


__all__ = ["MemoryHandler", "MemoryStore", "RuntimeMemoryStore"]
