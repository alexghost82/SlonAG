"""GET /v1/models and POST /v1/models/activate."""

from __future__ import annotations

from typing import Mapping

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
    ModelInfo,
    ModelsActivateRequest,
    ModelsListResponse,
    SchemaValidationError,
)


class ModelStore:
    """Injected model catalog. Activation updates local state only — no cloud."""

    def __init__(self, models: tuple[ModelInfo, ...] | None = None) -> None:
        if models is None:
            models = ()
        self._models: dict[str, ModelInfo] = {m.id: m for m in models}

    def list_models(self) -> tuple[ModelInfo, ...]:
        return tuple(self._models.values())

    def activate(self, model_id: str) -> ModelInfo | None:
        if model_id not in self._models:
            return None
        updated: dict[str, ModelInfo] = {}
        for mid, info in self._models.items():
            updated[mid] = ModelInfo(
                id=info.id,
                provider_id=info.provider_id,
                display_name=info.display_name,
                active=(mid == model_id),
            )
        self._models = updated
        return self._models[model_id]


class ModelsHandler:
    """List models and activate one via injected store (no api_keys.json)."""

    def __init__(
        self,
        *,
        store: ModelStore | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self.store = store or ModelStore()
        self._idempotency = idempotency or IdempotencyStore()

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    def list_models(
        self,
        *,
        principal: DevicePrincipal | None,
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied
        payload = ModelsListResponse(models=self.store.list_models())
        return RouteResponse(status_code=200, body=sanitize_body(payload.to_dict()))

    def activate(
        self,
        *,
        principal: DevicePrincipal | None,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = ModelsActivateRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        fingerprint = {"model_id": request.model_id, "role": request.role}

        def _activate() -> RouteResponse:
            # Activation is local catalog state only; approval flag retained for
            # SafetyPolicy wiring by app.py later — no provider calls here.
            activated = self.store.activate(request.model_id)
            if activated is None:
                return error_response(404, CODE_NOT_FOUND, "Model not found.")
            result: dict[str, object] = {
                "model_id": activated.id,
                "provider_id": activated.provider_id,
                "active": activated.active,
                "approval_required": True,
                "status": CODE_APPROVAL_REQUIRED,
            }
            if request.role is not None:
                result["role"] = request.role
            return RouteResponse(status_code=202, body=sanitize_body(result))

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"models_activate:{request.idempotency_key}",
            factory=_activate,
        )


__all__ = ["ModelStore", "ModelsHandler"]
