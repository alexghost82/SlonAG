"""Versioned Desktop Control API request/response schemas.

Contracts only — no sockets, no crypto, no tool execution.
Messages and error envelopes never carry API keys or raw key material.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from typing import Mapping

API_VERSION_PREFIX = "/v1"

CODE_OK = "ok"
CODE_INVALID_REQUEST = "invalid_request"
CODE_MISSING_FIELD = "missing_field"
CODE_INVALID_TYPE = "invalid_type"
CODE_UNAUTHORIZED = "unauthorized"
CODE_NOT_FOUND = "not_found"
CODE_APPROVAL_REQUIRED = "approval_required"
CODE_IDEMPOTENCY_CONFLICT = "idempotency_conflict"

ERROR_CODES = frozenset(
    {
        CODE_OK,
        CODE_INVALID_REQUEST,
        CODE_MISSING_FIELD,
        CODE_INVALID_TYPE,
        CODE_UNAUTHORIZED,
        CODE_NOT_FOUND,
        CODE_APPROVAL_REQUIRED,
        CODE_IDEMPOTENCY_CONFLICT,
    }
)

_SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "gemini_api_key",
        "openai_api_key",
        "openrouter_api_key",
        "raw_key",
        "secret_key",
    }
)

# Map API error codes to i18n keys.
_ERROR_KEYS: dict[str, str] = {
    CODE_OK: "api.ok",
    CODE_INVALID_REQUEST: "api.invalid_request",
    CODE_MISSING_FIELD: "api.missing_field",
    CODE_INVALID_TYPE: "api.invalid_type",
    CODE_UNAUTHORIZED: "api.unauthorized",
    CODE_NOT_FOUND: "api.not_found",
    CODE_APPROVAL_REQUIRED: "api.approval_required",
    CODE_IDEMPOTENCY_CONFLICT: "api.idempotency_conflict",
}

_UNKNOWN_KEY = "api.unknown"


def api_message(code: str) -> str:
    """Return a secret-free explanation for a structured API error code.

    Uses the catalog-backed translator (``tr``) so messages adapt
    to the active locale.  Falls back to English if a key is missing.
    """
    from localization.translator import tr, MissingTranslationError

    key = _ERROR_KEYS.get(code, _UNKNOWN_KEY)
    try:
        return tr(key)
    except MissingTranslationError:
        # Fallback: return a simple English string so the server never
        # breaks even if the i18n catalog is incomplete.
        return _MESSAGES.get(code, "Desktop Control API rejected the request.")


class SchemaValidationError(Exception):
    """Schema parse/validation failure. Messages never echo secret values."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        field: str | None = None,
    ) -> None:
        self.code = code
        self.field = field
        super().__init__(message if message is not None else api_message(code))


@dataclass(frozen=True)
class ApiError:
    """Common error envelope: structured code + human message, no secrets."""

    code: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ApiError:
        payload = _require_mapping(data)
        code = _require_str(payload, "code")
        message = _require_str(payload, "message")
        return cls(code=code, message=message)

    @classmethod
    def of(cls, code: str, message: str | None = None) -> ApiError:
        return cls(code=code, message=message if message is not None else api_message(code))


# --- Pairing -----------------------------------------------------------------


@dataclass(frozen=True)
class PairingStartRequest:
    """POST /v1/pairing/start — begin a one-time pairing challenge."""

    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PairingStartRequest:
        payload = _require_mapping(data)
        return cls(idempotency_key=_require_str(payload, "idempotency_key"))


@dataclass(frozen=True)
class PairingStartResponse:
    """One-time code + QR payload string (not an image)."""

    code: str
    expires_at: float
    qr_payload: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PairingStartResponse:
        payload = _require_mapping(data)
        return cls(
            code=_require_str(payload, "code"),
            expires_at=_require_float(payload, "expires_at"),
            qr_payload=_require_str(payload, "qr_payload"),
        )


@dataclass(frozen=True)
class PairingCompleteRequest:
    """POST /v1/pairing/complete — exchange code for a device credential."""

    code: str
    device_name: str
    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PairingCompleteRequest:
        payload = _require_mapping(data)
        return cls(
            code=_require_str(payload, "code"),
            device_name=_require_str(payload, "device_name"),
            idempotency_key=_require_str(payload, "idempotency_key"),
        )


@dataclass(frozen=True)
class PairingCompleteResponse:
    """Per-device credential issued once. Never includes AI provider API keys."""

    device_id: str
    device_secret: str
    expires_at: float | None = None

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PairingCompleteResponse:
        payload = _require_mapping(data)
        expires_raw = payload.get("expires_at")
        expires_at: float | None
        if expires_raw is None:
            expires_at = None
        elif isinstance(expires_raw, bool):
            raise SchemaValidationError(
                CODE_INVALID_TYPE,
                "Field 'expires_at' must be a number or null.",
                field="expires_at",
            )
        elif isinstance(expires_raw, (int, float)):
            expires_at = float(expires_raw)
        else:
            raise SchemaValidationError(
                CODE_INVALID_TYPE,
                "Field 'expires_at' must be a number or null.",
                field="expires_at",
            )
        return cls(
            device_id=_require_str(payload, "device_id"),
            device_secret=_require_str(payload, "device_secret"),
            expires_at=expires_at,
        )


# --- Status ------------------------------------------------------------------


@dataclass(frozen=True)
class StatusResponse:
    """GET /v1/status — desktop health without secrets."""

    online: bool
    paired: bool
    provider_id: str | None = None
    model_id: str | None = None
    network_mode: str | None = None
    privacy_profile: str | None = None
    active_tasks: int = 0
    pending_approvals: int = 0

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> StatusResponse:
        payload = _require_mapping(data)
        return cls(
            online=_require_bool(payload, "online"),
            paired=_require_bool(payload, "paired"),
            provider_id=_optional_str(payload, "provider_id"),
            model_id=_optional_str(payload, "model_id"),
            network_mode=_optional_str(payload, "network_mode"),
            privacy_profile=_optional_str(payload, "privacy_profile"),
            active_tasks=_optional_int(payload, "active_tasks", default=0),
            pending_approvals=_optional_int(payload, "pending_approvals", default=0),
        )


# --- Chat --------------------------------------------------------------------


@dataclass(frozen=True)
class ChatRequest:
    """POST /v1/chat — mutating; requires idempotency_key."""

    message: str
    idempotency_key: str
    conversation_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ChatRequest:
        payload = _require_mapping(data)
        return cls(
            message=_require_str(payload, "message"),
            idempotency_key=_require_str(payload, "idempotency_key"),
            conversation_id=_optional_str(payload, "conversation_id"),
        )


@dataclass(frozen=True)
class ChatStreamEvent:
    """One streamed chat event (delta / done / approval_required / error)."""

    event: str
    conversation_id: str | None = None
    delta: str | None = None
    approval_id: str | None = None
    approval_required: bool = False
    error: ApiError | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "event": self.event,
            "approval_required": self.approval_required,
        }
        if self.conversation_id is not None:
            payload["conversation_id"] = self.conversation_id
        if self.delta is not None:
            payload["delta"] = self.delta
        if self.approval_id is not None:
            payload["approval_id"] = self.approval_id
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ChatStreamEvent:
        payload = _require_mapping(data)
        error_raw = payload.get("error")
        error: ApiError | None
        if error_raw is None:
            error = None
        elif isinstance(error_raw, Mapping):
            error = ApiError.from_dict(error_raw)
        else:
            raise SchemaValidationError(
                CODE_INVALID_TYPE,
                "Field 'error' must be an object or null.",
                field="error",
            )
        return cls(
            event=_require_str(payload, "event"),
            conversation_id=_optional_str(payload, "conversation_id"),
            delta=_optional_str(payload, "delta"),
            approval_id=_optional_str(payload, "approval_id"),
            approval_required=_optional_bool(payload, "approval_required", default=False),
            error=error,
        )


# --- Tasks -------------------------------------------------------------------


@dataclass(frozen=True)
class TaskCreateRequest:
    """POST /v1/tasks — mutating; requires idempotency_key."""

    prompt: str
    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TaskCreateRequest:
        payload = _require_mapping(data)
        return cls(
            prompt=_require_str(payload, "prompt"),
            idempotency_key=_require_str(payload, "idempotency_key"),
        )


@dataclass(frozen=True)
class TaskInfo:
    """One task row for list/create/cancel responses."""

    id: str
    status: str
    prompt: str | None = None
    approval_required: bool = False

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TaskInfo:
        payload = _require_mapping(data)
        return cls(
            id=_require_str(payload, "id"),
            status=_require_str(payload, "status"),
            prompt=_optional_str(payload, "prompt"),
            approval_required=_optional_bool(payload, "approval_required", default=False),
        )


@dataclass(frozen=True)
class TaskListResponse:
    """GET /v1/tasks."""

    tasks: tuple[TaskInfo, ...]

    def to_dict(self) -> dict[str, object]:
        return {"tasks": [task.to_dict() for task in self.tasks]}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TaskListResponse:
        payload = _require_mapping(data)
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list):
            raise SchemaValidationError(
                CODE_INVALID_TYPE,
                "Field 'tasks' must be a list.",
                field="tasks",
            )
        tasks: list[TaskInfo] = []
        for item in raw_tasks:
            if not isinstance(item, Mapping):
                raise SchemaValidationError(
                    CODE_INVALID_TYPE,
                    "Each task must be an object.",
                    field="tasks",
                )
            tasks.append(TaskInfo.from_dict(item))
        return cls(tasks=tuple(tasks))


@dataclass(frozen=True)
class TaskCancelRequest:
    """POST /v1/tasks/{id}/cancel — mutating; requires idempotency_key."""

    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TaskCancelRequest:
        payload = _require_mapping(data)
        return cls(idempotency_key=_require_str(payload, "idempotency_key"))


# --- Approvals ---------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalInfo:
    """One pending or decided approval."""

    id: str
    tool_name: str
    risk: str
    status: str
    source: str | None = None
    intent: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ApprovalInfo:
        payload = _require_mapping(data)
        return cls(
            id=_require_str(payload, "id"),
            tool_name=_require_str(payload, "tool_name"),
            risk=_require_str(payload, "risk"),
            status=_require_str(payload, "status"),
            source=_optional_str(payload, "source"),
            intent=_optional_str(payload, "intent"),
        )


@dataclass(frozen=True)
class ApprovalListResponse:
    """GET /v1/approvals."""

    approvals: tuple[ApprovalInfo, ...]

    def to_dict(self) -> dict[str, object]:
        return {"approvals": [item.to_dict() for item in self.approvals]}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ApprovalListResponse:
        payload = _require_mapping(data)
        raw = payload.get("approvals")
        if not isinstance(raw, list):
            raise SchemaValidationError(
                CODE_INVALID_TYPE,
                "Field 'approvals' must be a list.",
                field="approvals",
            )
        approvals: list[ApprovalInfo] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise SchemaValidationError(
                    CODE_INVALID_TYPE,
                    "Each approval must be an object.",
                    field="approvals",
                )
            approvals.append(ApprovalInfo.from_dict(item))
        return cls(approvals=tuple(approvals))


@dataclass(frozen=True)
class ApprovalDecisionRequest:
    """POST /v1/approvals/{id}/decision — mutating; requires idempotency_key."""

    decision: str
    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ApprovalDecisionRequest:
        payload = _require_mapping(data)
        return cls(
            decision=_require_str(payload, "decision"),
            idempotency_key=_require_str(payload, "idempotency_key"),
        )


# --- Models ------------------------------------------------------------------


@dataclass(frozen=True)
class ModelInfo:
    """One model entry for list/activate."""

    id: str
    provider_id: str
    display_name: str | None = None
    active: bool = False

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ModelInfo:
        payload = _require_mapping(data)
        return cls(
            id=_require_str(payload, "id"),
            provider_id=_require_str(payload, "provider_id"),
            display_name=_optional_str(payload, "display_name"),
            active=_optional_bool(payload, "active", default=False),
        )


@dataclass(frozen=True)
class ModelsListResponse:
    """GET /v1/models."""

    models: tuple[ModelInfo, ...]

    def to_dict(self) -> dict[str, object]:
        return {"models": [model.to_dict() for model in self.models]}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ModelsListResponse:
        payload = _require_mapping(data)
        raw = payload.get("models")
        if not isinstance(raw, list):
            raise SchemaValidationError(
                CODE_INVALID_TYPE,
                "Field 'models' must be a list.",
                field="models",
            )
        models: list[ModelInfo] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise SchemaValidationError(
                    CODE_INVALID_TYPE,
                    "Each model must be an object.",
                    field="models",
                )
            models.append(ModelInfo.from_dict(item))
        return cls(models=tuple(models))


@dataclass(frozen=True)
class ModelsActivateRequest:
    """POST /v1/models/activate — mutating; requires idempotency_key."""

    model_id: str
    idempotency_key: str
    role: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ModelsActivateRequest:
        payload = _require_mapping(data)
        return cls(
            model_id=_require_str(payload, "model_id"),
            idempotency_key=_require_str(payload, "idempotency_key"),
            role=_optional_str(payload, "role"),
        )


# --- Screen ------------------------------------------------------------------


@dataclass(frozen=True)
class ScreenCaptureRequest:
    """POST /v1/screen/capture — mutating; requires idempotency_key."""

    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ScreenCaptureRequest:
        payload = _require_mapping(data)
        return cls(idempotency_key=_require_str(payload, "idempotency_key"))


@dataclass(frozen=True)
class ScreenCaptureResponse:
    """Mock capture metadata — no raw screenshot bytes required here."""

    width: int
    height: int
    mime_type: str
    capture_id: str
    approval_required: bool = False

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ScreenCaptureResponse:
        payload = _require_mapping(data)
        return cls(
            width=_require_int(payload, "width"),
            height=_require_int(payload, "height"),
            mime_type=_require_str(payload, "mime_type"),
            capture_id=_require_str(payload, "capture_id"),
            approval_required=_optional_bool(payload, "approval_required", default=False),
        )


# --- Memory ------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryEntry:
    """One memory record for GET /v1/memory."""

    id: str
    kind: str
    summary: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MemoryEntry:
        payload = _require_mapping(data)
        return cls(
            id=_require_str(payload, "id"),
            kind=_require_str(payload, "kind"),
            summary=_optional_str(payload, "summary"),
        )


@dataclass(frozen=True)
class MemoryGetResponse:
    """GET /v1/memory."""

    entries: tuple[MemoryEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {"entries": [entry.to_dict() for entry in self.entries]}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MemoryGetResponse:
        payload = _require_mapping(data)
        raw = payload.get("entries")
        if not isinstance(raw, list):
            raise SchemaValidationError(
                CODE_INVALID_TYPE,
                "Field 'entries' must be a list.",
                field="entries",
            )
        entries: list[MemoryEntry] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise SchemaValidationError(
                    CODE_INVALID_TYPE,
                    "Each memory entry must be an object.",
                    field="entries",
                )
            entries.append(MemoryEntry.from_dict(item))
        return cls(entries=tuple(entries))


@dataclass(frozen=True)
class MemoryDeleteRequest:
    """DELETE /v1/memory/{id} body — mutating; requires idempotency_key."""

    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return _public_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MemoryDeleteRequest:
        payload = _require_mapping(data)
        return cls(idempotency_key=_require_str(payload, "idempotency_key"))


# --- Helpers -----------------------------------------------------------------


def _require_mapping(data: Mapping[str, object] | object) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise SchemaValidationError(
            CODE_INVALID_REQUEST,
            "Request body must be an object.",
        )
    return data


def _require_str(payload: Mapping[str, object], field: str) -> str:
    if field not in payload:
        raise SchemaValidationError(
            CODE_MISSING_FIELD,
            f"Field '{field}' is required.",
            field=field,
        )
    value = payload[field]
    if not isinstance(value, str) or not value:
        raise SchemaValidationError(
            CODE_INVALID_TYPE,
            f"Field '{field}' must be a non-empty string.",
            field=field,
        )
    return value


def _optional_str(payload: Mapping[str, object], field: str) -> str | None:
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        raise SchemaValidationError(
            CODE_INVALID_TYPE,
            f"Field '{field}' must be a string or null.",
            field=field,
        )
    return value


def _require_bool(payload: Mapping[str, object], field: str) -> bool:
    if field not in payload:
        raise SchemaValidationError(
            CODE_MISSING_FIELD,
            f"Field '{field}' is required.",
            field=field,
        )
    value = payload[field]
    if not isinstance(value, bool):
        raise SchemaValidationError(
            CODE_INVALID_TYPE,
            f"Field '{field}' must be a boolean.",
            field=field,
        )
    return value


def _optional_bool(
    payload: Mapping[str, object],
    field: str,
    *,
    default: bool,
) -> bool:
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, bool):
        raise SchemaValidationError(
            CODE_INVALID_TYPE,
            f"Field '{field}' must be a boolean.",
            field=field,
        )
    return value


def _require_int(payload: Mapping[str, object], field: str) -> int:
    if field not in payload:
        raise SchemaValidationError(
            CODE_MISSING_FIELD,
            f"Field '{field}' is required.",
            field=field,
        )
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(
            CODE_INVALID_TYPE,
            f"Field '{field}' must be an integer.",
            field=field,
        )
    return value


def _optional_int(
    payload: Mapping[str, object],
    field: str,
    *,
    default: int,
) -> int:
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(
            CODE_INVALID_TYPE,
            f"Field '{field}' must be an integer.",
            field=field,
        )
    return value


def _require_float(payload: Mapping[str, object], field: str) -> float:
    if field not in payload:
        raise SchemaValidationError(
            CODE_MISSING_FIELD,
            f"Field '{field}' is required.",
            field=field,
        )
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(
            CODE_INVALID_TYPE,
            f"Field '{field}' must be a number.",
            field=field,
        )
    return float(value)


def _public_dict(obj: object) -> dict[str, object]:
    """Serialize a dataclass, dropping None and never emitting secret field names."""
    if not is_dataclass(obj) or isinstance(obj, type):
        raise TypeError("expected a dataclass instance")
    raw = asdict(obj)
    result: dict[str, object] = {}
    for key, value in raw.items():
        if key in _SECRET_FIELD_NAMES:
            continue
        if value is None:
            continue
        result[key] = value
    return result


def strip_secret_fields(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a shallow copy without known AI key field names."""
    return {k: v for k, v in payload.items() if k not in _SECRET_FIELD_NAMES}


def schema_field_names(cls: type[object]) -> frozenset[str]:
    """Return dataclass field names for introspection in tests."""
    return frozenset(f.name for f in fields(cls))  # type: ignore[arg-type]


__all__ = [
    "API_VERSION_PREFIX",
    "CODE_APPROVAL_REQUIRED",
    "CODE_IDEMPOTENCY_CONFLICT",
    "CODE_INVALID_REQUEST",
    "CODE_INVALID_TYPE",
    "CODE_MISSING_FIELD",
    "CODE_NOT_FOUND",
    "CODE_OK",
    "CODE_UNAUTHORIZED",
    "ERROR_CODES",
    "ApiError",
    "ApprovalDecisionRequest",
    "ApprovalInfo",
    "ApprovalListResponse",
    "ChatRequest",
    "ChatStreamEvent",
    "MemoryDeleteRequest",
    "MemoryEntry",
    "MemoryGetResponse",
    "ModelInfo",
    "ModelsActivateRequest",
    "ModelsListResponse",
    "PairingCompleteRequest",
    "PairingCompleteResponse",
    "PairingStartRequest",
    "PairingStartResponse",
    "SchemaValidationError",
    "ScreenCaptureRequest",
    "ScreenCaptureResponse",
    "StatusResponse",
    "TaskCancelRequest",
    "TaskCreateRequest",
    "TaskInfo",
    "TaskListResponse",
    "api_message",
    "schema_field_names",
    "strip_secret_fields",
]


# E2E test compatibility shims

@dataclass
class ChatRequestSchema:
    """Canonical request schema for server routes E2E tests."""
    session_id: str = ""
    messages: list[dict[str, str]] = None  # type: ignore[assignment]
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.messages is None:
            self.messages = []


@dataclass
class ChatResponseSchema:
    """Canonical response schema for server routes E2E tests."""
    status: str = "ok"
    session_id: str = ""
    response: str = ""
    tool_calls: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tool_calls is None:
            self.tool_calls = []


# Keep existing DataSanitizer
__all__ = [
    "API_VERSION_PREFIX",
    "CODE_OK",
    "CODE_INVALID_REQUEST",
    "CODE_MISSING_FIELD",
    "CODE_INVALID_TYPE",
    "CODE_UNAUTHORIZED",
    "CODE_NOT_FOUND",
    "CODE_APPROVAL_REQUIRED",
    "DataSanitizer",
    "ChatRequestSchema",
    "ChatResponseSchema",
]


# Additional E2E schemas
@dataclass
class SessionCreateSchema:
    """Schema for session creation in E2E tests."""
    session_id: str = ""
    agent_id: str = ""

@dataclass
class ToolResultSchema:
    """Schema for tool result in E2E tests."""
    tool_name: str = ""
    content: str = ""
