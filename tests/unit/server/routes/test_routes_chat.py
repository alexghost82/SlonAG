"""Unit tests for POST /v1/chat route handler."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.chat import ChatHandler
from server.schemas import CODE_APPROVAL_REQUIRED, CODE_MISSING_FIELD


def test_chat_unauthenticated_returns_401() -> None:
    handler = ChatHandler()
    response = handler.post(
        principal=None,
        body={"message": "hi", "idempotency_key": "c1"},
    )
    assert response.status_code == 401


def test_chat_requires_idempotency_key() -> None:
    handler = ChatHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.post(principal=principal, body={"message": "hi"})
    assert response.status_code == 400
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_MISSING_FIELD


def test_chat_idempotency_no_double_side_effect() -> None:
    handler = ChatHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    body = {
        "message": "hello",
        "idempotency_key": "chat-1",
        "api_key": "sk-should-never-echo",
    }
    first = handler.post(principal=principal, body=body)
    second = handler.post(principal=principal, body=body)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.body == second.body
    assert first.body.get("approval_required") is True
    assert first.body.get("status") == CODE_APPROVAL_REQUIRED
    assert handler.idempotency.side_effect_count("chat:chat-1") == 1
    assert "api_key" not in first.body
    assert "sk-should-never-echo" not in str(first.body)
