"""Deterministic test MCP server for testing MCP runtime without external dependencies.

This server speaks the MCP JSON-RPC protocol over stdio and provides:
- Fixed tool definitions (echo, compute, side_effect, approve_me)
- Resource discovery
- Prompt discovery
- Full lifecycle (initialize, tools/list, tools/call, resources/read)

Usage:  python -m mark.mcp.test_server
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

# --- MCP-defined tools ---
TEST_TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the provided message. Safe read-only operation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo back"},
            },
            "required": ["message"],
        },
        "annotations": {"readsResult": False, "writesResult": False},
    },
    {
        "name": "compute",
        "description": "Compute arithmetic. Returns numeric result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "Arithmetic operation",
                },
                "a": {"type": "number", "description": "First operand"},
                "b": {"type": "number", "description": "Second operand"},
            },
            "required": ["operation", "a", "b"],
        },
        "annotations": {"readsResult": False, "writesResult": False},
    },
    {
        "name": "write_note",
        "description": "Write a note to the test system. Requires approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["title", "content"],
        },
        "annotations": {"readsResult": False, "writesResult": True},
    },
    {
        "name": "slow_operation",
        "description": "A slow operation that takes 5 seconds. Useful for timeout testing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "duration_seconds": {"type": "number", "default": 5},
            },
        },
        "annotations": {"readsResult": False, "writesResult": False},
    },
]

TEST_RESOURCES = [
    {
        "uri": "memo://test/note",
        "name": "Test Note",
        "description": "A memo note for testing",
        "mimeType": "text/plain",
    },
]

TEST_RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "memo://test/{id}",
        "name": "Test Memo by ID",
        "description": "A memo by ID",
        "mimeType": "text/plain",
    },
]

TEST_PROMPTS = [
    {
        "name": "summarize",
        "description": "Summarize the given text",
        "arguments": [
            {
                "name": "text",
                "description": "Text to summarize",
                "required": True,
            }
        ],
    },
]

RESOURCE_CONTENTS = {
    "memo://test/note": "This is test memo content.",
}


class TestMcpServer:
    """Standalone MCP test server for stdio transport testing."""

    def __init__(self) -> None:
        self._next_id = 0

    async def run(self) -> None:
        """Run the MCP server loop reading from stdin and writing to stdout."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        writer: asyncio.StreamWriter = await asyncio.get_running_loop().create_future()
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_connection(
            lambda: asyncio.Protocol(), fd=sys.stdout.fileno()
        )
        writer = transport  # type: ignore[assignment]

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    request = json.loads(text)
                except json.JSONDecodeError:
                    await self._send_error(writer, None, "Parse error", f"Invalid JSON: {text[:200]}")
                    continue

                result = await self._handle(request)
                if result is not None:
                    await self._send_json(writer, result)
        except asyncio.CancelledError:
            pass

    async def _handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method", "")
        req_id = request.get("id")

        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/templates/list": self._handle_resource_templates_list,
            "resources/read": self._handle_resource_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompt_get,
        }

        handler = handlers.get(method)
        if handler is None:
            if req_id is not None:
                return self._error_response(req_id, "Method not found", -32601)
            return None

        try:
            params = request.get("params", {})
            result = await handler(params)
            if req_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result,
                }
        except Exception as exc:
            if req_id is not None:
                return self._error_response(req_id, str(exc), -32603)
            return None
        return None

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": "2025-03-26",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True},
                "prompts": {"listChanged": True},
                "logging": {},
            },
            "serverInfo": {"name": "slon-test-mcp", "version": "1.0.0"},
        }

    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": TEST_TOOLS}

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments", {})

        if name == "echo":
            msg = args.get("message", "")
            return {"content": [{"type": "text", "text": msg}]}

        if name == "compute":
            op = args.get("operation", "")
            a = args.get("a", 0)
            b = args.get("b", 0)
            if op == "add":
                result = a + b
            elif op == "subtract":
                result = a - b
            elif op == "multiply":
                result = a * b
            elif op == "divide":
                if b == 0:
                    return {
                        "content": [{"type": "text", "text": "Division by zero"}],
                        "isError": True,
                    }
                result = a / b
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown operation: {op}"}],
                    "isError": True,
                }
            return {"content": [{"type": "text", "text": str(result)}]}

        if name == "write_note":
            title = args.get("title", "")
            content = args.get("content", "")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Note '{title}' written with {len(content)} chars.",
                    }
                ]
            }

        if name == "slow_operation":
            duration = args.get("duration_seconds", 5)
            await asyncio.sleep(min(duration, 30))  # Cap at 30s
            return {"content": [{"type": "text", "text": "Done"}]}

        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True,
        }

    async def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"resources": TEST_RESOURCES}

    async def _handle_resource_templates_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"resourceTemplates": TEST_RESOURCE_TEMPLATES}

    async def _handle_resource_read(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri", "")
        text = RESOURCE_CONTENTS.get(uri)
        if text is None:
            return {
                "contents": [],
            }
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/plain",
                    "text": text,
                }
            ]
        }

    async def _handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"prompts": TEST_PROMPTS}

    async def _handle_prompt_get(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name == "summarize":
            text = args.get("text", "")
            summary = f"Summary: {text[:50]}..." if text else "Empty text"
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "content": {"type": "text", "text": summary},
                    }
                ]
            }
        return {"messages": []}

    async def _send_json(self, writer: Any, data: dict[str, Any]) -> None:
        payload = json.dumps(data) + "\n"
        writer.write(payload.encode("utf-8"))
        await writer.drain()

    async def _send_error(
        self, writer: Any, req_id: int | str | None, message: str, code: int = -32600
    ) -> None:
        error: dict[str, Any] = {
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
        }
        if req_id is not None:
            error["id"] = req_id
        await self._send_json(writer, error)

    @staticmethod
    def _error_response(
        req_id: int | str, message: str, code: int = -32600
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


def main() -> None:
    """Entry point for the test MCP server."""
    server = TestMcpServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
