"""Unit tests for GET /v1/status route handler."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.status import get_status
from server.schemas import CODE_UNAUTHORIZED, StatusResponse


def test_status_unauthenticated_returns_401() -> None:
    response = get_status(principal=None)
    assert response.status_code == 401
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_UNAUTHORIZED


def test_status_revoked_returns_403() -> None:
    principal = DevicePrincipal(device_id="dev_1", revoked=True)
    response = get_status(principal=principal)
    assert response.status_code == 403
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_UNAUTHORIZED


def test_status_happy_path_with_injected_provider() -> None:
    """Status returns injected provider data; no fake defaults."""
    principal = DevicePrincipal(device_id="dev_ok")

    def provider() -> StatusResponse:
        return StatusResponse(
            online=True,
            paired=True,
            provider_id="local",
            model_id="mock-model",
            network_mode="local",
            privacy_profile="fully_local",
            active_tasks=0,
            pending_approvals=0,
        )

    response = get_status(principal=principal, provider=provider)
    assert response.status_code == 200
    assert response.body["online"] is True
    assert response.body["paired"] is True
    assert "api_key" not in response.body
    assert "gemini_api_key" not in response.body
    assert response.body["provider_id"] == "local"


def test_status_uses_injected_provider() -> None:
    principal = DevicePrincipal(device_id="dev_ok")

    def provider() -> StatusResponse:
        return StatusResponse(
            online=True,
            paired=True,
            provider_id="local",
            model_id="custom",
            active_tasks=2,
            pending_approvals=1,
        )

    response = get_status(principal=principal, provider=provider)
    assert response.status_code == 200
    assert response.body["model_id"] == "custom"
    assert response.body["active_tasks"] == 2
    assert response.body["pending_approvals"] == 1


def test_status_default_uses_real_runtime() -> None:
    """Without injected provider, get_status queries real runtime state."""
    principal = DevicePrincipal(device_id="dev_ok")
    response = get_status(principal=principal)
    assert response.status_code == 200
    # Real runtime may or may not be online — just check structure
    assert isinstance(response.body["online"], bool)
    assert isinstance(response.body["paired"], bool)
    assert "online" in response.body
    assert "provider_id" in response.body


def test_status_sanitizes_secrets() -> None:
    """Secret fields are stripped from the status response."""
    principal = DevicePrincipal(device_id="dev_ok")

    def provider() -> StatusResponse:
        return StatusResponse(
            online=True,
            paired=True,
            provider_id="local",
            model_id="test-model",
        )

    response = get_status(principal=principal, provider=provider)
    for secret_key in ("api_key", "gemini_api_key", "openai_api_key", "openrouter_api_key"):
        assert secret_key not in response.body
