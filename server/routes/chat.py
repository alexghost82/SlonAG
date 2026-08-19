"""POST /v1/chat — mutating; approval-gate stub (no tool / LLM execution)."""

from __future__ import annotations

from typing import Mapping

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
    """In-process chat entry that always routes mutating work through approval."""

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


def post_chat(
    *,
    principal: DevicePrincipal | None,
    body: Mapping[str, object],
    handler: ChatHandler | None = None,
) -> RouteResponse:
    """Module-level convenience wrapper around ``ChatHandler.post``."""
    return (handler or ChatHandler()).post(principal=principal, body=body)


__all__ = ["ChatHandler", "post_chat"]
