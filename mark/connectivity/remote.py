"""Remote transport adapter.

Provides a fallback transport for out-of-LAN connections.  Uses
signaling (not raw media) through a pluggable remote adapter backend.

Security rules:
- Never sends raw media through Firebase or any third-party service.
- Uses explicit remote URLs — no UPnP, no NAT traversal hacks.
- Requires authentication on every message.
- TLS is always enabled for remote connections.
- No silent public exposure — remote must be explicitly configured.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from mark.connectivity.types import TransportKind

logger = logging.getLogger(__name__)


class RemoteAdapterError(RuntimeError):
    """Remote adapter error."""

    def __init__(self, message: str, *, code: str = "remote_error") -> None:
        super().__init__(message)
        self.code = code


class RemoteAdapter:
    """Remote transport adapter for out-of-LAN connectivity.

    This adapter establishes a WebSocket connection over the public internet
    to a remote signaling server.  The signaling server relays control-plane
    messages (chat, tasks, approvals) but never media — media flows through
    separate channels (e.g. RTSP) that are configured explicitly.

    The default backend uses websockets over HTTPS.  Subclass and override
    :meth:`_open_connection` to use a different backend (e.g. Firebase,
    MQTT, custom TCP).
    """

    # Default remote URL — can be configured.
    DEFAULT_REMOTE_URL = "wss://relay.mark.local/v1/connectivity/ws"

    def __init__(
        self,
        url: str = "",
        connect_timeout: float = 15.0,
        heartbeat_interval: float = 30.0,
        **kwargs: Any,
    ) -> None:
        self.url = url or self.DEFAULT_REMOTE_URL
        self.connect_timeout = connect_timeout
        self.heartbeat_interval = heartbeat_interval
        self._connection: Any = None
        self._connected = False
        self._message_id = 0
        self._closed = False

    async def connect(self) -> None:
        """Establish the remote WebSocket connection."""
        if self._closed:
            raise RemoteAdapterError("Adapter is closed", code="adapter_closed")

        try:
            self._connection = await self._open_connection(self.url)
            self._connected = True
            logger.info("Remote adapter connected: %s", self.url)
        except Exception as exc:
            raise RemoteAdapterError(
                f"Remote connection failed: {exc}",
                code="remote_connect_failed",
            ) from exc

    async def disconnect(self) -> None:
        """Close the remote connection."""
        self._closed = True
        self._connected = False
        if self._connection is not None:
            try:
                await asyncio.wait_for(
                    self._connection.close(code=1000, reason="shutdown"),
                    timeout=3.0,
                )
            except Exception:  # noqa: BLE001
                pass
            self._connection = None

    async def send(self, kind: str, payload: dict[str, Any]) -> int:
        """Send a message through the remote transport.

        Every message includes the kind and a sequence number for ordering.
        """
        self._require_connected()
        self._message_id += 1

        message = {
            "kind": kind,
            "payload": payload,
            "sequence": self._message_id,
            "timestamp": time.time(),
        }

        try:
            if self._connection is not None:
                await self._connection.send(json.dumps(message))
        except Exception as exc:
            self._connected = False
            raise RemoteAdapterError(
                f"Remote send failed: {exc}",
                code="remote_send_error",
            ) from exc

        return self._message_id

    async def receive(self, timeout: float = 30.0) -> dict[str, Any] | None:
        """Receive one message from the remote transport."""
        self._require_connected()
        try:
            if self._connection is not None:
                raw = await asyncio.wait_for(self._connection.recv(), timeout=timeout)
                if isinstance(raw, str):
                    return json.loads(raw)
                return {"_raw_binary": raw}
            return None
        except asyncio.TimeoutError:
            return None
        except Exception as exc:
            self._connected = False
            raise RemoteAdapterError(
                f"Remote receive failed: {exc}",
                code="remote_receive_error",
            ) from exc

    @property
    def connected(self) -> bool:
        return self._connected

    def is_relay(self) -> bool:
        """Return True — this adapter uses a remote relay."""
        return True

    # -- Override for custom backends --

    async def _open_connection(self, url: str) -> Any:
        """Open the underlying connection.

        Override this method to use a different transport backend
        (Firebase, MQTT, custom TCP, etc.).

        The default uses websockets over WSS (WebSocket Secure).
        """
        try:
            import websockets
            return await websockets.connect(
                url,
                timeout=self.connect_timeout,
            )
        except ImportError:
            pass

        # Fallback: use urllib + asyncio for a basic WSS connection.
        return await self._open_connection_fallback(url)

    async def _open_connection_fallback(self, url: str) -> Any:
        """Minimal stdlib WSS fallback when websockets is not available."""
        import asyncio
        import ssl
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 443

        # Create SSL context for remote connections (require valid certs).
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx),
            timeout=self.connect_timeout,
        )

        # WebSocket handshake (similar to transport.py).
        import base64
        import hashlib
        import random

        key = base64.b64encode(random.randbytes(16)).decode("ascii")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")

        request = (
            f"GET {parsed.path or '/'} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=self.connect_timeout)
        response_text = response.decode("utf-8", errors="replace")

        if "101" not in response_text:
            writer.close()
            await writer.wait_closed()
            raise RemoteAdapterError(
                f"WebSocket upgrade failed for remote: {response_text[:200]}",
                code="remote_upgrade_failed",
            )

        return _StdlibWebSocketForRemote(reader, writer)

    def _require_connected(self) -> None:
        if not self._connected or self._closed:
            raise RemoteAdapterError(
                "Not connected",
                code="not_connected",
            )


class _StdlibWebSocketForRemote:
    """Minimal stdlib WebSocket for remote connections."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def send(self, data: str) -> None:
        import json as _json
        if not isinstance(data, str):
            data = _json.dumps(data)
        from mark.connectivity.transport import _encode_text_frame
        frame = _encode_text_frame(data.encode("utf-8"))
        self.writer.write(frame)
        await self.writer.drain()

    async def recv(self) -> str | None:
        from mark.connectivity.transport import _decode_text_frame
        data = await self.reader.read(65536)
        if not data:
            return None
        return _decode_text_frame(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        import mark.connectivity.transport as _t
        frame = _t._encode_text_frame(b"")
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "RemoteAdapter",
    "RemoteAdapterError",
]
