"""POST /v1/screen/capture — stub metadata only (no screenshot library)."""

from __future__ import annotations

from typing import Mapping

from server.routes._common import (
    DevicePrincipal,
    IdempotencyStore,
    RouteResponse,
    require_active_principal,
    sanitize_body,
    schema_error_response,
)
from server.schemas import (
    CODE_APPROVAL_REQUIRED,
    SchemaValidationError,
    ScreenCaptureRequest,
    ScreenCaptureResponse,
)


class ScreenHandler:
    """Return mock capture metadata; never grabs a real framebuffer."""

    def __init__(
        self,
        *,
        idempotency: IdempotencyStore | None = None,
        width: int = 1280,
        height: int = 720,
        mime_type: str = "image/png",
    ) -> None:
        self._idempotency = idempotency or IdempotencyStore()
        self._width = width
        self._height = height
        self._mime_type = mime_type

    @property
    def idempotency(self) -> IdempotencyStore:
        return self._idempotency

    def capture(
        self,
        *,
        principal: DevicePrincipal | None,
        body: Mapping[str, object],
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        try:
            request = ScreenCaptureRequest.from_dict(body)
        except SchemaValidationError as exc:
            return schema_error_response(exc)

        fingerprint = {"op": "screen_capture"}

        def _capture() -> RouteResponse:
            response = ScreenCaptureResponse(
                width=self._width,
                height=self._height,
                mime_type=self._mime_type,
                capture_id=f"cap_{request.idempotency_key}",
                approval_required=True,
            )
            payload = response.to_dict()
            payload["status"] = CODE_APPROVAL_REQUIRED
            return RouteResponse(status_code=202, body=sanitize_body(payload))

        return self._idempotency.run(
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            side_effect_key=f"screen_capture:{request.idempotency_key}",
            factory=_capture,
        )


__all__ = ["ScreenHandler"]
