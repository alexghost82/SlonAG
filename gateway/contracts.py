"""Strict public wire contracts for the Slon Gateway."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from i18n import t

MAX_ENVELOPE_BYTES = 256 * 1024
ALLOWED_NAMESPACES = frozenset(
    {"session", "agent", "node", "automation", "approval", "media", "system"}
)


class GatewayProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class GatewayEnvelope:
    id: str
    type: str
    timestamp: str
    session_id: str | None
    request_id: str | None
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.id.strip() or len(self.id) > 128:
            raise GatewayProtocolError("invalid_id", t("error.invalid_envelope_id"))
        parts = self.type.split(".", 1)
        if len(parts) != 2 or parts[0] not in ALLOWED_NAMESPACES or not parts[1]:
            raise GatewayProtocolError("invalid_type", t("error.invalid_envelope_type"))
        try:
            parsed = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GatewayProtocolError("invalid_timestamp", t("error.invalid_timestamp")) from exc
        if parsed.tzinfo is None:
            raise GatewayProtocolError("invalid_timestamp", t("error.timestamp_no_tz"))
        for name, value in (("session_id", self.session_id), ("request_id", self.request_id)):
            if value is not None and (not value.strip() or len(value) > 128):
                raise GatewayProtocolError(f"invalid_{name}", f"{name} is invalid.")
        if not isinstance(self.payload, Mapping):
            raise GatewayProtocolError("invalid_payload", t("error.invalid_payload"))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "type": self.type, "timestamp": self.timestamp,
            "session_id": self.session_id, "request_id": self.request_id,
            "payload": dict(self.payload),
        }

    def to_json(self) -> bytes:
        raw = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(raw) > MAX_ENVELOPE_BYTES:
            raise GatewayProtocolError("oversized_frame", t("error.oversized_frame"))
        return raw

    @classmethod
    def from_json(cls, raw: bytes | str) -> GatewayEnvelope:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(encoded) > MAX_ENVELOPE_BYTES:
            raise GatewayProtocolError("oversized_frame", t("error.oversized_frame"))
        try:
            value = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GatewayProtocolError("malformed_frame", t("error.malformed_frame")) from exc
        if not isinstance(value, dict):
            raise GatewayProtocolError("malformed_frame", t("error.malformed_frame_object"))
        required = {"id", "type", "timestamp", "session_id", "request_id", "payload"}
        if set(value) != required:
            raise GatewayProtocolError("malformed_frame", t("error.malformed_frame_fields"))
        if not all(isinstance(value[key], str) for key in ("id", "type", "timestamp")):
            raise GatewayProtocolError("malformed_frame", t("error.malformed_frame_types"))
        for key in ("session_id", "request_id"):
            if value[key] is not None and not isinstance(value[key], str):
                raise GatewayProtocolError("malformed_frame", f"{key} has invalid type.")
        if not isinstance(value["payload"], dict):
            raise GatewayProtocolError("malformed_frame", t("error.invalid_payload"))
        return cls(**value)


__all__ = [
    "ALLOWED_NAMESPACES", "GatewayEnvelope", "GatewayProtocolError",
    "MAX_ENVELOPE_BYTES", "utc_timestamp",
]
