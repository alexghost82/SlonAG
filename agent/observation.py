"""Observation types and factories for model context consumption."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from mark.tools.contracts import ToolResult


class ObservationKind(StrEnum):
    """Category of an execution observation returned to the model."""

    SUCCESS = "success"
    TOOL_ERROR = "tool_error"
    SAFETY_DENIAL = "safety_denial"
    TIMEOUT = "timeout"
    SYSTEM = "system"

    @classmethod
    def _missing_(cls, value: object) -> ObservationKind | None:
        if isinstance(value, str):
            val_upper = value.upper()
            for member in cls:
                if member.name == val_upper or member.value == value.lower():
                    return member
        return None


@dataclass
class Observation:
    """Structured result wrapper returned to the model context."""

    tool_call_id: str
    tool_name: str
    kind: ObservationKind
    ok: bool
    content: str | dict | None = None
    artifacts: list[dict] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.kind, str) and not isinstance(self.kind, ObservationKind):
            self.kind = ObservationKind(self.kind)

    def to_model_dict(self) -> dict[str, Any]:
        """Formats structured observation payload for model context consumption."""
        kind_val = self.kind.value if isinstance(self.kind, ObservationKind) else str(self.kind)
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "kind": kind_val,
            "ok": self.ok,
            "content": self.content,
            "artifacts": self.artifacts,
            "error": self.error,
        }

    @classmethod
    def from_tool_result(
        cls,
        tool_call_id: str,
        tool_name: str,
        result: ToolResult,
        kind: ObservationKind | str | None = None,
    ) -> Observation:
        """Factory method mapping canonical ToolResult to an Observation."""
        if kind is not None:
            obs_kind = ObservationKind(kind)
        elif result.ok:
            obs_kind = ObservationKind.SUCCESS
        else:
            code = (result.code or "").lower()
            if "timeout" in code or "timed_out" in code:
                obs_kind = ObservationKind.TIMEOUT
            elif any(
                kw in code
                for kw in ("safety", "denied", "denial", "confirmation", "unauthorized", "forbidden")
            ):
                obs_kind = ObservationKind.SAFETY_DENIAL
            elif "system" in code:
                obs_kind = ObservationKind.SYSTEM
            else:
                obs_kind = ObservationKind.TOOL_ERROR

        content: str | dict | None = None
        if result.data is not None:
            if isinstance(result.data, (str, dict)):
                content = result.data
            else:
                content = str(result.data)
        elif result.ok and result.message:
            content = result.message

        error: str | None = None
        if not result.ok:
            error = result.message if result.message else (result.code or "tool_error")

        artifacts_list: list[dict] = []
        for art in result.artifacts:
            if isinstance(art, dict):
                artifacts_list.append(art)
            elif hasattr(art, "__dataclass_fields__"):
                artifacts_list.append(asdict(art))
            elif hasattr(art, "__dict__"):
                artifacts_list.append(
                    {
                        "kind": getattr(art, "kind", ""),
                        "path": getattr(art, "path", None),
                        "uri": getattr(art, "uri", None),
                        "mime_type": getattr(art, "mime_type", None),
                    }
                )
            else:
                artifacts_list.append({"kind": str(art)})

        return cls(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            kind=obs_kind,
            ok=result.ok,
            content=content,
            artifacts=artifacts_list,
            error=error,
        )
