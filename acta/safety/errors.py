"""Structured safety-policy error codes.

Messages must never include API keys, tokens, passwords, URLs with
credentials, or other secret values.
"""

from __future__ import annotations

from i18n import t
CODE_OK = "ok"
CODE_UNKNOWN_TOOL = "unknown_tool"
CODE_INVALID_ARGS = "invalid_args"
CODE_UNSAFE_URL = "unsafe_url"

ERROR_CODES = frozenset(
    {
        CODE_OK,
        CODE_UNKNOWN_TOOL,
        CODE_INVALID_ARGS,
        CODE_UNSAFE_URL,
    }
)

_MESSAGES: dict[str, str] = {
    CODE_OK: t("safety.ok"),
    CODE_UNKNOWN_TOOL: t("safety.unknown_tool"),
    CODE_INVALID_ARGS: t("safety.invalid_args"),
    CODE_UNSAFE_URL: t("safety.unsafe_url"),
}

_UNKNOWN = t("safety.policy_violation")


def safety_message(code: str) -> str:
    """Return a secret-free explanation for a structured safety error code."""
    return _MESSAGES.get(code, _UNKNOWN)


class SafetyPolicyError(Exception):
    """Caller or policy error. Messages never echo argument values."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message if message is not None else safety_message(code))


class UnknownToolError(SafetyPolicyError):
    """``tool_name`` is not in the in-code registry. Never a default risk."""

    def __init__(self, tool_name: str, message: str | None = None) -> None:
        self.tool_name = tool_name
        super().__init__(
            CODE_UNKNOWN_TOOL,
            message if message is not None else "Неизвестный инструмент.",
        )


class ArgValidationError(SafetyPolicyError):
    """Required keys are missing or a value has the wrong type."""

    def __init__(
        self,
        tool_name: str,
        message: str | None = None,
        *,
        field: str | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.field = field
        super().__init__(
            CODE_INVALID_ARGS,
            message if message is not None else safety_message(CODE_INVALID_ARGS),
        )


class UnsafeUrlError(SafetyPolicyError):
    """Scheme or host is blocked (non-http(s), private, loopback, metadata)."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            CODE_UNSAFE_URL,
            message if message is not None else safety_message(CODE_UNSAFE_URL),
        )


__all__ = [
    "CODE_INVALID_ARGS",
    "CODE_OK",
    "CODE_UNKNOWN_TOOL",
    "CODE_UNSAFE_URL",
    "ERROR_CODES",
    "ArgValidationError",
    "SafetyPolicyError",
    "UnknownToolError",
    "UnsafeUrlError",
    "safety_message",
]
