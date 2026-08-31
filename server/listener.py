"""Live Desktop Control API listener (stdlib HTTP/HTTPS).

Binds via ``server.bind_policy`` (loopback default; same-LAN only with
``allow_non_loopback=True``). Wires real pairing, auth, and route handlers.
Wildcards and public-internet binds are denied. Auth remains mandatory for
protected routes. Optional TLS via ``tls_certfile`` / ``tls_keyfile``.
"""

from __future__ import annotations

import base64
import asyncio
import binascii
import hashlib
import ipaddress
import json
import secrets
import ssl
import struct
import select
import threading
import time
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from acta.bridge.control_plane import ControlPlaneUnavailable
from server.auth import (
    AuthError,
    DeviceCredential as AuthDeviceCredential,
    TokenService,
)
from server.bind_policy import BindHostError, validate_bind_host
from server.pairing import (
    ExpiredPairingCodeError,
    InvalidPairingCodeError,
    PairingError,
    PairingService,
)
from server.routes import (
    ApprovalStore,
    ApprovalsHandler,
    ChatHandler,
    FilesHandler,
    IdempotencyStore,
    MemoryHandler,
    MemoryStore,
    RuntimeMemoryStore,
    ModelStore,
    ModelsHandler,
    ScreenHandler,
    TaskStore,
    TasksHandler,
    get_status,
    health_check,
)
from server.routes._common import DevicePrincipal as RoutePrincipal
from server.routes._common import RouteResponse
from server.schemas import (
    API_VERSION_PREFIX,
    CODE_MISSING_FIELD,
    CODE_INVALID_REQUEST,
    CODE_NOT_FOUND,
    CODE_UNAUTHORIZED,
    ApiError,
    ApprovalInfo,
    PairingCompleteRequest,
    PairingStartRequest,
    SchemaValidationError,
    strip_secret_fields,
)
from server.tls import TlsConfigError, build_server_ssl_context
from server.websocket import EventsHub, EventsUnauthorizedError

DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 8765
MAX_JSON_BODY_BYTES = 12 * 1024 * 1024


class _BodyTooLarge(ValueError):
    pass


class _MalformedBody(ValueError):
    pass


def _enumerate_files(path: str) -> list[dict[str, object]]:
    """Bounded, metadata-only directory listing after handler allowlist checks."""
    directory = Path(path).expanduser().resolve(strict=True)
    if not directory.is_dir():
        return []
    entries: list[dict[str, object]] = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        try:
            resolved = child.resolve(strict=True)
            entries.append(
                {
                    "name": child.name,
                    "path": str(resolved),
                    "is_directory": resolved.is_dir(),
                }
            )
        except (OSError, RuntimeError):
            continue
        if len(entries) >= 500:
            break
    return entries


class DesktopControlListener:
    """Threaded HTTP(S) listener for the versioned ``/v1/*`` Desktop Control API."""

    def __init__(
        self,
        *,
        bind_host: str = DEFAULT_BIND_HOST,
        allow_non_loopback: bool = False,
        bind_port: int = DEFAULT_BIND_PORT,
        signing_key: bytes | str | None = None,
        pairing: PairingService | None = None,
        tokens: TokenService | None = None,
        tls_certfile: str | Path | None = None,
        tls_keyfile: str | Path | None = None,
        require_tls: bool = False,
        advertise_bonjour: bool = False,
        control_plane: Any | None = None,
        memory_backend: Any | None = None,
        files_root: str | Path | None = None,
        gateway: Any | None = None,
        gateway_workspace_id: str = "desktop",
        cors_allowed_origins: list[str] = [],
    ) -> None:
        host = validate_bind_host(
            bind_host,
            allow_non_loopback=allow_non_loopback,
        )
        self.bind_host = host
        self.allow_non_loopback = bool(allow_non_loopback)
        self.bind_port = int(bind_port)
        self.require_tls = bool(require_tls)

        cert = Path(tls_certfile).expanduser() if tls_certfile is not None else None
        key = Path(tls_keyfile).expanduser() if tls_keyfile is not None else None
        if (cert is None) ^ (key is None):
            raise TlsConfigError("Pass both tls_certfile and tls_keyfile, or neither")
        if self.require_tls and (cert is None or key is None):
            raise TlsConfigError(
                "require_tls=True needs tls_certfile and tls_keyfile "
                "(generate via server.tls.ensure_tls_material)"
            )
        if not ipaddress.ip_address(self.bind_host).is_loopback and (
            cert is None or key is None
        ):
            raise TlsConfigError(
                "LAN control requires TLS certificate and key for pinned iOS transport."
            )
        self.tls_certfile = cert
        self.tls_keyfile = key
        self.tls_certificate_fingerprint: str | None = None
        self._ssl_context: ssl.SSLContext | None = None
        if cert is not None and key is not None:
            self._ssl_context = build_server_ssl_context(cert, key)
            pem = cert.read_text(encoding="utf-8")
            der = ssl.PEM_cert_to_DER_cert(pem)
            self.tls_certificate_fingerprint = hashlib.sha256(der).hexdigest()

        key_material = signing_key if signing_key is not None else secrets.token_bytes(32)
        self._pairing = pairing if pairing is not None else PairingService()
        revoked: set[str] = set()

        def _is_revoked(device_id: str) -> bool:
            if device_id in revoked:
                return True
            return not self._pairing.is_active(device_id)

        self._revoked = revoked
        self._tokens = (
            tokens
            if tokens is not None
            else TokenService(signing_key=key_material, is_revoked=_is_revoked)
        )
        self._idempotency = IdempotencyStore()
        self._tasks = TaskStore()
        self._approvals = ApprovalStore()
        self._models = ModelStore()
        self._memory = (
            RuntimeMemoryStore(memory_backend)
            if memory_backend is not None
            else MemoryStore()
        )
        self._chat = ChatHandler(idempotency=self._idempotency)
        self._task_handler = TasksHandler(
            store=self._tasks,
            idempotency=self._idempotency,
        )
        self._approval_handler = ApprovalsHandler(
            store=self._approvals,
            idempotency=self._idempotency,
        )
        self._models_handler = ModelsHandler(
            store=self._models,
            idempotency=self._idempotency,
        )
        self._pending_remote_tasks: dict[str, tuple[str, str]] = {}
        self._pending_tool_approvals: dict[str, tuple[threading.Event, list[bool]]] = {}
        self._task_runtime_ids: dict[str, str] = {}
        self._task_queue: Any | None = None
        self._memory_handler = MemoryHandler(
            store=self._memory,
            idempotency=self._idempotency,
        )
        self._screen = ScreenHandler(idempotency=self._idempotency)
        root = Path(files_root).expanduser().resolve() if files_root is not None else None
        self._files_root = str(root) if root is not None else None
        self._files = FilesHandler(
            allowlist=[str(root)] if root is not None else None,
            enumerator=_enumerate_files if root is not None else None,
        )
        self._events = EventsHub()
        self._gateway = gateway
        self._gateway_workspace_id = gateway_workspace_id
        self._control_plane = control_plane
        if self._control_plane is not None:
            try:
                self._control_plane.add_event_sink(self._publish_public_event)
                self._control_plane.bind_approval_handler(self._request_tool_approval)
            except Exception:
                self._control_plane = None
        self._bonjour: Any | None = None  # BonjourManager when advertising
        self._cors_allowed_origins: list[str] = list(cors_allowed_origins)
        self._advertise_bonjour = bool(advertise_bonjour)

        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def _publish_public_event(self, event: Mapping[str, object]) -> int:
        public = strip_secret_fields(dict(event))
        sequence = self._events.publish(public)
        if self._gateway is not None:
            try:
                self._gateway.publish_control_event(
                    public, workspace_id=self._gateway_workspace_id
                )
            except Exception:
                pass
        return sequence

    @property
    def tls_enabled(self) -> bool:
        return self._ssl_context is not None

    @property
    def scheme(self) -> str:
        return "https" if self.tls_enabled else "http"

    @property
    def listening(self) -> bool:
        with self._lock:
            return self._httpd is not None

    @property
    def address(self) -> tuple[str, int] | None:
        with self._lock:
            if self._httpd is None:
                return None
            host, port = self._httpd.server_address[:2]
            return str(host), int(port)

    def start(self) -> tuple[str, int]:
        """Bind and listen. Idempotent if already listening on the same config."""
        with self._lock:
            if self._httpd is not None:
                addr = self.address
                assert addr is not None
                return addr

            handler = _make_handler(self)
            httpd = ThreadingHTTPServer(
                (self.bind_host, self.bind_port),
                handler,
            )
            if self._ssl_context is not None:
                httpd.socket = self._ssl_context.wrap_socket(
                    httpd.socket,
                    server_side=True,
                )
            httpd.daemon_threads = True
            thread = threading.Thread(
                target=httpd.serve_forever,
                name="mark-desktop-control",
                daemon=True,
            )
            self._httpd = httpd
            self._thread = thread
            thread.start()
            host, port = httpd.server_address[:2]
            if self._advertise_bonjour:
                try:
                    from server.bonjour import BonjourManager

                    mgr = BonjourManager()
                    properties = {"tls": "1" if self.tls_enabled else "0"}
                    if self.tls_certificate_fingerprint is not None:
                        properties["fingerprint_sha256"] = (
                            self.tls_certificate_fingerprint
                        )
                    mgr.start(str(host), int(port), properties=properties)
                    self._bonjour = mgr
                except Exception:
                    self._bonjour = None
            if self._control_plane is not None:
                self._control_plane.update_state(desktop_api_active=True)
            return str(host), int(port)

    def stop(self, *, join_timeout: float = 2.0) -> None:
        """Stop accepting connections. Safe to call when not listening."""
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            bonjour = self._bonjour
            self._httpd = None
            self._thread = None
            self._bonjour = None
        if bonjour is not None:
            try:
                bonjour.stop()
            except Exception:
                pass
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
        if self._control_plane is not None:
            self._control_plane.update_state(desktop_api_active=False)

    def handle(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> RouteResponse:
        """In-process dispatch (same routes as the live socket)."""
        return self._dispatch(
            method=method,
            path=path,
            body=dict(body) if body is not None else {},
            headers={str(k).lower(): str(v) for k, v in (headers or {}).items()},
        )

    def _dispatch(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, object],
        headers: dict[str, str],
    ) -> RouteResponse:
        verb = method.upper().strip()
        route = _normalize_path(path)
        if not route.startswith(API_VERSION_PREFIX):
            return _error(404, CODE_NOT_FOUND, "Unknown API version or path.")

        if self._gateway is not None and route.startswith(f"{API_VERSION_PREFIX}/gateway/"):
            return self._gateway_dispatch(verb, route, body, headers)

        principal = self._optional_principal(headers)

        try:
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/pairing/start":
                return self._pairing_start(body)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/pairing/complete":
                return self._pairing_complete(body)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/auth/token":
                return self._auth_token(body)

            # Health endpoint — no auth required, must be before protected routes.
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/health":
                return health_check(
                    is_listening=self.listening,
                    tls_enabled=self.tls_enabled,
                    bind_host=self.bind_host,
                    bind_port=self.bind_port,
                )

            # Protected surface — require auth (pairing/token routes above exempt).
            if principal is None:
                return _error(401, CODE_UNAUTHORIZED)

            if verb == "GET" and route == f"{API_VERSION_PREFIX}/status":
                if self._control_plane is not None:
                    return RouteResponse(
                        status_code=200,
                        body=strip_secret_fields(self._control_plane.status_snapshot()),
                    )
                return get_status(principal=principal)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/pairing/revoke":
                return self._pairing_revoke(principal, body)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/runtime/control":
                return self._runtime_control(body)
            if verb in {"GET", "WS"} and route == f"{API_VERSION_PREFIX}/events":
                return self._events_subscribe(principal)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/chat":
                if self._control_plane is not None:
                    return self._runtime_chat(body)
                return self._chat.post(principal=principal, body=body)
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/tasks":
                if self._control_plane is not None:
                    return self._runtime_tasks_list(principal=principal)
                return self._task_handler.list_tasks(principal=principal)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/tasks":
                if self._control_plane is not None:
                    return self._runtime_task_create(principal=principal, body=body)
                return self._task_handler.create(principal=principal, body=body)
            cancel_prefix = f"{API_VERSION_PREFIX}/tasks/"
            if (
                verb == "POST"
                and route.startswith(cancel_prefix)
                and route.endswith("/cancel")
            ):
                task_id = unquote(route[len(cancel_prefix) : -len("/cancel")])
                if self._control_plane is not None:
                    return self._runtime_task_cancel(
                        principal=principal,
                        task_id=task_id,
                        body=body,
                    )
                return self._task_handler.cancel(
                    principal=principal,
                    task_id=task_id,
                    body=body,
                )
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/approvals":
                return self._approval_handler.list_approvals(principal=principal)
            decision_prefix = f"{API_VERSION_PREFIX}/approvals/"
            if (
                verb == "POST"
                and route.startswith(decision_prefix)
                and route.endswith("/decision")
            ):
                approval_id = unquote(
                    route[len(decision_prefix) : -len("/decision")]
                )
                if self._control_plane is not None:
                    return self._runtime_approval_decide(
                        principal=principal,
                        approval_id=approval_id,
                        body=body,
                    )
                return self._approval_handler.decide(
                    principal=principal,
                    approval_id=approval_id,
                    body=body,
                )
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/models":
                if self._control_plane is not None:
                    return self._runtime_models_list()
                return self._models_handler.list_models(principal=principal)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/models/activate":
                if self._control_plane is not None:
                    return self._runtime_model_activate(body)
                return self._models_handler.activate(principal=principal, body=body)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/screen/capture":
                return self._screen.capture(principal=principal, body=body)
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/screen/frame":
                return self._screen_frame(principal=principal)
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/memory":
                return self._memory_handler.get_memory(principal=principal)
            memory_prefix = f"{API_VERSION_PREFIX}/memory/"
            if verb == "DELETE" and route.startswith(memory_prefix):
                memory_id = unquote(route[len(memory_prefix) :])
                return self._memory_handler.delete(
                    principal=principal,
                    memory_id=memory_id,
                    body=body,
                )
            if verb == "GET" and route == f"{API_VERSION_PREFIX}/files":
                path_raw = body.get("path", "/")
                path = path_raw if isinstance(path_raw, str) else "/"
                if path == "/" and self._files_root is not None:
                    path = self._files_root
                return self._files.list_entries(principal=principal, path=path)
            if verb == "POST" and route == f"{API_VERSION_PREFIX}/files/upload":
                return self._file_upload(body)
        except SchemaValidationError as exc:
            return _error(400, exc.code, str(exc), field=exc.field)
        except AuthError as exc:
            return _error(401, exc.code, str(exc))
        except PairingError as exc:
            return _error(400, exc.code, str(exc))

        return _error(404, CODE_NOT_FOUND, "No handler for this route.")

    def _gateway_dispatch(
        self, verb: str, route: str, body: dict[str, object], headers: dict[str, str]
    ) -> RouteResponse:
        prefix = f"{API_VERSION_PREFIX}/gateway"
        try:
            if verb == "POST" and route == f"{prefix}/pairing/complete":
                required = ("code", "device_name", "public_key")
                if not all(isinstance(body.get(key), str) for key in required):
                    return _error(400, CODE_INVALID_REQUEST, "Invalid pairing payload.")
                device_id = self._gateway.auth.complete_pairing(
                    code=body["code"], device_name=body["device_name"],
                    public_key=body["public_key"],
                    workspace_id=self._gateway_workspace_id,
                )
                return RouteResponse(201, {"device_id": device_id})
            if verb == "POST" and route == f"{prefix}/auth/challenge":
                device_id = body.get("device_id")
                if not isinstance(device_id, str):
                    return _error(400, CODE_INVALID_REQUEST, "device_id is required.")
                challenge = self._gateway.auth.challenge(device_id)
                return RouteResponse(200, {
                    "device_id": challenge.device_id, "nonce": challenge.nonce,
                    "expires_at": challenge.expires_at,
                })
            if verb == "POST" and route == f"{prefix}/auth/proof":
                if not all(isinstance(body.get(key), str) for key in ("device_id", "nonce", "signature")):
                    return _error(400, CODE_INVALID_REQUEST, "Invalid device proof.")
                tokens = self._gateway.auth.exchange_proof(
                    device_id=body["device_id"], nonce=body["nonce"],
                    signature=body["signature"],
                )
                return RouteResponse(200, tokens.to_public_dict())
            if verb == "POST" and route == f"{prefix}/auth/refresh":
                token = body.get("refresh_token")
                if not isinstance(token, str):
                    return _error(400, CODE_INVALID_REQUEST, "refresh_token is required.")
                return RouteResponse(200, self._gateway.auth.refresh(token).to_public_dict())
            principal = self._gateway.auth.authenticate(headers)
            workspace = self._gateway.auth.workspace_for(principal.device_id)
            if verb == "GET" and route == f"{prefix}/devices":
                return RouteResponse(200, {"devices": [
                    {key: value for key, value in item.items() if key != "public_key"}
                    for item in self._gateway.auth.trusted_devices(workspace_id=workspace)
                ]})
            if verb == "POST" and route == f"{prefix}/devices/revoke":
                target = body.get("device_id")
                if not isinstance(target, str):
                    return _error(400, CODE_INVALID_REQUEST, "device_id is required.")
                record = self._gateway.store.device(target)
                if record is None or record["workspace_id"] != workspace:
                    return _error(404, CODE_NOT_FOUND)
                return RouteResponse(200, {"revoked": self._gateway.auth.revoke(target)})
        except Exception as exc:
            return _error(401, CODE_UNAUTHORIZED, f"Gateway request rejected ({type(exc).__name__}).")
        return _error(404, CODE_NOT_FOUND, "No Gateway handler for this route.")

    def _optional_principal(
        self,
        headers: Mapping[str, str],
    ) -> RoutePrincipal | None:
        auth = headers.get("authorization", "").strip()
        if not auth:
            return None
        try:
            auth_principal = self._tokens.authenticate(
                headers,
                consume_jti=False,
            )
        except AuthError:
            return None
        active = self._pairing.is_active(auth_principal.device_id)
        return RoutePrincipal(
            device_id=auth_principal.device_id,
            revoked=not active,
        )

    def _pairing_start(self, body: dict[str, object]) -> RouteResponse:
        import base64

        from server.qr import try_render_qr_png

        request = PairingStartRequest.from_dict(body)
        started = self._pairing.start()
        payload: dict[str, object] = {
            "code": started.code,
            "expires_at": started.expires_at,
            "qr_payload": started.qr_payload,
            "idempotency_key": request.idempotency_key,
        }
        png = try_render_qr_png(started.qr_payload)
        if png is not None:
            payload["qr_png_base64"] = base64.b64encode(png).decode("ascii")
        if self.tls_certificate_fingerprint is not None:
            payload["tls_certificate_sha256"] = self.tls_certificate_fingerprint
        return RouteResponse(
            status_code=200,
            body=strip_secret_fields(payload),
        )

    def _pairing_complete(self, body: dict[str, object]) -> RouteResponse:
        request = PairingCompleteRequest.from_dict(body)
        try:
            credential = self._pairing.complete(request.code, request.device_name)
        except ExpiredPairingCodeError as exc:
            return _error(400, exc.code, str(exc))
        except InvalidPairingCodeError as exc:
            return _error(400, exc.code, str(exc))
        return RouteResponse(
            status_code=200,
            body=strip_secret_fields(
                {
                    "device_id": credential.device_id,
                    "device_secret": credential.device_secret,
                }
            ),
        )

    def _pairing_revoke(
        self,
        principal: RoutePrincipal,
        body: dict[str, object],
    ) -> RouteResponse:
        idempotency_key = body.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'idempotency_key' is required.",
            )

        def _revoke() -> RouteResponse:
            self._pairing.revoke(principal.device_id)
            self._revoked.add(principal.device_id)
            return RouteResponse(status_code=200, body={"revoked": True})

        return self._idempotency.run(
            idempotency_key=idempotency_key,
            fingerprint={"device_id": principal.device_id},
            side_effect_key=f"pairing_revoke:{idempotency_key}",
            factory=_revoke,
        )

    def _auth_token(self, body: dict[str, object]) -> RouteResponse:
        device_id = body.get("device_id")
        device_secret = body.get("device_secret")
        if not isinstance(device_id, str) or not device_id:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'device_id' is required.",
                field="device_id",
            )
        if not isinstance(device_secret, str) or not device_secret:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'device_secret' is required.",
                field="device_secret",
            )
        if not self._pairing.verify_device_secret(device_id, device_secret):
            return _error(401, CODE_UNAUTHORIZED, "Invalid device credentials.")
        record = self._pairing.devices.get(device_id)
        name = record.device_name if record is not None else None
        issued = self._tokens.mint(
            AuthDeviceCredential(
                device_id=device_id,
                device_secret=device_secret,
                device_name=name,
            )
        )
        return RouteResponse(
            status_code=200,
            body=strip_secret_fields(issued.to_public_dict()),
        )

    def _events_subscribe(self, principal: RoutePrincipal) -> RouteResponse:
        try:
            sub = self._events.subscribe(principal=principal)
        except EventsUnauthorizedError as exc:
            return _error(401, CODE_UNAUTHORIZED, str(exc))
        events = sub.poll()
        return RouteResponse(
            status_code=200,
            body=strip_secret_fields(
                {
                    "subscribed": True,
                    "device_id": sub.device_id,
                    "events": events,
                }
            ),
        )

    def _runtime_control(self, body: dict[str, object]) -> RouteResponse:
        if self._control_plane is None:
            return _error(503, CODE_NOT_FOUND, "Desktop runtime is unavailable.")
        control_plane = self._control_plane
        action = body.get("action")
        idempotency_key = body.get("idempotency_key")
        allowed = {
            "start",
            "pause",
            "stop",
            "mute",
            "unmute",
            "toggle_tts",
            "listen_stt",
        }
        if not isinstance(action, str) or action not in allowed:
            return _error(
                400,
                CODE_INVALID_REQUEST,
                "Unsupported runtime action.",
                field="action",
            )
        if not isinstance(idempotency_key, str) or not idempotency_key:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'idempotency_key' is required.",
                field="idempotency_key",
            )

        def _perform() -> RouteResponse:
            try:
                control_plane.perform(action)
            except ControlPlaneUnavailable as exc:
                return _error(409, CODE_INVALID_REQUEST, str(exc))
            state = control_plane.status_snapshot().get(
                "assistant_state",
                "UNKNOWN",
            )
            return RouteResponse(
                status_code=200,
                body={"accepted": True, "state": str(state)},
            )

        return self._idempotency.run(
            idempotency_key=idempotency_key,
            fingerprint={"action": action},
            side_effect_key=f"runtime:{idempotency_key}",
            factory=_perform,
        )

    def _runtime_chat(self, body: dict[str, object]) -> RouteResponse:
        if self._control_plane is None:
            return _error(503, CODE_NOT_FOUND, "Desktop runtime is unavailable.")
        control_plane = self._control_plane
        message = body.get("message")
        idempotency_key = body.get("idempotency_key")
        conversation_id = body.get("conversation_id")
        if not isinstance(message, str) or not message.strip():
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'message' is required.",
                field="message",
            )
        if not isinstance(idempotency_key, str) or not idempotency_key:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'idempotency_key' is required.",
                field="idempotency_key",
            )
        if conversation_id is not None and not isinstance(conversation_id, str):
            return _error(
                400,
                CODE_INVALID_REQUEST,
                "Field 'conversation_id' must be a string.",
                field="conversation_id",
            )

        def _submit() -> RouteResponse:
            try:
                reply = control_plane.submit_text_and_wait(message, timeout=55.0)
            except ControlPlaneUnavailable as exc:
                return _error(409, CODE_INVALID_REQUEST, str(exc))
            if reply is None:
                return _error(
                    504,
                    "runtime_timeout",
                    "Desktop runtime did not complete the response in time.",
                )
            return RouteResponse(
                status_code=200,
                body={
                    "event": "delta",
                    "conversation_id": conversation_id or f"remote_{idempotency_key}",
                    "delta": reply,
                    "approval_required": False,
                },
            )

        return self._idempotency.run(
            idempotency_key=idempotency_key,
            fingerprint={
                "message": message,
                "conversation_id": conversation_id,
            },
            side_effect_key=f"chat:{idempotency_key}",
            factory=_submit,
        )

    def _runtime_task_create(
        self,
        *,
        principal: RoutePrincipal,
        body: dict[str, object],
    ) -> RouteResponse:
        request_body = dict(body)
        request_body["approval_required"] = True
        response = self._task_handler.create(principal=principal, body=request_body)
        if response.status_code not in {200, 201, 202}:
            return response
        task_id = response.body.get("id")
        prompt = response.body.get("prompt")
        if isinstance(task_id, str) and isinstance(prompt, str):
            approval_id = f"remote-task:{task_id}"
            if not any(
                item.id == approval_id for item in self._approvals.list_approvals()
            ):
                self._approvals.seed(
                    ApprovalInfo(
                        id=approval_id,
                        tool_name="agent_task",
                        risk="high",
                        status="pending",
                        source="remote_user",
                        intent=prompt,
                    )
                )
                self._pending_remote_tasks[approval_id] = (task_id, prompt)
        return response

    def _runtime_tasks_list(self, *, principal: RoutePrincipal) -> RouteResponse:
        if self._task_queue is not None:
            for task_id, runtime_id in tuple(self._task_runtime_ids.items()):
                runtime = self._task_queue.get_status(runtime_id)
                if runtime is not None:
                    self._tasks.set_status(
                        task_id,
                        str(runtime.get("status", "unknown")),
                        approval_required=False,
                    )
        return self._task_handler.list_tasks(principal=principal)

    def _runtime_task_cancel(
        self,
        *,
        principal: RoutePrincipal,
        task_id: str,
        body: dict[str, object],
    ) -> RouteResponse:
        runtime_id = self._task_runtime_ids.get(task_id)
        if runtime_id is not None and self._task_queue is not None:
            self._task_queue.cancel(runtime_id)
        response = self._task_handler.cancel(
            principal=principal,
            task_id=task_id,
            body=body,
        )
        if response.status_code == 200:
            self._tasks.set_status(task_id, "cancelled", approval_required=False)
            response = self._task_handler.list_tasks(principal=principal)
            raw_tasks = response.body.get("tasks")
            tasks = raw_tasks if isinstance(raw_tasks, list) else []
            task = next(
                (
                    item
                    for item in tasks
                    if isinstance(item, Mapping) and item.get("id") == task_id
                ),
                None,
            )
            return RouteResponse(status_code=200, body=dict(task) if task else {})
        return response

    def _runtime_approval_decide(
        self,
        *,
        principal: RoutePrincipal,
        approval_id: str,
        body: dict[str, object],
    ) -> RouteResponse:
        response = self._approval_handler.decide(
            principal=principal,
            approval_id=approval_id,
            body=body,
        )
        if response.status_code != 200:
            return response
        tool_waiter = self._pending_tool_approvals.pop(approval_id, None)
        decision = str(response.body.get("decision", "")).lower()
        if self._gateway is not None:
            try:
                workspace = self._gateway.auth.workspace_for(principal.device_id)
                durable = self._gateway.approvals.decide(
                    approval_id=approval_id, workspace_id=workspace,
                    allow=decision in {"approve", "allow"},
                    device_id=principal.device_id,
                )
                if durable:
                    return response
            except Exception:
                return _error(403, CODE_UNAUTHORIZED, "Approval decision rejected.")
        if tool_waiter is not None:
            event, result = tool_waiter
            result.append(decision in {"approve", "allow"})
            event.set()
            return response
        pending = self._pending_remote_tasks.pop(approval_id, None)
        if pending is None:
            return response
        task_id, prompt = pending
        if decision in {"approve", "allow"}:
            from agent.task_queue import get_queue

            self._task_queue = get_queue()
            runtime_id = self._task_queue.submit(prompt)
            self._task_runtime_ids[task_id] = runtime_id
            self._tasks.set_status(task_id, "pending", approval_required=False)
        else:
            self._tasks.set_status(task_id, "denied", approval_required=False)
        return response

    def _request_tool_approval(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        source: str,
        reason: str,
        tool_call_id: str | None = None,
    ) -> bool:
        durable_request = None
        if self._gateway is not None:
            durable_request = self._gateway.approvals.request(
                workspace_id=self._gateway_workspace_id, tool_name=tool_name,
                reason=reason, timeout=120.0,
                tool_call_id=tool_call_id,
            )
        approval_id = (
            durable_request.approval_id
            if durable_request is not None
            else f"tool:{secrets.token_urlsafe(12)}"
        )
        event = threading.Event()
        result: list[bool] = []
        safe_details = strip_secret_fields(
            {"reason": reason, "arguments": dict(arguments)}
        )
        if durable_request is None:
            self._pending_tool_approvals[approval_id] = (event, result)
        self._approvals.seed(
            ApprovalInfo(
                id=approval_id,
                tool_name=tool_name,
                risk="high",
                status="pending",
                source=source,
                intent=json.dumps(safe_details, ensure_ascii=False)[:2000],
            )
        )
        self._events.publish(
            {
                "event": "approval",
                "id": approval_id,
                "tool_name": tool_name,
                "risk": "high",
            }
        )
        if durable_request is not None:
            gateway = self._gateway
            if gateway is None:
                return False
            approved = gateway.approvals.wait(durable_request, timeout=120.0)
            self._approvals.decide(approval_id, "approve" if approved else "deny")
            return approved
        if not event.wait(timeout=120.0):
            self._pending_tool_approvals.pop(approval_id, None)
            self._approvals.decide(approval_id, "deny")
            return False
        return bool(result and result[0])

    def _runtime_models_list(self) -> RouteResponse:
        control_plane = self._control_plane
        if control_plane is None:
            return _error(503, CODE_NOT_FOUND, "Desktop runtime is unavailable.")
        snapshot = control_plane.status_snapshot()
        model_id = snapshot.get("model_id")
        provider_id = snapshot.get("provider_id", "unknown")
        models: list[dict[str, object]] = []
        if isinstance(model_id, str) and model_id:
            models.append(
                {
                    "id": model_id,
                    "provider_id": str(provider_id),
                    "display_name": model_id.rsplit("/", 1)[-1],
                    "active": True,
                }
            )
        return RouteResponse(status_code=200, body={"models": models})

    def _runtime_model_activate(self, body: dict[str, object]) -> RouteResponse:
        model_id = body.get("model_id")
        idempotency_key = body.get("idempotency_key")
        if not isinstance(model_id, str) or not model_id:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'model_id' is required.",
                field="model_id",
            )
        if not isinstance(idempotency_key, str) or not idempotency_key:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'idempotency_key' is required.",
                field="idempotency_key",
            )
        control_plane = self._control_plane
        if control_plane is None:
            return _error(503, CODE_NOT_FOUND, "Desktop runtime is unavailable.")
        snapshot = control_plane.status_snapshot()
        if snapshot.get("model_id") != model_id:
            return _error(
                409,
                CODE_INVALID_REQUEST,
                "The live desktop session cannot hot-swap to this model.",
                field="model_id",
            )
        return RouteResponse(
            status_code=200,
            body={
                "id": model_id,
                "provider_id": str(snapshot.get("provider_id", "unknown")),
                "display_name": model_id.rsplit("/", 1)[-1],
                "active": True,
            },
        )

    def _file_upload(self, body: dict[str, object]) -> RouteResponse:
        if self._files_root is None:
            return _error(403, CODE_UNAUTHORIZED, "File uploads are not enabled.")
        directory_raw = body.get("directory")
        filename = body.get("filename")
        encoded = body.get("content_base64")
        idempotency_key = body.get("idempotency_key")
        if not isinstance(directory_raw, str) or not directory_raw:
            return _error(400, CODE_MISSING_FIELD, "Field 'directory' is required.")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or filename in {".", ".."}
        ):
            return _error(400, CODE_INVALID_REQUEST, "Invalid upload filename.")
        if not isinstance(encoded, str) or not encoded:
            return _error(400, CODE_MISSING_FIELD, "Field 'content_base64' is required.")
        if len(encoded) > 14 * 1024 * 1024:
            return _error(413, CODE_INVALID_REQUEST, "Upload exceeds 10 MB.")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            return _error(
                400,
                CODE_MISSING_FIELD,
                "Field 'idempotency_key' is required.",
            )
        root = Path(self._files_root)
        try:
            directory = Path(directory_raw).expanduser().resolve(strict=True)
        except OSError:
            return _error(404, CODE_NOT_FOUND, "Upload directory not found.")
        if not directory.is_dir() or not directory.is_relative_to(root):
            return _error(403, CODE_UNAUTHORIZED, "Upload path is outside allowlist.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return _error(400, CODE_INVALID_REQUEST, "Invalid base64 upload data.")
        if len(content) > 10 * 1024 * 1024:
            return _error(413, CODE_INVALID_REQUEST, "Upload exceeds 10 MB.")

        def _write() -> RouteResponse:
            target = directory / filename
            try:
                with target.open("xb") as stream:
                    stream.write(content)
            except FileExistsError:
                return _error(409, CODE_INVALID_REQUEST, "File already exists.")
            return RouteResponse(
                status_code=201,
                body={
                    "entry": {
                        "name": filename,
                        "path": str(target),
                        "is_directory": False,
                    }
                },
            )

        return self._idempotency.run(
            idempotency_key=idempotency_key,
            fingerprint={
                "directory": str(directory),
                "filename": filename,
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            side_effect_key=f"file_upload:{idempotency_key}",
            factory=_write,
        )

    def _screen_frame(self, *, principal: RoutePrincipal) -> RouteResponse:
        from server.live_video import LiveVideoSource, ScreenGrabError

        if principal.revoked:
            return _error(403, CODE_UNAUTHORIZED, "Device credential has been revoked.")
        try:
            frame = LiveVideoSource(fps=1.0).grab_one()
        except ScreenGrabError as exc:
            return _error(503, CODE_NOT_FOUND, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error(503, CODE_NOT_FOUND, f"screen grab failed: {exc}")
        return RouteResponse(
            status_code=200,
            body={
                "width": frame.width,
                "height": frame.height,
                "seq": frame.seq,
                "mime_type": "image/jpeg",
            },
            raw_body=frame.jpeg,
            content_type="image/jpeg",
        )


def _make_handler(
    listener: DesktopControlListener,
) -> type[BaseHTTPRequestHandler]:
    class DesktopControlHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _read_json_body(self) -> dict[str, object]:
            length_raw = self.headers.get("Content-Length", "0")
            try:
                length = int(length_raw)
            except ValueError as exc:
                raise _MalformedBody from exc
            if length > MAX_JSON_BODY_BYTES:
                raise _BodyTooLarge
            if length < 0:
                raise _MalformedBody
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _MalformedBody from exc
            if isinstance(payload, dict):
                return dict(payload)
            return {}

        def _headers_map(self) -> dict[str, str]:
            return {str(k).lower(): str(v) for k, v in self.headers.items()}

        def _write_response(self, response: RouteResponse) -> None:
            if response.raw_body is not None:
                payload = response.raw_body
                ctype = response.content_type or "application/octet-stream"
                self.send_response(int(response.status_code))
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            payload = json.dumps(response.body, ensure_ascii=False).encode("utf-8")
            self.send_response(int(response.status_code))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            # CORS header — explicit whitelist, default deny.
            origin = self.headers.get("Origin", "")
            if origin and origin in listener._cors_allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if (
                listener._gateway is not None
                and parsed.path.rstrip("/") == f"{API_VERSION_PREFIX}/gateway/artifacts/download"
            ):
                self._gateway_artifact_download()
                return
            if (
                listener._gateway is not None
                and parsed.path.rstrip("/") == f"{API_VERSION_PREFIX}/gateway/ws"
                and self.headers.get("Upgrade", "").lower() == "websocket"
            ):
                self._stream_gateway(parsed.query)
                return
            if (
                parsed.path.rstrip("/") == f"{API_VERSION_PREFIX}/events"
                and self.headers.get("Upgrade", "").lower() == "websocket"
            ):
                self._stream_websocket_events()
                return
            # MJPEG live stream — long-lived; auth via Authorization header.
            if parsed.path.rstrip("/") == f"{API_VERSION_PREFIX}/screen/stream":
                self._stream_mjpeg()
                return
            body: dict[str, object] = {}
            query = parse_qs(parsed.query)
            if "path" in query and query["path"]:
                body["path"] = query["path"][0]
            response = listener.handle(
                "GET",
                parsed.path,
                body=body,
                headers=self._headers_map(),
            )
            self._write_response(response)

        def _stream_websocket_events(self) -> None:
            principal = listener._optional_principal(self._headers_map())
            if principal is None or principal.revoked:
                self._write_response(_error(401, CODE_UNAUTHORIZED))
                return
            key = self.headers.get("Sec-WebSocket-Key", "").strip()
            if not key:
                self._write_response(
                    _error(400, CODE_INVALID_REQUEST, "Missing WebSocket key.")
                )
                return
            accept = base64.b64encode(
                hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
                ).digest()
            ).decode("ascii")
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()

            subscription = listener._events.subscribe(principal=principal)
            try:
                if listener._control_plane is not None:
                    self._write_websocket_json(
                        {
                            "type": "status",
                            "payload": strip_secret_fields(
                                listener._control_plane.status_snapshot()
                            ),
                        }
                    )
                while listener.listening and not subscription.closed:
                    events = subscription.poll()
                    if not events:
                        time.sleep(0.1)
                        continue
                    for event in events:
                        self._write_websocket_json(event)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            finally:
                subscription.close()

        def _stream_gateway(self, query_text: str) -> None:
            from gateway.contracts import GatewayProtocolError
            from gateway.framing import decode_client_frame, encode_server_frame

            try:
                auth_headers = self._headers_map()
                principal = listener._gateway.auth.authenticate_connection(auth_headers)
            except Exception:
                self._write_response(_error(401, CODE_UNAUTHORIZED))
                return
            key = self.headers.get("Sec-WebSocket-Key", "").strip()
            if not key:
                self._write_response(_error(400, CODE_INVALID_REQUEST, "Missing WebSocket key."))
                return
            query = parse_qs(query_text)
            try:
                raw_cursor = query.get("cursor", [None])[0]
                cursor = None if raw_cursor is None else int(raw_cursor)
                if cursor is not None and cursor < 0:
                    raise ValueError
            except ValueError:
                self._write_response(_error(400, CODE_INVALID_REQUEST, "Invalid replay cursor."))
                return
            accept = base64.b64encode(
                hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
                ).digest()
            ).decode("ascii")
            try:
                connection = asyncio.run(listener._gateway.websocket.connect(
                    device_id=principal.device_id, after_sequence=cursor,
                    validate_auth=lambda: listener._gateway.auth.validate_connection(
                        auth_headers
                    ),
                ))
            except GatewayProtocolError:
                self._write_response(
                    _error(409, CODE_INVALID_REQUEST, "Replay rejected.")
                )
                return
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            try:
                while listener.listening and not connection.closed:
                    if connection.heartbeat():
                        self.connection.sendall(encode_server_frame(b"", opcode=0x9))
                    for item in connection.drain():
                        value = item.envelope.to_dict()
                        value["payload"] = {
                            **dict(item.envelope.payload),
                            "gateway_sequence": item.sequence,
                        }
                        self.connection.sendall(encode_server_frame(
                            json.dumps(value, ensure_ascii=False).encode("utf-8")
                        ))
                    readable, _, _ = select.select([self.connection], [], [], 0.1)
                    if not readable:
                        continue
                    raw = _read_websocket_frame_bytes(self.connection)
                    frame = decode_client_frame(raw)
                    if frame.opcode == 0x8:
                        break
                    if frame.opcode == 0x9:
                        self.connection.sendall(encode_server_frame(frame.payload, opcode=0xA))
                        continue
                    if frame.opcode == 0xA:
                        connection.last_pong_at = time.monotonic()
                        continue
                    response = asyncio.run(connection.receive(frame.payload))
                    self.connection.sendall(encode_server_frame(response.to_json()))
            except (BrokenPipeError, ConnectionResetError, OSError, GatewayProtocolError):
                return
            finally:
                connection.close()

        def _write_websocket_json(self, value: Mapping[str, object]) -> None:
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            header = bytearray([0x81])
            length = len(payload)
            if length < 126:
                header.append(length)
            elif length <= 0xFFFF:
                header.append(126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(127)
                header.extend(struct.pack("!Q", length))
            self.wfile.write(bytes(header) + payload)
            self.wfile.flush()

        def _stream_mjpeg(self) -> None:
            from server.live_video import LiveVideoSource, ScreenGrabError, mjpeg_bytes

            principal = listener._optional_principal(self._headers_map())
            if principal is None or principal.revoked:
                self._write_response(
                    _error(401, CODE_UNAUTHORIZED)
                )
                return
            try:
                source = LiveVideoSource(fps=2.0)
            except Exception as exc:  # noqa: BLE001
                self._write_response(
                    _error(503, CODE_NOT_FOUND, f"live video unavailable: {exc}")
                )
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame",
            )
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for frame in source.frames():
                    try:
                        self.wfile.write(mjpeg_bytes(frame))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
            except ScreenGrabError:
                return
            finally:
                source.stop()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if (
                listener._gateway is not None
                and parsed.path.rstrip("/") == f"{API_VERSION_PREFIX}/gateway/artifacts/upload"
            ):
                self._gateway_artifact_upload()
                return
            try:
                body = self._read_json_body()
            except _BodyTooLarge:
                self._write_response(_error(413, CODE_INVALID_REQUEST, "Request body is too large."))
                return
            except _MalformedBody:
                self._write_response(_error(400, CODE_INVALID_REQUEST, "Malformed JSON request."))
                return
            response = listener.handle(
                "POST",
                parsed.path,
                body=body,
                headers=self._headers_map(),
            )
            self._write_response(response)

        def _gateway_artifact_upload(self) -> None:
            from gateway.artifacts import DEFAULT_MAX_BYTES

            try:
                principal = listener._gateway.auth.authenticate(self._headers_map())
                workspace = listener._gateway.auth.workspace_for(principal.device_id)
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > DEFAULT_MAX_BYTES:
                    self._write_response(_error(413, CODE_INVALID_REQUEST, "Artifact is too large."))
                    return
                ticket = self.headers.get("X-Slon-Transfer-Ticket", "")
                mime = self.headers.get("Content-Type", "application/octet-stream")
                result = listener._gateway.artifacts.upload(
                    ticket=ticket, device_id=principal.device_id,
                    workspace_id=workspace, mime_type=mime,
                    data=self.rfile.read(length),
                )
                self._write_response(RouteResponse(201, result))
            except Exception as exc:
                self._write_response(_error(
                    403, CODE_UNAUTHORIZED,
                    f"Artifact upload rejected ({type(exc).__name__}).",
                ))

        def _gateway_artifact_download(self) -> None:
            try:
                principal = listener._gateway.auth.authenticate(self._headers_map())
                workspace = listener._gateway.auth.workspace_for(principal.device_id)
                ticket = self.headers.get("X-Slon-Transfer-Ticket", "")
                data, mime = listener._gateway.artifacts.download(
                    ticket=ticket, device_id=principal.device_id,
                    workspace_id=workspace,
                )
                self._write_response(RouteResponse(
                    status_code=200, body={}, raw_body=data, content_type=mime
                ))
            except Exception as exc:
                self._write_response(_error(
                    403, CODE_UNAUTHORIZED,
                    f"Artifact download rejected ({type(exc).__name__}).",
                ))

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = self._read_json_body()
            except _BodyTooLarge:
                self._write_response(_error(413, CODE_INVALID_REQUEST, "Request body is too large."))
                return
            except _MalformedBody:
                self._write_response(_error(400, CODE_INVALID_REQUEST, "Malformed JSON request."))
                return
            response = listener.handle(
                "DELETE",
                parsed.path,
                body=body,
                headers=self._headers_map(),
            )
            self._write_response(response)

        def do_OPTIONS(self) -> None:  # noqa: N802
            """Handle CORS preflight requests."""
            origin = self.headers.get("Origin", "")
            if origin and origin in listener._cors_allowed_origins:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.send_header("Access-Control-Max-Age", "86400")
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()

    return DesktopControlHTTPHandler


def _normalize_path(path: str) -> str:
    raw = path.strip() or "/"
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    if not raw.startswith("/"):
        raw = "/" + raw
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw.rstrip("/")
    return raw


def _read_websocket_frame_bytes(sock) -> bytes:
    """Read one client frame while rejecting its declared size before allocation."""
    from gateway.contracts import MAX_ENVELOPE_BYTES, GatewayProtocolError

    def exact(size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise ConnectionResetError
            chunks.extend(chunk)
        return bytes(chunks)

    header = exact(2)
    length_code = header[1] & 0x7F
    extended = b""
    if length_code == 126:
        extended = exact(2)
        length = struct.unpack("!H", extended)[0]
    elif length_code == 127:
        extended = exact(8)
        length = struct.unpack("!Q", extended)[0]
    else:
        length = length_code
    if length > MAX_ENVELOPE_BYTES:
        raise GatewayProtocolError("oversized_frame", "WebSocket frame is too large.")
    masked = bool(header[1] & 0x80)
    mask = exact(4) if masked else b""
    return header + extended + mask + exact(length)


def _error(
    status_code: int,
    code: str,
    message: str | None = None,
    *,
    field: str | None = None,
) -> RouteResponse:
    error = ApiError.of(code, message)
    body: dict[str, object] = {"error": error.to_dict()}
    if field is not None:
        body["field"] = field
    return RouteResponse(status_code=status_code, body=body)


__all__ = [
    "DEFAULT_BIND_HOST",
    "DEFAULT_BIND_PORT",
    "MAX_JSON_BODY_BYTES",
    "BindHostError",
    "DesktopControlListener",
]
