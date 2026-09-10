from __future__ import annotations

import base64
import time
from pathlib import Path

import pytest

from gateway.contracts import (
    MAX_ENVELOPE_BYTES,
    GatewayEnvelope,
    GatewayProtocolError,
    utc_timestamp,
)
from gateway.framing import decode_client_frame
from gateway.router import GatewayRouter
from gateway.store import GatewayStore
from gateway.websocket import GatewayWebSocketRuntime


def _store(tmp_path: Path) -> GatewayStore:
    return GatewayStore(tmp_path / "gateway.sqlite3")


def _trust(store: GatewayStore, device: str = "phone", workspace: str = "home") -> None:
    store.trust_device(
        device_id=device,
        device_name=device,
        public_key=base64.b64encode(b"k" * 32).decode(),
        key_fingerprint=device,
        workspace_id=workspace,
        created_at=time.time(),
    )


def _envelope(event_id: str, kind: str = "system.runtime_event", **payload) -> GatewayEnvelope:
    return GatewayEnvelope(
        id=event_id,
        type=kind,
        timestamp=utc_timestamp(),
        session_id="sess-1",
        request_id=event_id,
        payload=payload,
    )


def _runtime(store: GatewayStore, *, max_pending: int = 128) -> GatewayWebSocketRuntime:
    return GatewayWebSocketRuntime(
        store=store,
        router=GatewayRouter(),
        is_active=lambda value: bool(store.device(value)["active"]),  # type: ignore[index]
        workspace_for=lambda value: str(store.device(value)["workspace_id"]),  # type: ignore[index]
        max_pending=max_pending,
    )


@pytest.mark.asyncio
async def test_reconnect_replays_after_disconnect(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trust(store)
    runtime = _runtime(store)
    first = await runtime.connect(device_id="phone", after_sequence=0)
    seq = await runtime.publish("home", _envelope("e1", state="thinking"))
    assert first.drain()[0].sequence == seq
    first.close()
    seq2 = await runtime.publish("home", _envelope("e2", state="speaking"))
    second = await runtime.connect(device_id="phone", after_sequence=seq)
    replayed = second.drain()
    assert [item.envelope.id for item in replayed] == ["e2"]
    assert replayed[0].sequence == seq2
    runtime.close()


@pytest.mark.asyncio
async def test_backpressure_disconnects_slow_client(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trust(store)
    runtime = _runtime(store, max_pending=2)
    conn = await runtime.connect(device_id="phone", after_sequence=0)
    await runtime.publish("home", _envelope("a"))
    await runtime.publish("home", _envelope("b"))
    await runtime.publish("home", _envelope("c"))
    assert conn.closed
    runtime.close()


def test_malformed_and_large_frames_fail_closed() -> None:
    with pytest.raises(GatewayProtocolError, match="(?i)(malformed|некоррект)"):
        GatewayEnvelope.from_json(b"{not-json")
    with pytest.raises(GatewayProtocolError):
        decode_client_frame(b"\x81")
    with pytest.raises(GatewayProtocolError, match="(?i)(too large|слишком большой|oversized)"):
        GatewayEnvelope.from_json(b"x" * (MAX_ENVELOPE_BYTES + 8))
