"""Structured logging with correlation IDs, latency, and no secrets.

Provides:
- Correlation/run/session IDs in all logs
- Provider/model/tool call IDs in context
- Latency tracking (ms or seconds)
- Recovery status
- No secrets (API keys, tokens) in any output
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Generator

from i18n import t


# Context variables for current operation
CORRELATION_ID: ContextVar[str] = ContextVar("correlation_id", default="")
SESSION_ID: ContextVar[str] = ContextVar("session_id", default="")
TOOL_CALL_ID: ContextVar[str] = ContextVar("tool_call_id", default="")


@dataclass
class LogContext:
    """Context stored in log record."""

    correlation_id: str = ""
    session_id: str = ""
    tool_call_id: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    recovery_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter."""

    def __init__(self) -> None:
        super().__init__(fmt=None, datefmt=None, style="{")

    def format(self, record: logging.LogRecord) -> str:
        ctx = getattr(record, "structured_context", LogContext())
        entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": ctx.correlation_id,
            "session_id": ctx.session_id,
            "tool_call_id": ctx.tool_call_id,
            "latency_ms": ctx.latency_ms,
        }
        if ctx.provider:
            entry["provider"] = ctx.provider
        if ctx.model:
            entry["model"] = ctx.model
        if ctx.recovery_status:
            entry["recovery_status"] = ctx.recovery_status
        if hasattr(record, "exc_info") and record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        import json
        return json.dumps(entry, ensure_ascii=False)


class NoSecretFilter(logging.Filter):
    """Filter out any content that looks like a secret."""

    SECRET_PATTERNS = [
        "api_key", "token", "secret", "password", "credential",
        "authorization", "bearer", "apikey", "api-key",
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern in self.SECRET_PATTERNS:
            if pattern.lower() in msg.lower():
                # Mask potential secret values
                record.msg = record.getMessage().replace(
                    msg, f"[MASKED] (contains {pattern})"
                )
        return True


def _mask_secret_value(value: str) -> str:
    """Mask a secret value: show first 4 and last 4 chars."""
    if not value or len(value) < 8:
        return "[REDACTED]"
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def sanitize_for_log(value: str) -> str:
    """Sanitize a value for safe logging. Never log API keys."""
    if not value:
        return ""
    lowered = value.lower()
    # If it looks like an API key (long, mostly alphanumeric with dashes), mask it
    if len(value) > 20 and any(c.isupper() for c in value[:3]):
        # Could be an API key - mask it
        return _mask_secret_value(value)
    # If it contains known secret markers, mask
    for marker in ["key", "token", "secret", "password", "credential"]:
        if marker in lowered and len(value) > 10:
            return _mask_secret_value(value)
    return value


# ──────────────────────────────────────────────────────────────────────
# Latency tracking
# ──────────────────────────────────────────────────────────────────────


@contextmanager
def track_latency(
    logger: logging.Logger,
    operation: str,
    provider: str = "",
    model: str = "",
) -> Generator[None, None, None]:
    """Context manager that tracks and logs latency for an operation."""
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        ctx = LogContext(
            correlation_id=CORRELATION_ID.get(),
            session_id=SESSION_ID.get(),
            latency_ms=round(elapsed_ms, 2),
            provider=provider,
            model=model,
        )
        logger.debug(
            f"{t("observability.latency_logged", operation=operation)} "
            f"{elapsed_ms:.1f}ms",
            extra={"structured_context": ctx},
        )


# ──────────────────────────────────────────────────────────────────────
# Convenience functions
# ──────────────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """Get a logger with structured formatting."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        handler.addFilter(NoSecretFilter())
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


def set_correlation_id(correlation_id: str) -> None:
    """Set the current correlation ID."""
    CORRELATION_ID.set(correlation_id)


def set_session_id(session_id: str) -> None:
    """Set the current session ID."""
    SESSION_ID.set(session_id)


def set_tool_call_id(tool_call_id: str) -> None:
    """Set the current tool call ID."""
    TOOL_CALL_ID.set(tool_call_id)


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    cid = str(uuid.uuid4())[:8]
    set_correlation_id(cid)
    return cid


def generate_session_id() -> str:
    """Generate a new session ID."""
    sid = str(uuid.uuid4())[:12]
    set_session_id(sid)
    return sid


# ──────────────────────────────────────────────────────────────────────
# Recovery status logging
# ──────────────────────────────────────────────────────────────────────

RECOVERY_STATUS_LOG = get_logger("observability.recovery")


def log_recovery_attempt(
    component: str,
    attempt: int,
    max_retries: int,
    error: str = "",
) -> None:
    """Log a recovery attempt with structured context."""
    ctx = LogContext(
        correlation_id=CORRELATION_ID.get(),
        recovery_status=f"attempt_{attempt}/{max_retries}",
    )
    if error:
        msg = sanitize_for_log(
            t("observability.recovery_attempt",
              component=component,
              attempt=str(attempt),
              max=str(max_retries),
              error=error)
        )
    else:
        msg = t("observability.recovery_attempt",
                component=component,
                attempt=str(attempt),
                max=str(max_retries))
    RECOVERY_STATUS_LOG.warning(msg, extra={"structured_context": ctx})


def log_recovery_success(component: str) -> None:
    """Log successful recovery."""
    ctx = LogContext(
        correlation_id=CORRELATION_ID.get(),
        recovery_status="recovered",
    )
    RECOVERY_STATUS_LOG.info(
        t("observability.recovery_success", component=component),
        extra={"structured_context": ctx},
    )


def log_recovery_failed(component: str) -> None:
    """Log failed recovery after all attempts."""
    ctx = LogContext(
        correlation_id=CORRELATION_ID.get(),
        recovery_status="failed",
    )
    RECOVERY_STATUS_LOG.error(
        t("observability.recovery_failed", component=component),
        extra={"structured_context": ctx},
    )


def log_tool_call(
    logger: logging.Logger,
    tool_name: str,
    latency_ms: float,
    provider: str = "",
    model: str = "",
    success: bool = True,
) -> None:
    """Log a tool call with structured context."""
    ctx = LogContext(
        correlation_id=CORRELATION_ID.get(),
        session_id=SESSION_ID.get(),
        tool_call_id=TOOL_CALL_ID.get(),
        latency_ms=latency_ms,
        provider=provider,
        model=model,
    )
    level = logging.DEBUG if success else logging.WARNING
    msg = t("observability.tool_call_logged",
            name=tool_name,
            latency=f"{latency_ms:.1f}ms",
            success="true" if success else "false")
    logger.log(level, msg, extra={"structured_context": ctx})
