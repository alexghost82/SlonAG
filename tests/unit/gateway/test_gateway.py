from __future__ import annotations

import asyncio
import base64
import os
import socket
import sqlite3
import time
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gateway.artifacts import ArtifactTransferError, ArtifactTransferService
from gateway.approvals import DurableApprovalCoordinator
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
from gateway.status import read_gateway_status
from gateway.store import GatewayStore, GatewayStoreError
from gateway.websocket import GatewayWebSocketRuntime
from acta.bridge import RuntimeStack
from acta.safety import DecisionKind, RiskLevel, SafetyDecision, UntrustedSource
from acta.tools import ToolRegistry
from acta.tools.contracts import ToolSpec
from providers.contracts import (
    ChatResponse,
    ModelInfo,
    ToolCall,
    ToolResultMessage,
)
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
    with pytest.raises(GatewayProtocolError, match="(?i)control frame"):
        decode_client_frame(control)
    with pytest.raises(GatewayProtocolError, match="(?i)control frame"):
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


@pytest.mark.asyncio
async def test_long_lived_websocket_loses_authority_when_access_expires(
    tmp_path: Path,
) -> None:
    now = [100.0]
    store = _store(tmp_path)
    auth = GatewayAuthService(
        store=store, signing_key=b"expiry-key", clock=lambda: now[0],
        access_ttl_seconds=2,
    )
    private = Ed25519PrivateKey.generate()
    device_id = _pair(auth, private)
    challenge = auth.challenge(device_id)
    tokens = auth.exchange_proof(
        device_id=device_id, nonce=challenge.nonce,
        signature=base64.b64encode(private.sign(challenge.nonce.encode())).decode(),
    )
    headers = {"Authorization": f"Bearer {tokens.access_token}"}
    auth.authenticate_connection(headers)
    runtime = GatewayWebSocketRuntime(
        store=store, router=GatewayRouter(),
        is_active=lambda device: bool(store.device(device)["active"]),
        workspace_for=auth.workspace_for,
    )
    connection = await runtime.connect(
        device_id=device_id, validate_auth=lambda: auth.validate_connection(headers)
    )
    now[0] = 103.0
    with pytest.raises(GatewayProtocolError, match="authorization expired"):
        connection.drain()
    assert connection.closed


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
    with pytest.raises(GatewayProtocolError, match="cursor"):
        await runtime.connect(device_id="a", after_sequence=sequence + 100)


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


def test_durable_approval_is_scoped_terminal_and_not_resumed_after_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.sqlite3"
    store = GatewayStore(path)
    coordinator = DurableApprovalCoordinator(store)
    request = coordinator.request(
        workspace_id="a", tool_name="open_app", reason="confirm",
        timeout=30, session_id="session", run_id="run", tool_call_id="call",
    )
    assert not coordinator.decide(
        approval_id=request.approval_id, workspace_id="b", allow=True,
        device_id="foreign",
    )
    assert coordinator.decide(
        approval_id=request.approval_id, workspace_id="a", allow=False,
        device_id="device",
    )
    assert not coordinator.decide(
        approval_id=request.approval_id, workspace_id="a", allow=True,
        device_id="device",
    )
    assert not coordinator.wait(request, timeout=0)
    pending = coordinator.request(
        workspace_id="a", tool_name="open_app", reason="confirm", timeout=30,
        tool_call_id="pending-call",
    )
    store.close()
    reopened = GatewayStore(path)
    reopened.recover_uncertain(time.time())
    row = next(item for item in reopened.approvals(workspace_id="a")
               if item["approval_id"] == pending.approval_id)
    assert row["status"] == "interrupted"
    assert not DurableApprovalCoordinator(reopened).decide(
        approval_id=pending.approval_id, workspace_id="a", allow=True,
        device_id="device",
    )


def test_approval_expiry_cancellation_shutdown_and_job_cas_are_fail_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    coordinator = DurableApprovalCoordinator(store)
    expired = coordinator.request(
        workspace_id="workspace", tool_name="write", reason="confirm",
        timeout=0.01, session_id="session", run_id="run",
        tool_call_id="expired-call",
    )
    time.sleep(0.02)
    assert not coordinator.wait(expired, timeout=0)
    assert store.approval(expired.approval_id)["status"] == "expired"
    assert not coordinator.decide(
        approval_id=expired.approval_id, workspace_id="workspace", allow=True,
        device_id="device",
    )

    cancelled = coordinator.request(
        workspace_id="workspace", tool_name="write", reason="confirm", timeout=30,
        session_id="session", run_id="run", tool_call_id="cancelled-call",
    )
    coordinator.cancel(cancelled.approval_id, workspace_id="workspace")
    assert not coordinator.wait(cancelled, timeout=0)
    assert store.approval(cancelled.approval_id)["status"] == "cancelled"

    shutdown = coordinator.request(
        workspace_id="workspace", tool_name="write", reason="confirm", timeout=30,
        session_id="session", run_id="run", tool_call_id="shutdown-call",
    )
    coordinator.close()
    assert not coordinator.wait(shutdown, timeout=0)
    assert store.approval(shutdown.approval_id)["status"] == "cancelled"

    store.trust_device(
        device_id="device", device_name="phone",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="job-device", workspace_id="workspace", created_at=1,
    )
    store.put_operation(
        operation_id="job", kind="job", device_id="device",
        workspace_id="workspace", session_id="session", status="running",
        payload={"request_id": "request"}, now=1,
    )
    assert store.update_operation("job", "cancelled", 2)
    assert not store.update_operation("job", "completed", 3)
    assert store.operation("job", workspace_id="workspace")["status"] == "cancelled"
    assert store.operation("job", workspace_id="foreign") is None


def test_legacy_desktop_waiter_delegates_to_durable_gateway_approval(
    tmp_path: Path,
) -> None:
    gateway = SlonGateway(
        database_path=tmp_path / "shared-approval.sqlite3",
        artifact_root=tmp_path / "artifacts", signing_key=b"approval-key",
    )
    gateway.store.trust_device(
        device_id="device", device_name="phone",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="device", workspace_id="desktop", created_at=time.time(),
    )
    listener = DesktopControlListener(gateway=gateway)
    outcome: list[bool] = []
    worker = threading.Thread(target=lambda: outcome.append(
        listener._request_tool_approval(
            "open_app", {}, "user", "confirm", "desktop-call"
        )
    ))
    worker.start()
    deadline = time.time() + 2
    approvals = []
    while time.time() < deadline and not approvals:
        approvals = gateway.store.approvals(workspace_id="desktop")
        time.sleep(0.01)
    approval_id = str(approvals[0]["approval_id"])
    response = asyncio.run(gateway.router.dispatch(
        GatewayContext("device", "desktop", "connection"),
        GatewayEnvelope(
            "decision", "approval.decide", utc_timestamp(), None, "decision-1",
            {"approval_id": approval_id, "decision": "allow"},
        ),
    ))
    worker.join(timeout=2)
    assert response.type == "approval.decided"
    assert outcome == [True]
    with pytest.raises(GatewayProtocolError, match="unavailable"):
        asyncio.run(gateway.router.dispatch(
            GatewayContext("device", "desktop", "connection"),
            GatewayEnvelope(
                "duplicate", "approval.decide", utc_timestamp(), None, "decision-2",
                {"approval_id": approval_id, "decision": "allow"},
            ),
        ))
    gateway.close()


def test_gateway_runtime_status_detects_stale_process(tmp_path: Path) -> None:
    path = tmp_path / "status.sqlite3"
    store = GatewayStore(path)
    store.update_runtime_status(
        instance_id="instance", state="running", heartbeat_at=time.time() - 30,
        bind_host="192.168.1.20", tls_active=True,
    )
    status = read_gateway_status(path, stale_after_seconds=5)
    assert status["state"] == "unavailable"
    assert set(status) == {
        "singleton", "instance_id", "state", "heartbeat_at", "bind_host",
        "tls_active", "connected_devices", "error_code",
    }
    assert not ({"token", "secret", "pairing_code", "private_key"} & set(status))


@pytest.mark.asyncio
async def test_same_websocket_agent_run_approval_and_completion_are_correlated(
    tmp_path: Path,
) -> None:
    manager = SessionManager(SessionStore(tmp_path / "sessions.sqlite3"))
    model = ModelInfo(
        "test", "model", "Test", text=True, tool_calling=True
    )
    session = manager.create(
        title="Gateway", agent_id="agent",
        model_policy=ModelPolicy("test", "model"), workspace_id="workspace-a",
    )
    handler_calls: list[dict[str, object]] = []
    chat_messages: list[list[str]] = []
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="side_effect", description="effect",
        input_schema={"type": "object"}, output_schema=None,
        handler=lambda arguments: handler_calls.append(dict(arguments)) or "done",
        risk=RiskLevel.CONFIRM,
    ))

    class ConfirmPolicy:
        def validate_args(self, _name, arguments):
            return dict(arguments)

        def authorize(self, name, arguments, **_kwargs):
            return SafetyDecision(
                DecisionKind.CONFIRM, name, RiskLevel.CONFIRM,
                UntrustedSource.USER, "effect", dict(arguments), "confirm",
            )

    class Router:
        async def list_models(self, _provider_id):
            return (model,)

        async def chat(self, request):
            chat_messages.append([type(item).__name__ for item in request.messages])
            if any(isinstance(item, ToolResultMessage) for item in request.messages):
                return ChatResponse("complete", "test", "model")
            return ChatResponse(
                "", "test", "model",
                (ToolCall("provider-call-42", "side_effect", {"value": 42}),),
            )

    stack = RuntimeStack(
        provider_id="test", network_mode="offline", router=Router(),
        safety=ConfirmPolicy(), tool_registry=registry,
        session_manager=manager,
    )
    gateway = SlonGateway(
        database_path=tmp_path / "gateway.sqlite3",
        artifact_root=tmp_path / "artifacts", signing_key=b"test-signing-key",
        session_manager=manager, runtime_stack=stack,
    )
    gateway.store.trust_device(
        device_id="device", device_name="phone",
        public_key=base64.b64encode(b"x" * 32).decode(),
        key_fingerprint="device", workspace_id="workspace-a", created_at=time.time(),
    )
    connection = await gateway.websocket.connect(device_id="device")
    run = GatewayEnvelope(
        "run-event", "agent.run", utc_timestamp(), session.id, "run-request",
        {"goal": "perform effect"},
    )
    accepted = await connection.receive(run.to_json())
    assert accepted.type == "agent.accepted"
    job_id = accepted.payload["job_id"]

    requested = None
    deadline = time.monotonic() + 3
    while requested is None and time.monotonic() < deadline:
        for item in connection.drain():
            if item.envelope.type == "approval.requested":
                requested = item.envelope
        if requested is None:
            await asyncio.sleep(0.01)
    assert requested is not None
    assert requested.payload["job_id"] == job_id
    assert requested.payload["tool_call_id"] == "provider-call-42"
    approval_id = requested.payload["approval_id"]
    stored = gateway.store.approval(str(approval_id))
    assert stored is not None
    assert stored["workspace_id"] == "workspace-a"
    assert stored["session_id"] == session.id
    assert stored["run_id"] == job_id
    assert stored["tool_call_id"] == "provider-call-42"

    decided = await connection.receive(GatewayEnvelope(
        "decision-event", "approval.decide", utc_timestamp(), session.id,
        "decision-request", {"approval_id": approval_id, "decision": "allow"},
    ).to_json())
    assert decided.type == "approval.decided"
    assert decided.payload["tool_call_id"] == "provider-call-42"

    completed = None
    deadline = time.monotonic() + 3
    while completed is None and time.monotonic() < deadline:
        for item in connection.drain():
            if item.envelope.type == "agent.completed":
                completed = item.envelope
        if completed is None:
            await asyncio.sleep(0.01)
    assert completed is not None, {
        "operation": gateway.store.operation(
            str(job_id), workspace_id="workspace-a"
        ),
        "approval": gateway.store.approval(str(approval_id)),
        "handler_calls": handler_calls,
        "transcript": manager.get(
            session.id, workspace_id="workspace-a"
        ).transcript,
    }
    assert completed.session_id == session.id
    assert completed.payload["job_id"] == job_id
    assert completed.payload["ok"] is True, completed.payload
    assert handler_calls == [{"value": 42}]
    assert chat_messages == [
        ["UserMessage"],
        ["UserMessage", "AssistantToolCallMessage", "ToolResultMessage"],
    ]
    gateway.close()


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
    for package in ("sessions", "runtime", "providers", "acta/tools"):
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
