"""MCP stdio transport wrapper for SlonAG."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Mapping
from typing import Any

from mark.mcp.types import McpServerConfig


class McpStdioTransport:
    """Manages stdin/stdout subprocess for stdio-based MCP servers.

    Implements full lifecycle:
    - Launch subprocess with configurable env/command/args
    - Read/write JSON-RPC messages over stdin/stdout
    - Handle disconnect and timeout
    - Cancellation support
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._closed = False
        self._pending_requests: dict[str, asyncio.Future] = {}

    async def start(self) -> None:
        """Launch the MCP server subprocess and open transport."""
        if self.config.command is None or self.config.command == "":
            raise ValueError("MCP stdio transport requires a non-empty command")

        env = self._make_env()
        proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        if proc.stdin is None or proc.stdout is None:
            await proc.wait()
            raise RuntimeError("MCP subprocess opened without stdin or stdout")

        self._process = proc
        self._reader_task = asyncio.create_task(self._reader_loop())

    def _make_env(self) -> dict[str, str]:
        import os
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.update(self.config.env)
        return env

    async def _reader_loop(self) -> None:
        """Read JSON-RPC messages from server stdout and dispatch."""
        if self._process is None or self._process.stdout is None:
            return
        try:
            while not self._closed:
                line = await self._process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                await self._handle_message(msg)
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Route JSON-RPC message to appropriate handler."""
        msg_id = msg.get("id")
        if msg_id is not None and isinstance(msg_id, str):
            future = self._pending_requests.pop(msg_id, None)
            if future is not None and not future.done():
                if "error" in msg:
                    error = msg["error"]
                    future.set_exception(
                        RuntimeError(
                            f"MCP error: {error.get('message', 'unknown')}"
                        )
                    )
                else:
                    future.set_result(msg.get("result"))

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """Send a JSON-RPC request and await the response."""
        if self._process is None or self._process.stdin is None or self._closed:
            raise RuntimeError("Transport is not connected")

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
            self._process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._process.stdin.drain()
            result = await asyncio.wait_for(future, timeout=timeout)
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
        return await self._send_request(method, params, timeout or 30.0)

    async def cancel_request(self, request_id: str) -> None:
        """Send CancelledNotification for an in-flight request."""
        if self._process is None or self._process.stdin is None:
            return
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "$/cancelled",
            "params": {"reason": "client cancellation"},
        }
        try:
            self._process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._process.stdin.drain()
        except Exception:
            pass

    async def stop(self) -> None:
        """Terminate the transport and subprocess."""
        self._closed = True
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        if hasattr(self, "_reader_task"):
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                    await self._process.wait()
                except Exception:
                    pass

    async def __aenter__(self) -> McpStdioTransport:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    @property
    def is_connected(self) -> bool:
        return (
            not self._closed
            and self._process is not None
            and self._process.returncode is None
        )
