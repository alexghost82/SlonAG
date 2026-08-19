"""Loopback-default in-process Desktop Control API mock.

Bind policy lives in ``server.bind_policy``: loopback by default; same-LAN
private addresses require ``allow_non_loopback=True``; wildcards and public
internet binds are denied. Pairing/auth are unchanged by bind host.

This mock does not open listening sockets. For a real ``listen()``, use
``server.listener.DesktopControlListener`` (CLI: ``python -m server``).
TLS remains a separate hard requirement for non-lab deployments.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import unquote

from server.bind_policy import BindHostError, validate_bind_host
from server.schemas import (
    API_VERSION_PREFIX,
    CODE_APPROVAL_REQUIRED,
    CODE_MISSING_FIELD,
    CODE_NOT_FOUND,
    CODE_UNAUTHORIZED,
    ApiError,
    ApprovalDecisionRequest,
    ChatRequest,
    MemoryDeleteRequest,
    ModelsActivateRequest,
    PairingCompleteRequest,
    PairingStartRequest,
    SchemaValidationError,
    ScreenCaptureRequest,
    TaskCancelRequest,
    TaskCreateRequest,
    strip_secret_fields,
)


@dataclass(frozen=True)
class MockResponse:
    """In-process HTTP-like response. Body is always a JSON-serializable dict."""

    status_code: int
    body: dict[str, object]


class DesktopControlApp:
    """Headless mock dispatcher for the versioned ``/v1/*`` surface.

    ``bind_host`` is configuration only — this class never calls ``socket.bind``
    or ``listen``. Unit tests must not open real listening sockets.
    """

    def __init__(
        self,
        *,
        bind_host: str = "127.0.0.1",
        allow_non_loopback: bool = False,
        bind_port: int = 8765,
    ) -> None:
        # Policy: loopback default; same-LAN private IP only with explicit
        # allow_non_loopback=True. Wildcards and public binds denied.
        # Auth/pairing are unchanged by bind host (see docs/audit/lan-bind.md).
        host = validate_bind_host(
            bind_host,
            allow_non_loopback=allow_non_loopback,
        )
        self.bind_host = host
        self.allow_non_loopback = bool(allow_non_loopback)
        self.bind_port = int(bind_port)
        self._idempotency: dict[tuple[str, str, str], MockResponse] = {}
        self._side_effect_counts: dict[str, int] = {}

    @property
    def listening(self) -> bool:
        """Mock never opens a real socket."""
        return False

    def handle(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> MockResponse:
        """Dispatch one in-process request. Never listens on a network socket."""
        verb = method.upper().strip()
        route = _normalize_path(path)
        header_map = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        payload = dict(body) if body is not None else {}

        if not route.startswith(API_VERSION_PREFIX):
            return _error(404, CODE_NOT_FOUND, "Unknown API version or path.")

        if route in (f"{API_VERSION_PREFIX}/status", f"{API_VERSION_PREFIX}/events"):
            if not _is_authenticated(header_map):
                return _error(401, CODE_UNAUTHORIZED)

        try:
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/status":
                return self._status()
            if verb in {"GET", "WS"} and route == f"{API_VERSION_PREFIX}/events":
                return self._events()
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/pairing/start":
                return self._mutating(verb, route, payload, factory=self._pairing_start)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/pairing/complete":
                return self._mutating(
                    verb,
                    route,
                    payload,
                    factory=self._pairing_complete,
                )
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/chat":
                return self._mutating(verb, route, payload, factory=self._chat)
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/tasks":
                return self._tasks_list()
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/tasks":
                return self._mutating(verb, route, payload, factory=self._tasks_create)
            cancel_prefix = f"{API_VERSION_PREFIX}/tasks/"
            if (
                verb == "POST"
                and route.startswith(cancel_prefix)
                and route.endswith("/cancel")
            ):
                task_id = route[len(cancel_prefix) : -len("/cancel")]
                return self._mutating(
                    verb,
                    route,
                    payload,
                    factory=lambda p: self._tasks_cancel(task_id, p),
                )
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/approvals":
                return self._approvals_list()
            decision_prefix = f"{API_VERSION_PREFIX}/approvals/"
            if (
                verb == "POST"
                and route.startswith(decision_prefix)
                and route.endswith("/decision")
            ):
                approval_id = route[len(decision_prefix) : -len("/decision")]
                return self._mutating(
                    verb,
                    route,
                    payload,
                    factory=lambda p: self._approvals_decision(approval_id, p),
                )
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/models":
                return self._models_list()
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/models/activate":
                return self._mutating(
                    verb,
                    route,
                    payload,
                    factory=self._models_activate,
                )
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/screen/capture":
                return self._mutating(
                    verb,
                    route,
                    payload,
                    factory=self._screen_capture,
                )
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/memory":
                return self._memory_get()
            memory_prefix = f"{API_VERSION_PREFIX}/memory/"
            if verb == "DELETE" and route.startswith(memory_prefix):
                memory_id = route[len(memory_prefix) :]
                return self._mutating(
                    verb,
                    route,
                    payload,
                    factory=lambda p: self._memory_delete(memory_id, p),
                )
        except SchemaValidationError as exc:
            return _error(400, exc.code, str(exc), field=exc.field)

        return _error(404, CODE_NOT_FOUND, "No mock handler for this route.")

    def side_effect_count(self, key: str) -> int:
        """Test helper: how many times a mutating side effect ran for ``key``."""
        return self._side_effect_counts.get(key, 0)

    def _record_side_effect(self, key: str) -> None:
        self._side_effect_counts[key] = self._side_effect_counts.get(key, 0) + 1

    def _mutating(
        self,
        method: str,
        path: str,
        payload: dict[str, object],
        *,
        factory: Callable[[dict[str, object]], MockResponse],
    ) -> MockResponse:
        key_raw = payload.get("idempotency_key")
        if not isinstance(key_raw, str) or not key_raw:
            raise SchemaValidationError(
                CODE_MISSING_FIELD,
                "Field 'idempotency_key' is required.",
                field="idempotency_key",
            )
        cache_key = (method, path, key_raw)
        cached = self._idempotency.get(cache_key)
        if cached is not None:
            return MockResponse(status_code=cached.status_code, body=deepcopy(cached.body))

        response = factory(payload)
        sanitized = MockResponse(
            status_code=response.status_code,
            body=_sanitize_response_body(response.body),
        )
        self._idempotency[cache_key] = sanitized
        return MockResponse(
            status_code=sanitized.status_code,
            body=deepcopy(sanitized.body),
        )

    def _status(self) -> MockResponse:
        return MockResponse(
            status_code=200,
            body={
                "online": True,
                "paired": True,
                "provider_id": "local",
                "model_id": "mock-model",
                "network_mode": "offline",
                "privacy_profile": "fully_local",
                "active_tasks": 0,
                "pending_approvals": 0,
            },
        )

    def _events(self) -> MockResponse:
        return MockResponse(
            status_code=200,
            body={"subscribed": True, "events": []},
        )

    def _pairing_start(self, payload: dict[str, object]) -> MockResponse:
        request = PairingStartRequest.from_dict(payload)
        self._record_side_effect(f"pairing_start:{request.idempotency_key}")
        return MockResponse(
            status_code=200,
            body={
                "code": "123456",
                "expires_at": 1_700_000_000.0,
                "qr_payload": "mark-pair://local/123456",
            },
        )

    def _pairing_complete(self, payload: dict[str, object]) -> MockResponse:
        request = PairingCompleteRequest.from_dict(payload)
        self._record_side_effect(f"pairing_complete:{request.idempotency_key}")
        return MockResponse(
            status_code=200,
            body={
                "device_id": "dev_mock_1",
                "device_secret": "device-secret-once",
            },
        )

    def _chat(self, payload: dict[str, object]) -> MockResponse:
        request = ChatRequest.from_dict(payload)
        self._record_side_effect(f"chat:{request.idempotency_key}")
        return MockResponse(
            status_code=202,
            body={
                "event": "approval_required",
                "conversation_id": request.conversation_id or "conv_mock",
                "approval_id": "appr_chat_1",
                "approval_required": True,
                "status": CODE_APPROVAL_REQUIRED,
                "error": ApiError.of(CODE_APPROVAL_REQUIRED).to_dict(),
            },
        )

    def _tasks_list(self) -> MockResponse:
        return MockResponse(status_code=200, body={"tasks": []})

    def _tasks_create(self, payload: dict[str, object]) -> MockResponse:
        request = TaskCreateRequest.from_dict(payload)
        self._record_side_effect(f"tasks_create:{request.idempotency_key}")
        return MockResponse(
            status_code=202,
            body={
                "id": "task_mock_1",
                "status": CODE_APPROVAL_REQUIRED,
                "prompt": request.prompt,
                "approval_required": True,
            },
        )

    def _tasks_cancel(self, task_id: str, payload: dict[str, object]) -> MockResponse:
        request = TaskCancelRequest.from_dict(payload)
        self._record_side_effect(f"tasks_cancel:{request.idempotency_key}")
        return MockResponse(
            status_code=202,
            body={
                "id": unquote(task_id),
                "status": CODE_APPROVAL_REQUIRED,
                "approval_required": True,
            },
        )

    def _approvals_list(self) -> MockResponse:
        return MockResponse(status_code=200, body={"approvals": []})

    def _approvals_decision(
        self,
        approval_id: str,
        payload: dict[str, object],
    ) -> MockResponse:
        request = ApprovalDecisionRequest.from_dict(payload)
        self._record_side_effect(f"approvals_decision:{request.idempotency_key}")
        return MockResponse(
            status_code=202,
            body={
                "id": unquote(approval_id),
                "decision": request.decision,
                "status": CODE_APPROVAL_REQUIRED,
                "approval_required": True,
            },
        )

    def _models_list(self) -> MockResponse:
        return MockResponse(
            status_code=200,
            body={
                "models": [
                    {
                        "id": "mock-model",
                        "provider_id": "local",
                        "display_name": "Mock Local",
                        "active": True,
                    }
                ]
            },
        )

    def _models_activate(self, payload: dict[str, object]) -> MockResponse:
        request = ModelsActivateRequest.from_dict(payload)
        self._record_side_effect(f"models_activate:{request.idempotency_key}")
        body: dict[str, object] = {
            "model_id": request.model_id,
            "status": CODE_APPROVAL_REQUIRED,
            "approval_required": True,
        }
        if request.role is not None:
            body["role"] = request.role
        return MockResponse(status_code=202, body=body)

    def _screen_capture(self, payload: dict[str, object]) -> MockResponse:
        request = ScreenCaptureRequest.from_dict(payload)
        self._record_side_effect(f"screen_capture:{request.idempotency_key}")
        return MockResponse(
            status_code=202,
            body={
                "width": 1280,
                "height": 720,
                "mime_type": "image/png",
                "capture_id": "cap_mock_1",
                "approval_required": True,
                "status": CODE_APPROVAL_REQUIRED,
            },
        )

    def _memory_get(self) -> MockResponse:
        return MockResponse(status_code=200, body={"entries": []})

    def _memory_delete(self, memory_id: str, payload: dict[str, object]) -> MockResponse:
        request = MemoryDeleteRequest.from_dict(payload)
        self._record_side_effect(f"memory_delete:{request.idempotency_key}")
        return MockResponse(
            status_code=202,
            body={
                "id": unquote(memory_id),
                "deleted": False,
                "approval_required": True,
                "status": CODE_APPROVAL_REQUIRED,
            },
        )


MockDesktopApi = DesktopControlApp


def _is_authenticated(headers: Mapping[str, str]) -> bool:
    auth = headers.get("authorization", "").strip()
    if not auth:
        return False
    lower = auth.lower()
    if lower.startswith("bearer ") and auth[7:].strip():
        return True
    return bool(auth)


def _normalize_path(path: str) -> str:
    raw = path.strip() or "/"
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    if not raw.startswith("/"):
        raw = "/" + raw
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw.rstrip("/")
    return raw


def _sanitize_response_body(body: Mapping[str, object]) -> dict[str, object]:
    """Drop AI API key fields; never leak raw key material in mock responses."""
    return strip_secret_fields(body)


def _error(
    status_code: int,
    code: str,
    message: str | None = None,
    *,
    field: str | None = None,
) -> MockResponse:
    error = ApiError.of(code, message)
    body: dict[str, object] = {"error": error.to_dict()}
    if field is not None:
        body["field"] = field
    return MockResponse(status_code=status_code, body=body)


__all__ = [
    "BindHostError",
    "DesktopControlApp",
    "MockDesktopApi",
    "MockResponse",
]
