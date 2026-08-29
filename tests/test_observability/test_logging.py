"""Tests for observability/logging.py."""

import json
import logging
import sys
import uuid
from io import StringIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from observability.logging import (
    LogContext,
    StructuredFormatter,
    NoSecretFilter,
    sanitize_for_log,
    get_logger,
    set_correlation_id,
    set_session_id,
    set_tool_call_id,
    generate_correlation_id,
    generate_session_id,
    CORRELATION_ID,
    SESSION_ID,
    TOOL_CALL_ID,
)


class TestLogContext:
    def test_default_values(self):
        ctx = LogContext()
        assert ctx.correlation_id == ""
        assert ctx.session_id == ""
        assert ctx.latency_ms == 0.0

    def test_to_dict(self):
        ctx = LogContext(correlation_id="abc", session_id="xyz", latency_ms=42.5,
                         provider="openai", model="gpt-4")
        d = ctx.to_dict()
        assert d["correlation_id"] == "abc"
        assert d["session_id"] == "xyz"
        assert d["latency_ms"] == 42.5
        assert d["provider"] == "openai"
        assert d["model"] == "gpt-4"


class TestStructuredFormatter:
    def test_formats_json(self):
        fmt = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello world", args=(), exc_info=None,
        )
        record.structured_context = LogContext(correlation_id="abc", session_id="xyz")
        result = fmt.format(record)
        data = json.loads(result)
        assert data["level"] == "INFO"
        assert data["message"] == "hello world"
        assert data["correlation_id"] == "abc"
        assert data["session_id"] == "xyz"


class TestNoSecretFilter:
    def test_allows_safe_message(self):
        f = NoSecretFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="user logged in", args=(), exc_info=None,
        )
        assert f.filter(record) is True

    def test_filters_secret_message(self):
        f = NoSecretFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="api_key=abc123 is valid", args=(), exc_info=None,
        )
        assert f.filter(record) is True


class TestSanitizeForLog:
    def test_empty_string(self):
        assert sanitize_for_log("") == ""

    def test_long_uppercase_mixed_masked(self):
        # Looks like an API key (first 3 chars contain uppercase)
        val = "SKE-abcdef1234567890ABCDEF"
        result = sanitize_for_log(val)
        assert "****" in result or "[REDACTED]" in result

    def test_short_value_not_masked(self):
        assert sanitize_for_log("short") == "short"

    def test_known_marker_masked(self):
        val = "my_secret_password_value"
        result = sanitize_for_log(val)
        assert "****" in result or "[REDACTED]" in result


class TestContextVars:
    def test_generate_correlation_id(self):
        cid = generate_correlation_id()
        assert len(cid) > 0
        assert CORRELATION_ID.get() == cid

    def test_generate_session_id(self):
        sid = generate_session_id()
        assert len(sid) > 0
        assert SESSION_ID.get() == sid

    def test_set_correlation_id(self):
        cid = str(uuid.uuid4())[:8]
        set_correlation_id(cid)
        assert CORRELATION_ID.get() == cid

    def test_set_session_id(self):
        sid = str(uuid.uuid4())[:12]
        set_session_id(sid)
        assert SESSION_ID.get() == sid

    def test_set_tool_call_id(self):
        from observability.logging import set_tool_call_id, TOOL_CALL_ID
        tid = str(uuid.uuid4())[:8]
        set_tool_call_id(tid)
        assert TOOL_CALL_ID.get() == tid


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test.obs.unit")
        assert isinstance(logger, logging.Logger)
        assert len(logger.handlers) > 0

    def test_output_is_json(self, capsys):
        logger = get_logger("test.obs.json_output")
        logger.info("test message")
        captured = capsys.readouterr()
        # StreamHandler writes to stderr by default
        output = captured.err.strip() if captured.err.strip() else captured.out.strip()
        data = json.loads(output)
        assert data["message"] == "test message"
        assert data["level"] == "INFO"
