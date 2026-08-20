from __future__ import annotations

import asyncio
import base64
import os
import socket
import sqlite3
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gateway.artifacts import ArtifactTransferError, ArtifactTransferService
from gateway.auth import GatewayAuthError, GatewayAuthService
from gateway.contracts import (
    GatewayEnvelope,
    GatewayProtocolError,
    MAX_ENVELOPE_BYTES,
    utc_timestamp,
)
from gateway.framing import decode_client_frame, encode_server_frame
from gateway.router import (
    GatewayContext,
    GatewayRouter,
    bind_session_routes,
    response_envelope,
)
from gateway.service import SlonGateway
from gateway.store import GatewayStore, GatewayStoreError
from gateway.websocket import GatewayWebSocketRuntime
from sessions import ModelPolicy, SessionManager, SessionStore
from server.listener import DesktopControlListener
from server.__main__ import main as server_main


def _store(tmp_path: Path) -> GatewayStore:
    return GatewayStore(tmp_path / "gateway.sqlite3")


def _envelope(kind: str = "system.health", **payload) -> GatewayEnvelope:
    return GatewayEnvelope(
        id="event-1",
        type=kind,
        timestamp=utc_timestamp(),
        session_id=None,
        request_id="request-1",
        payload=payload,
    )


def _pair(auth: GatewayAuthService, private: Ed25519PrivateKey) -> str:
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    started = auth.start_pairing()
    return auth.complete_pairing(
        code=started.code,
        device_name="iPhone",
        public_key=base64.b64encode(public).decode(),
        workspace_id="workspace-a",
    )


def test_gateway_envelope_roundtrip_and_strict_validation() -> None:
    envelope = _envelope(value=1)
    assert GatewayEnvelope.from_json(envelope.to_json()) == envelope
    with pytest.raises(GatewayProtocolError, match="fields"):
        GatewayEnvelope.from_json(b'{"id":"x"}')
    with pytest.raises(GatewayProtocolError, match="too large"):
        GatewayEnvelope.from_json(b"x" * (MAX_ENVELOPE_BYTES + 1))
    with pytest.raises(GatewayProtocolError, match="unsupported"):
        _envelope("tool.execute")


def test_websocket_frame_codec_rejects_unmasked_malformed_and_oversized() -> None:
    payload = _envelope().to_json()
    mask = b"abcd"
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    frame = bytes([0x81, 0x80 | 126]) + len(payload).to_bytes(2, "big") + mask + masked
    assert decode_client_frame(frame).payload == payload
    assert encode_server_frame(payload).endswith(payload)
    with pytest.raises(GatewayProtocolError, match="masked"):
        decode_client_frame(bytes([0x81, 1]) + b"x")
    oversized = bytes([0x81, 0xFF]) + (MAX_ENVELOPE_BYTES + 1).to_bytes(8, "big")
    with pytest.raises(GatewayProtocolError, match="too large"):
        decode_client_frame(oversized)
    control = bytes([0x89, 0x80 | 126]) + (126).to_bytes(2, "big")
    with pytest.raises(GatewayProtocolError, match="control frame"):
        decode_client_frame(control)
    with pytest.raises(GatewayProtocolError, match="control frame"):
        encode_server_frame(b"x" * 126, opcode=0x9)


def test_pinned_pairing_proof_rotation_revocation_and_restart(tmp_path: Path) -> None:
    store = _store(tmp_path)
    auth = GatewayAuthService(store=store, signing_key=b"gateway-test-key")
    private = Ed25519PrivateKey.generate()
    device_id = _pair(auth, private)
    challenge = auth.challenge(device_id)
    signature = private.sign(challenge.nonce.encode())
    tokens = auth.exchange_proof(
        device_id=device_id,
        nonce=challenge.nonce,
        signature=base64.b64encode(signature).decode(),
    )
    assert (
        auth.authenticate({"Authorization": f"Bearer {tokens.access_token}"}).device_id
        == device_id
    )
    rotated = auth.refresh(tokens.refresh_token)
    with pytest.raises(Exception):
        auth.refresh(tokens.refresh_token)
    assert rotated.refresh_token != tokens.refresh_token
    assert auth.revoke(device_id)
    with pytest.raises(Exception):
        auth.authenticate({"Authorization": f"Bearer {rotated.access_token}"})
    store.close()
    reopened = _store(tmp_path)
    assert reopened.device(device_id)["active"] == 0


def test_pinned_key_mismatch_and_challenge_replay_fail_closed(tmp_path: Path) -> None:
    auth = GatewayAuthService(store=_store(tmp_path), signing_key=b"key")
    private = Ed25519PrivateKey.generate()
    device_id = _pair(auth, private)
    challenge = auth.challenge(device_id)
    bad = Ed25519PrivateKey.generate().sign(challenge.nonce.encode())
    with pytest.raises(GatewayAuthError, match="proof rejected"):
        auth.exchange_proof(
            device_id=device_id,
            nonce=challenge.nonce,
            signature=base64.b64encode(bad).decode(),
        )
    with pytest.raises(GatewayAuthError, match="already used"):
        auth.exchange_proof(
            device_id=device_id,
            nonce=challenge.nonce,
            signature=base64.b64encode(private.sign(challenge.nonce.encode())).decode(),
        )


def test_refresh_rotation_and_access_replay_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "durable.sqlite3"
    store = GatewayStore(path)
    auth = GatewayAuthService(store=store, signing_key=b"durable-key")
    private = Ed25519PrivateKey.generate()
    device_id = _pair(auth, private)
    challenge = auth.challenge(device_id)
    tokens = auth.exchange_proof(
        device_id=device_id, nonce=challenge.nonce,
        signature=base64.b64encode(private.sign(challenge.nonce.encode())).decode(),
    )
    headers = {"Authorization": f"Bearer {tokens.access_token}"}
    auth.authenticate_connection(headers)
    store.close()

    reopened = GatewayStore(path)
    restarted = GatewayAuthService(store=reopened, signing_key=b"durable-key")
    with pytest.raises(Exception, match="replayed"):
        restarted.authenticate_connection(headers)
    rotated = restarted.refresh(tokens.refresh_token)
    assert rotated.refresh_token != tokens.refresh_token
    with pytest.raises(Exception, match="rejected"):
        restarted.refresh(tokens.refresh_token)


def test_gateway_lan_cli_is_explicit_and_tls_only() -> None:
    assert server_main(["--gateway-lan"]) == 2
    assert server_main([
        "--gateway-lan", "--allow-non-loopback", "--host", "192.168.1.20"
    ]) == 2
    assert server_main(["--gateway-pair"]) == 2


@pytest.mark.asyncio
async def test_gateway_exposes_factual_node_and_automation_inventory(tmp_path: Path) -> None:
    gateway = SlonGateway(
        database_path=tmp_path / "routes.sqlite3",
        artifact_root=tmp_path / "artifacts",
        signing_key=b"route-key",
    )
    context = GatewayContext("device", "workspace", "connection")
    nodes = await gateway.router.dispatch(context, _envelope("node.list"))
    automations = await gateway.router.dispatch(context, _envelope("automation.list"))
    assert nodes.payload == {
        "nodes": [{"id": "local-runtime", "kind": "desktop", "online": True}]
    }
    assert automations.payload == {"automations": []}
    gateway.close()


@pytest.mark.asyncio
async def test_websocket_replay_cursor_ping_and_workspace_isolation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    for device, workspace in (("a", "wa"), ("b", "wb")):
        store.trust_device(
            device_id=device,
            device_name=device,
            public_key=base64.b64encode(b"x" * 32).decode(),
            key_fingerprint=device,
            workspace_id=workspace,
            created_at=time.time(),
        )
    router = GatewayRouter()
    runtime = GatewayWebSocketRuntime(
        store=store,
        router=router,
        is_active=lambda value: bool(store.device(value)["active"]),
        workspace_for=lambda value: str(store.device(value)["workspace_id"]),
    )
    event = _envelope("system.runtime_event", state="thinking")
    sequence = await runtime.publish("wa", event)
    a = await runtime.connect(device_id="a", after_sequence=0)
    b = await runtime.connect(device_id="b", after_sequence=0)
    assert [(item.sequence, item.envelope) for item in a.drain()] == [(sequence, event)]
    assert b.drain() == []
    pong = await a.receive(_envelope("system.ping").to_json())
    assert pong.type == "system.pong"
    ack = GatewayEnvelope(
        "ack",
        "system.ack",
        utc_timestamp(),
        None,
        "ack-request",
        {"sequence": sequence},
    )
    await a.receive(ack.to_json())
    assert store.cursor("a", "events") == sequence
    with pytest.raises(GatewayProtocolError, match="not delivered"):
        await a.receive(GatewayEnvelope(
            "future", "system.ack", utc_timestamp(), None, "future-request",
            {"sequence": sequence + 1},
        ).to_json())
    connection_id = a.context.connection_id
    a.close()
    assert connection_id not in runtime._connections


@pytest.mark.asyncio
async def test_slow_websocket_consumer_is_closed_not_dropped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.trust_device(
        device_id="a",
        device_name="a",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="a",
        workspace_id="wa",
        created_at=time.time(),
    )
    store.trust_device(
        device_id="b",
        device_name="b",
        public_key=base64.b64encode(b"y" * 32).decode(),
        key_fingerprint="b",
        workspace_id="wa",
        created_at=time.time(),
    )
    runtime = GatewayWebSocketRuntime(
        store=store,
        router=GatewayRouter(),
        is_active=lambda _device: True,
        workspace_for=lambda _device: "wa",
        max_pending=1,
    )
    connection = await runtime.connect(device_id="a")
    healthy = await runtime.connect(device_id="b")
    await runtime.publish("wa", _envelope("system.runtime_event", n=1))
    assert len(healthy.drain()) == 1
    await runtime.publish("wa", _envelope("system.runtime_event", n=2))
    assert connection.closed
    assert len(healthy.drain()) == 1


@pytest.mark.asyncio
async def test_replay_log_is_bounded_and_reports_expired_cursor(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "bounded.sqlite3", event_retention=2)
    store.trust_device(
        device_id="a",
        device_name="a",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="a",
        workspace_id="wa",
        created_at=time.time(),
    )
    runtime = GatewayWebSocketRuntime(
        store=store,
        router=GatewayRouter(),
        is_active=lambda _device: True,
        workspace_for=lambda _device: "wa",
    )
    for number in range(4):
        await runtime.publish("wa", _envelope("system.runtime_event", n=number))
    assert len(store.events_after(workspace_id="wa", sequence=0, limit=10)) == 2
    with pytest.raises(GatewayProtocolError) as caught:
        await runtime.connect(device_id="a", after_sequence=1)
    assert caught.value.code == "replay_gap"


@pytest.mark.asyncio
async def test_revocation_invalidates_existing_connection(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.trust_device(
        device_id="a",
        device_name="a",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="a",
        workspace_id="wa",
        created_at=time.time(),
    )
    runtime = GatewayWebSocketRuntime(
        store=store,
        router=GatewayRouter(),
        is_active=lambda device: bool(store.device(device)["active"]),
        workspace_for=lambda device: str(store.device(device)["workspace_id"]),
    )
    connection = await runtime.connect(device_id="a")
    store.revoke_device("a", revoked_at=time.time())
    with pytest.raises(GatewayProtocolError, match="trusted"):
        connection.drain()
    assert connection.closed


@pytest.mark.asyncio
async def test_gateway_heartbeat_pings_then_closes_stale_peer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.trust_device(
        device_id="a",
        device_name="a",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="a",
        workspace_id="wa",
        created_at=time.time(),
    )
    runtime = GatewayWebSocketRuntime(
        store=store,
        router=GatewayRouter(),
        is_active=lambda _device: True,
        workspace_for=lambda _device: "wa",
    )
    connection = await runtime.connect(device_id="a")
    start = connection.last_pong_at
    assert connection.heartbeat(now=start + 21)
    with pytest.raises(GatewayProtocolError, match="timed out"):
        connection.heartbeat(now=start + 61)
    assert connection.closed


@pytest.mark.asyncio
async def test_router_idempotency_is_device_and_workspace_scoped(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    router = GatewayRouter(idempotency_store=store)
    calls = 0

    async def handler(context, request):
        nonlocal calls
        calls += 1
        return response_envelope(request, "agent.accepted", {"calls": calls})

    router.register("agent.run", handler)
    request = _envelope("agent.run")
    context = GatewayContext("device", "workspace", "connection")
    first = await router.dispatch(context, request)
    second = await router.dispatch(context, request)
    assert first.to_dict() == second.to_dict()
    assert calls == 1


def test_session_routes_enforce_server_owned_workspace(tmp_path: Path) -> None:
    sessions = SessionManager(SessionStore(tmp_path / "sessions.sqlite3"))
    session = sessions.create(
        title="private",
        agent_id="slon",
        model_policy=ModelPolicy("p", "m"),
        workspace_id="workspace-a",
    )
    router = GatewayRouter()
    bind_session_routes(router, sessions)
    request = GatewayEnvelope(
        "get", "session.get", utc_timestamp(), session.id, None, {}
    )
    with pytest.raises(Exception):
        asyncio.run(router.dispatch(GatewayContext("b", "workspace-b", "c"), request))


def test_signed_artifact_limits_owner_expiry_tamper_and_download(
    tmp_path: Path,
) -> None:
    now = [100.0]
    store = _store(tmp_path)
    store.trust_device(
        device_id="a",
        device_name="a",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="a",
        workspace_id="wa",
        created_at=now[0],
    )
    service = ArtifactTransferService(
        store=store,
        root=tmp_path / "artifacts",
        signing_key=b"artifact-key",
        clock=lambda: now[0],
    )
    upload = service.issue(
        device_id="a",
        workspace_id="wa",
        operation="upload",
        mime_type="text/plain",
        max_bytes=5,
        ttl_seconds=10,
    )
    with pytest.raises(ArtifactTransferError):
        service.upload(
            ticket=upload.ticket + "x",
            device_id="a",
            workspace_id="wa",
            mime_type="text/plain",
            data=b"ok",
        )
    with pytest.raises(ArtifactTransferError, match="owner"):
        service.upload(
            ticket=upload.ticket,
            device_id="b",
            workspace_id="wa",
            mime_type="text/plain",
            data=b"ok",
        )
    saved = service.upload(
        ticket=upload.ticket,
        device_id="a",
        workspace_id="wa",
        mime_type="text/plain",
        data=b"hello",
    )
    with pytest.raises(ArtifactTransferError, match="owner"):
        service.issue_download(
            artifact_id=str(saved["artifact_id"]), device_id="b",
            workspace_id="wb", mime_type="text/plain", max_bytes=5,
        )
    with pytest.raises(ArtifactTransferError, match="identifier"):
        service.issue_download(
            artifact_id="../secret", device_id="a", workspace_id="wa",
            mime_type="text/plain", max_bytes=5,
        )
    download = service.issue_download(
        artifact_id=str(saved["artifact_id"]),
        device_id="a",
        workspace_id="wa",
        mime_type="text/plain",
        max_bytes=5,
    )
    assert service.download(
        ticket=download.ticket, device_id="a", workspace_id="wa"
    ) == (b"hello", "text/plain")
    with pytest.raises(ArtifactTransferError, match="already used|invalid"):
        service.download(ticket=download.ticket, device_id="a", workspace_id="wa")
    expired = service.issue(
        device_id="a",
        workspace_id="wa",
        operation="upload",
        mime_type="text/plain",
        max_bytes=5,
        ttl_seconds=1,
    )
    now[0] = 102.0
    with pytest.raises(ArtifactTransferError, match="expired"):
        service.upload(
            ticket=expired.ticket,
            device_id="a",
            workspace_id="wa",
            mime_type="text/plain",
            data=b"x",
        )


def test_restart_marks_pending_gateway_work_uncertain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.trust_device(
        device_id="a",
        device_name="a",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="a",
        workspace_id="wa",
        created_at=1,
    )
    store.put_operation(
        operation_id="job",
        kind="job",
        device_id="a",
        workspace_id="wa",
        session_id=None,
        status="running",
        payload={},
        now=1,
    )
    assert store.reserve_request(
        device_id="a", workspace_id="wa", request_id="r", now=1
    )
    assert store.recover_uncertain(2) == 1
    assert store.operations(workspace_id="wa", kind="job")[0]["status"] == "interrupted"
    with pytest.raises(GatewayStoreError, match="uncertain"):
        store.cached_response(device_id="a", workspace_id="wa", request_id="r")


def test_gateway_schema_rejects_future_version(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE gateway_schema(version INTEGER NOT NULL)")
    db.execute("INSERT INTO gateway_schema VALUES (999)")
    db.commit()
    db.close()
    with pytest.raises(GatewayStoreError, match="unsupported"):
        GatewayStore(path)


def test_internal_layers_do_not_import_gateway() -> None:
    root = Path(__file__).resolve().parents[3]
    for package in ("sessions", "runtime", "providers", "mark/tools"):
        for source in (root / package).rglob("*.py"):
            assert "import gateway" not in source.read_text(encoding="utf-8")


def _free_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def test_real_gateway_websocket_duplex_health_roundtrip(tmp_path: Path) -> None:
    gateway = SlonGateway(
        database_path=tmp_path / "gateway.sqlite3",
        artifact_root=tmp_path / "artifacts",
        signing_key=b"gateway-signing-key-for-tests-32bytes",
    )
    listener = DesktopControlListener(
        bind_port=_free_port(),
        gateway=gateway,
        signing_key=b"legacy-signing-key-for-tests-32bytes",
    )
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    # Pairing is initiated on the trusted desktop surface; the network API
    # accepts the human-transferred one-time code but never returns that code.
    start = gateway.auth.start_pairing()
    complete = listener.handle(
        "POST",
        "/v1/gateway/pairing/complete",
        body={
            "code": start.code,
            "device_name": "iPhone",
            "public_key": public,
        },
    )
    challenge = listener.handle(
        "POST",
        "/v1/gateway/auth/challenge",
        body={"device_id": complete.body["device_id"]},
    )
    signature = base64.b64encode(
        private.sign(challenge.body["nonce"].encode())
    ).decode()
    token = listener.handle(
        "POST",
        "/v1/gateway/auth/proof",
        body={
            "device_id": complete.body["device_id"],
            "nonce": challenge.body["nonce"],
            "signature": signature,
        },
    )
    host, port = listener.start()
    sock = socket.create_connection((host, port), timeout=2)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(
            (
                "GET /v1/gateway/ws?cursor=0 HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\nUpgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                f"Authorization: Bearer {token.body['access_token']}\r\n\r\n"
            ).encode()
        )
        assert b"101 Switching Protocols" in sock.recv(4096)
        payload = _envelope("system.health").to_json()
        mask = b"abcd"
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        frame = (
            bytes([0x81, 0x80 | 126]) + len(payload).to_bytes(2, "big") + mask + masked
        )
        sock.sendall(frame)
        response = sock.recv(4096)
        assert b"system.health_status" in response
        assert b"runtime_composed" in response
    finally:
        sock.close()
        listener.stop()
        gateway.close()
