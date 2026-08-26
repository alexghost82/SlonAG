"""Deterministic test MCP server for testing MCP runtime without external dependencies.

This server speaks the MCP JSON-RPC protocol over stdio and provides:
- Fixed tool definitions (echo, compute, write_note, slow_operation)
- Resource discovery and reading
- Prompt discovery and retrieval
- Full MCP lifecycle (initialize, tools/list, tools/call, resources/read, prompts/list, prompts/get)

Usage:  python -m mark.mcp.test_server
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

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

RESOURCE_CONTENTS: dict[str, str] = {
    "memo://test/note": "This is test memo content.",
}


class TestMcpServer:
    """Standalone MCP test server for stdio transport testing."""

    def __init__(self) -> None:
        # Force unbuffered I/O
        sys.stdout.reconfigure(line_buffering=True)

    async def run(self) -> None:
        """Run the MCP server loop reading from stdin and writing to stdout."""
        loop = asyncio.get_running_loop()
        stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(stdin_reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        stdout = sys.stdout.buffer

        try:
            while True:
                line = await stdin_reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    request = json.loads(text)
                except json.JSONDecodeError:
                    self._write(stdout, self._error_response(None, "Parse error", f"Invalid JSON: {text[:200]}"))
                    continue

                result = await self._handle(request)
                if result is not None:
                    self._write(stdout, result)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                stdout.flush()
            except Exception:
                pass

    @staticmethod
    def _write(stdout, data: dict[str, Any]) -> None:
        payload = json.dumps(data) + "\n"
        stdout.write(payload.encode("utf-8"))
        try:
            stdout.flush()
        except Exception:
            pass

    async def _handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method", "")
        req_id = request.get("id")

        handlers: dict[str, Any] = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/templates/list": self._handle_resource_templates_list,
            "resources/read": self._handle_resource_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompt_get,
            "notifications/initialized": self._handle_notification_initialized,
        }

        handler = handlers.get(method)
        if handler is None:
            return self._error_response(req_id, f"Method not found: {method}", -32601)

        try:
            params = request.get("params", {}) or {}
            resp = await handler(params)
            return {"jsonrpc": "2.0", "id": req_id, "result": resp}
        except Exception as exc:
            return self._error_response(req_id, str(exc), -32603)

    @staticmethod
    async def _handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
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

    @staticmethod
    async def _handle_tools_list(params: dict[str, Any]) -> dict[str, Any]:
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
            await asyncio.sleep(min(duration, 30))
            return {"content": [{"type": "text", "text": "Done"}]}

        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True,
        }

    @staticmethod
    async def _handle_resources_list(params: dict[str, Any]) -> dict[str, Any]:
        return {"resources": TEST_RESOURCES}

    @staticmethod
    async def _handle_resource_templates_list(params: dict[str, Any]) -> dict[str, Any]:
        return {"resourceTemplates": TEST_RESOURCE_TEMPLATES}

    async def _handle_resource_read(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri", "")
        text = RESOURCE_CONTENTS.get(uri)
        if text is None:
            return {"contents": []}
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/plain",
                    "text": text,
                }
            ]
        }

    @staticmethod
    async def _handle_prompts_list(params: dict[str, Any]) -> dict[str, Any]:
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
                        "content": [{"type": "text", "text": summary}],
                    }
                ]
            }
        return {"messages": []}

    @staticmethod
    async def _handle_notification_initialized(params: dict[str, Any]) -> None:
        pass

    @staticmethod
    def _error_response(
        req_id: int | str | None, message: str, code: int = -32600
    ) -> dict[str, Any]:
        error: dict[str, Any] = {
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
        }
        if req_id is not None:
            error["id"] = req_id
        return error


def main() -> None:
    """Entry point for the test MCP server."""
    asyncio.run(TestMcpServer().run())


if __name__ == "__main__":
    main()
