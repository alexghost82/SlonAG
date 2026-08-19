"""Unit tests for screen capture stub."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.screen import ScreenHandler
from server.schemas import CODE_APPROVAL_REQUIRED, CODE_MISSING_FIELD


def test_screen_unauthenticated_returns_401() -> None:
    handler = ScreenHandler()
    response = handler.capture(
        principal=None,
        body={"idempotency_key": "cap-1"},
    )
    assert response.status_code == 401


def test_screen_capture_returns_mock_metadata() -> None:
    handler = ScreenHandler(width=800, height=600)
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.capture(
        principal=principal,
        body={"idempotency_key": "cap-1"},
    )
    assert response.status_code == 202
    assert response.body["width"] == 800
    assert response.body["height"] == 600
    assert response.body["mime_type"] == "image/png"
    assert response.body["capture_id"] == "cap_cap-1"
    assert response.body.get("approval_required") is True
    assert response.body.get("status") == CODE_APPROVAL_REQUIRED
    # No raw screenshot bytes in the stub response.
    assert "bytes" not in response.body
    assert "data" not in response.body


def test_screen_requires_idempotency_key() -> None:
    handler = ScreenHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.capture(principal=principal, body={})
    assert response.status_code == 400
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_MISSING_FIELD
