"""Unit tests for models list/activate handlers."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.models import ModelsHandler
from server.schemas import CODE_APPROVAL_REQUIRED


def test_models_list_unauthenticated_returns_401() -> None:
    handler = ModelsHandler()
    response = handler.list_models(principal=None)
    assert response.status_code == 401


def test_models_list_and_activate() -> None:
    handler = ModelsHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    listed = handler.list_models(principal=principal)
    assert listed.status_code == 200
    models = listed.body["models"]
    assert isinstance(models, list)
    assert models

    activated = handler.activate(
        principal=principal,
        body={"model_id": "mock-model", "idempotency_key": "act-1"},
    )
    assert activated.status_code == 202
    assert activated.body["model_id"] == "mock-model"
    assert activated.body.get("active") is True
    assert activated.body.get("approval_required") is True
    assert activated.body.get("status") == CODE_APPROVAL_REQUIRED
    assert "api_key" not in activated.body
