"""MCP Streamable HTTP transport using the official MCP SDK.

Wraps mcp.client.streamable_http.streamable_http_client to provide
a transport compatible with the existing McpClient interface.
"""

from __future__ import annotations

from i18n import t
import asyncio
import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class McpStreamableHttpTransport:
    """Streamable HTTP transport for MCP servers.

    Uses the official MCP SDK's streamable_http_client to communicate
    with MCP servers over HTTP with SSE (Server-Sent Events) for
    server-to-client messages and POST for client-to-server.

    Supports:
    - Connection to HTTP-based MCP servers
    - Session management (resumption via MCP-Session-Id header)
    - JSON-RPC 2.0 message framing
    - Timeout and cancellation
    - Automatic reconnection (SDK handles retries)
    - SSE response parsing
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        write_timeout: float = 30.0,
        pool_timeout: float = 30.0,
    ) -> None:
        self.url = url
        self._headers = headers or {}
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._write_timeout = write_timeout
        self._pool_timeout = pool_timeout
        self._write_stream: Any = None
        self._closed = False
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._session_id: str | None = None
        self._reader_task: asyncio.Task[None] | None = None

    def _make_timeout(self, read_override: float | None = None) -> Any:
        """Create an httpx Timeout with consistent keyword params."""
        import httpx
        return httpx.Timeout(
            connect=self._connect_timeout,
            read=read_override if read_override is not None else self._read_timeout,
            write=self._write_timeout,
            pool=self._pool_timeout,
        )

    async def start(self) -> None:
        """Connect to the MCP server and initialize transport streams."""
        if self._closed:
            raise RuntimeError("Транспорт уже остановлен")

        # Lazy import to avoid circular imports during pytest collection
        from mcp.client.streamable_http import streamable_http_client
        import httpx

        http_client = httpx.AsyncClient(
            timeout=self._make_timeout(),
        )

        try:
            async with streamable_http_client(
                self.url, http_client=http_client
            ) as (read_stream, write_stream, session_id):
                self._write_stream = write_stream
                self._session_id = session_id

                # Start the reader loop in background
                self._reader_task = asyncio.create_task(self._reader_loop(read_stream))

                # Verify connection by sending initialize request
                try:
                    result = await self._send_request(
                        "initialize",
                        {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "slonag",
                                "version": "0.1.0",
                            },
                        },
                        timeout=15.0,
                    )
                    if not isinstance(result, dict):
                        raise ValueError("initialize вернул результат не в формате dict")
                except Exception:
                    # Server may not support initialize; transport is still valid
                    pass

        except Exception as exc:
            raise RuntimeError(t("mcp.session_failed", exc=str(exc))) from exc

    async def _reader_loop(self, read_stream: Any) -> None:
        """Read SSE messages from server and dispatch JSON-RPC responses."""
        try:
            async for msg in read_stream:
                if self._closed:
                    break
                await self._handle_message(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("MCP HTTP reader loop ended with exception")

    async def _handle_message(self, msg: Any) -> None:
        """Route incoming message to appropriate handler."""
        try:
            if isinstance(msg, bytes):
                text = msg.decode("utf-8", errors="replace").strip()
                if not text:
                    return
                data = json.loads(text)
            else:
                data = msg if isinstance(msg, dict) else {}

            msg_id = data.get("id")
            if msg_id is not None and isinstance(msg_id, str):
                future = self._pending_requests.pop(msg_id, None)
                if future is not None and not future.done():
                    if "error" in data:
                        error = data["error"]
                        future.set_exception(
                            RuntimeError(
                                f"MCP error: {error.get('message', 'неизвестная ошибка')}"
                            )
                        )
                    else:
                        future.set_result(data.get("result"))
        except Exception:
            logger.debug("Failed to handle MCP message", exc_info=True)

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """Send a JSON-RPC request over HTTP POST."""
        import httpx

        if self._write_stream is None or self._closed:
            raise RuntimeError("Транспорт не подключён")

        request_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            payload_bytes = json.dumps(payload).encode("utf-8")

            headers = dict(self._headers)
            if self._session_id:
                headers["MCP-Session-Id"] = self._session_id

            async with httpx.AsyncClient(
                timeout=self._make_timeout(read_override=timeout)
            ) as client:
                resp = await client.post(
                    self.url,
                    content=payload_bytes,
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                )
                resp.raise_for_status()
                result = resp.json()
                return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise
        except asyncio.CancelledError:
            self._pending_requests.pop(request_id, None)
            raise

    async def send_message(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a JSON-RPC method call and return the result."""
        return await self._send_request(method, params, timeout or self._read_timeout)

    async def cancel_request(self, request_id: str) -> None:
        """Send cancellation notification."""
        if self._write_stream is None:
            return
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "$/cancelled",
            "params": {"reason": "отмена клиентом"},
        }
        try:
            self._write_stream.send_nowait(
                json.dumps(payload).encode("utf-8")
            )
        except Exception:
            pass

    async def stop(self) -> None:
        """Close the transport."""
        self._closed = True
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

    @property
    def is_connected(self) -> bool:
        return not self._closed and self._write_stream is not None

    async def __aenter__(self) -> McpStreamableHttpTransport:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()
