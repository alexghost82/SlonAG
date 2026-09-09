"""Typed UI → Control Plane commands. UI widgets must not call Core directly."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class UiCommandKind(StrEnum):
    SEND_MESSAGE = "send_message"
    START_VOICE = "start_voice"
    STOP_VOICE = "stop_voice"
    CANCEL = "cancel"
    APPROVE = "approve"
    DENY = "deny"
    SELECT_MODEL = "select_model"
    CHANGE_SETTINGS = "change_settings"
    OPEN_SESSION = "open_session"


@dataclass(frozen=True)
class UiCommand:
    kind: UiCommandKind
    payload: Mapping[str, Any] = field(default_factory=dict)

    def action_name(self) -> str:
        return self.kind.value


REQUIRED_COMMANDS = frozenset(item.value for item in UiCommandKind)

__all__ = ["REQUIRED_COMMANDS", "UiCommand", "UiCommandKind"]
