"""Structured proactive-agent error codes and exceptions.

Messages never include secrets, API keys, tokens, or user data.
"""
from __future__ import annotations

from i18n import t

# Error codes
CODE_OK = "ok"
CODE_INVALID_EVENT = "invalid_event"
CODE_SPAM_DETECTED = "spam_detected"
CODE_COOLDOWN_ACTIVE = "cooldown_active"
CODE_PERM_DENIED = "permission_denied"
CODE_RELEVANCE_TOO_LOW = "relevance_too_low"
CODE_ACTION_BLOCKED = "action_blocked"
CODE_DUPLICATE_EVENT = "duplicate_event"
CODE_INVALID_ACTION = "invalid_action"

ERROR_CODES: frozenset[str] = frozenset([
    CODE_OK,
    CODE_INVALID_EVENT,
    CODE_SPAM_DETECTED,
    CODE_COOLDOWN_ACTIVE,
    CODE_PERM_DENIED,
    CODE_RELEVANCE_TOO_LOW,
    CODE_ACTION_BLOCKED,
    CODE_DUPLICATE_EVENT,
    CODE_INVALID_ACTION,
])

_MESSAGES: dict[str, str] = {
    CODE_OK: t("proactive.ok"),
    CODE_INVALID_EVENT: t("proactive.invalid_event"),
    CODE_SPAM_DETECTED: t("proactive.spam_detected"),
    CODE_COOLDOWN_ACTIVE: t("proactive.cooldown_active"),
    CODE_PERM_DENIED: t("proactive.permission_denied"),
    CODE_RELEVANCE_TOO_LOW: t("proactive.relevance_too_low"),
    CODE_ACTION_BLOCKED: t("proactive.action_blocked"),
    CODE_DUPLICATE_EVENT: t("proactive.duplicate_event"),
    CODE_INVALID_ACTION: t("proactive.invalid_action"),
}


def proactive_message(code: str) -> str:
    return _MESSAGES.get(code, code)


class ProactiveError(Exception):
    """Base exception for proactive-agent errors.

    Messages never echo argument values or secrets.
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or proactive_message(code))


class InvalidEventError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_INVALID_EVENT, message)


class SpamDetectedError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_SPAM_DETECTED, message)


class CooldownActiveError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_COOLDOWN_ACTIVE, message)


class PermissionDeniedError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_PERM_DENIED, message)


class RelevanceTooLowError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_RELEVANCE_TOO_LOW, message)


class ActionBlockedError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_ACTION_BLOCKED, message)


class DuplicateEventError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_DUPLICATE_EVENT, message)


class InvalidActionError(ProactiveError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_INVALID_ACTION, message)
