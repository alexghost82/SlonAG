"""Reject passwords, API keys, tokens, and payment-card-like values.

Extra sensitive categories are caller-configurable. Exception text never
echoes the rejected value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from mark.memory.errors import MemoryPolicyError

_BUILTIN_KEY_MARKERS = frozenset(
    {
        "password",
        "passwd",
        "passphrase",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "secret",
        "credit_card",
        "card_number",
        "cardnumber",
        "cvv",
        "cvc",
        "pan",
        "payment_card",
    }
)

_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[baprs]-"),
    re.compile(r"(?i)\b(?:sk|pk|rk|tok)[_-](?:live|test)[_-][A-Za-z0-9]{8,}"),
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+"),
)

_CARD_CANDIDATE = re.compile(r"(?:\d[ \t-]?){13,19}")
_SPLIT_KEY = re.compile(r"[._/\s=:\-]+")


class MemoryPolicy:
    """Decide whether a key/value pair is allowed in the memory store."""

    def __init__(self, extra_categories: Sequence[str] = ()) -> None:
        extras = tuple(item.strip().lower() for item in extra_categories if item.strip())
        self.extra_categories = extras
        self._key_markers = _BUILTIN_KEY_MARKERS | frozenset(
            marker.replace("-", "_") for marker in extras
        )

    def allows(self, key: str, value: str) -> bool:
        """Return True when the pair is not secret-like."""
        return self.reject_reason(key, value) is None

    def check(self, key: str, value: str) -> None:
        """Raise ``MemoryPolicyError`` when the pair looks like a secret."""
        reason = self.reject_reason(key, value)
        if reason is None:
            return
        raise MemoryPolicyError(reason)

    def reject_reason(self, key: str, value: str) -> str | None:
        """Return a secret-free reason, or None when the pair is allowed."""
        if _key_has_marker(key, self._key_markers):
            return "Память отказала в сохранении: похоже на секрет."
        if _value_looks_secret(value):
            return "Память отказала в сохранении: похоже на секретное значение."
        if _looks_like_card(value):
            return "Память отказала в сохранении: похоже на данные платёжной карты."
        return None


def _key_has_marker(key: str, markers: Iterable[str]) -> bool:
    normalized = key.lower().replace("-", "_")
    parts = [part for part in _SPLIT_KEY.split(normalized) if part]
    collapsed_full = normalized.replace("_", "")
    bounded = f"_{normalized}_"
    for marker in markers:
        token = marker.lower().replace("-", "_")
        compact = token.replace("_", "")
        if token == normalized or compact == collapsed_full:
            return True
        if f"_{token}_" in bounded:
            return True
        if token in parts or compact in parts:
            return True
    return False


def _value_looks_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _VALUE_PATTERNS)


def _looks_like_card(value: str) -> bool:
    for match in _CARD_CANDIDATE.finditer(value):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return True
    return False


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = ord(char) - 48
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0




# ---------------------------------------------------------------------------
# Convenience public API
# ---------------------------------------------------------------------------


def should_block_memory(value: str) -> bool:
    """Return True when *value* looks like a secret and should be
    blocked from being stored in memory."""
    return _value_looks_secret(value) or _looks_like_card(value)


__all__ = ["MemoryPolicy", "should_block_memory"]
