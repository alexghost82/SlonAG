"""Unit tests for Desktop Control API schemas."""

from __future__ import annotations

import pytest

from server.schemas import (
    API_VERSION_PREFIX,
    CODE_MISSING_FIELD,
    ApiError,
    ApprovalDecisionRequest,
    ChatRequest,
    ChatStreamEvent,
    MemoryDeleteRequest,
    MemoryEntry,
    MemoryGetResponse,
    ModelInfo,
    ModelsActivateRequest,
    ModelsListResponse,
    PairingCompleteRequest,
    PairingCompleteResponse,
    PairingStartRequest,
    PairingStartResponse,
    SchemaValidationError,
    ScreenCaptureRequest,
    ScreenCaptureResponse,
    StatusResponse,
    TaskCancelRequest,
    TaskCreateRequest,
    TaskInfo,
    TaskListResponse,
)


def test_api_version_prefix() -> None:
    assert API_VERSION_PREFIX == "/v1"


def test_pairing_start_round_trip() -> None:
    original = PairingStartRequest(idempotency_key="idem-1")
    restored = PairingStartRequest.from_dict(original.to_dict())
    assert restored == original


def test_pairing_start_requires_idempotency_key() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        PairingStartRequest.from_dict({})
    assert exc_info.value.code == CODE_MISSING_FIELD
    assert exc_info.value.field == "idempotency_key"


def test_pairing_complete_requires_fields() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        PairingCompleteRequest.from_dict({"code": "123456"})
    assert exc_info.value.field in {"device_name", "idempotency_key"}

    ok = PairingCompleteRequest.from_dict(
        {
            "code": "123456",
            "device_name": "iPhone",
            "idempotency_key": "idem-2",
        }
    )
    assert ok.device_name == "iPhone"


def test_pairing_responses_round_trip() -> None:
    start = PairingStartResponse(
        code="123456",
        expires_at=1.0,
        qr_payload="mark-pair://local/123456",
    )
    assert PairingStartResponse.from_dict(start.to_dict()) == start

    complete = PairingCompleteResponse(
        device_id="dev_1",
        device_secret="once",
        expires_at=None,
    )
    restored = PairingCompleteResponse.from_dict(complete.to_dict())
    assert restored.device_id == "dev_1"
    assert restored.device_secret == "once"


def test_status_requires_online_and_paired() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        StatusResponse.from_dict({"online": True})
    assert exc_info.value.field == "paired"

    status = StatusResponse(online=True, paired=False, provider_id="local")
    assert StatusResponse.from_dict(status.to_dict()).paired is False


def test_chat_request_requires_message_and_idempotency() -> None:
    with pytest.raises(SchemaValidationError) as exc_info:
        ChatRequest.from_dict({"message": "hi"})
    assert exc_info.value.field == "idempotency_key"

    with pytest.raises(SchemaValidationError) as exc_info:
        ChatRequest.from_dict({"idempotency_key": "k"})
    assert exc_info.value.field == "message"

    chat = ChatRequest(message="hi", idempotency_key="k", conversation_id="c1")
    assert ChatRequest.from_dict(chat.to_dict()) == chat


def test_chat_stream_event_round_trip() -> None:
    event = ChatStreamEvent(
        event="approval_required",
        conversation_id="c1",
        approval_id="a1",
        approval_required=True,
        error=ApiError(code="approval_required", message="needs approval"),
    )
    restored = ChatStreamEvent.from_dict(event.to_dict())
    assert restored.event == "approval_required"
    assert restored.approval_required is True
    assert restored.error is not None
    assert restored.error.code == "approval_required"


def test_tasks_schemas() -> None:
    create = TaskCreateRequest(prompt="do thing", idempotency_key="t1")
    assert TaskCreateRequest.from_dict(create.to_dict()) == create

    with pytest.raises(SchemaValidationError):
        TaskCreateRequest.from_dict({"prompt": "x"})

    cancel = TaskCancelRequest(idempotency_key="c1")
    assert TaskCancelRequest.from_dict(cancel.to_dict()) == cancel

    listed = TaskListResponse(
        tasks=(TaskInfo(id="1", status="pending", approval_required=True),)
    )
    assert TaskListResponse.from_dict(listed.to_dict()).tasks[0].id == "1"


def test_approvals_and_models_and_screen_and_memory() -> None:
    decision = ApprovalDecisionRequest(decision="allow", idempotency_key="d1")
    assert ApprovalDecisionRequest.from_dict(decision.to_dict()) == decision

    models = ModelsListResponse(
        models=(ModelInfo(id="m1", provider_id="local", active=True),)
    )
    assert ModelsListResponse.from_dict(models.to_dict()).models[0].id == "m1"

    activate = ModelsActivateRequest(model_id="m1", idempotency_key="a1", role="chat")
    assert ModelsActivateRequest.from_dict(activate.to_dict()) == activate

    capture_req = ScreenCaptureRequest(idempotency_key="s1")
    assert ScreenCaptureRequest.from_dict(capture_req.to_dict()) == capture_req

    capture = ScreenCaptureResponse(
        width=100,
        height=80,
        mime_type="image/png",
        capture_id="cap1",
        approval_required=True,
    )
    assert ScreenCaptureResponse.from_dict(capture.to_dict()) == capture

    memory = MemoryGetResponse(
        entries=(MemoryEntry(id="mem1", kind="note", summary="hello"),)
    )
    assert MemoryGetResponse.from_dict(memory.to_dict()).entries[0].id == "mem1"

    delete = MemoryDeleteRequest(idempotency_key="del1")
    assert MemoryDeleteRequest.from_dict(delete.to_dict()) == delete


def test_api_error_envelope_has_no_secret_fields() -> None:
    err = ApiError.of("unauthorized")
    payload = err.to_dict()
    assert set(payload.keys()) == {"code", "message"}
    assert "api_key" not in payload
    assert "sk-" not in err.message
