"""Tests for canonical tool contracts."""

from dataclasses import FrozenInstanceError

import pytest

from mark.safety import RiskLevel
from mark.tools import ArtifactRef, ToolResult, ToolSpec


def _handler(**_: object) -> str:
    return "ok"


def test_valid_tool_spec() -> None:
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }
    spec = ToolSpec(
        name="documents.search-v2",
        description="Search documents",
        input_schema=input_schema,
        output_schema={"type": "object"},
        handler=_handler,
        risk=RiskLevel.READ,
        capabilities=frozenset({"documents"}),
        scopes=frozenset({"local"}),
    )

    assert spec.name == "documents.search-v2"
    assert spec.handler is _handler
    assert spec.timeout_seconds == 30.0
    assert not spec.idempotent
    assert not spec.cancellable


@pytest.mark.parametrize("name", ["", "UPPER", "has space", "slash/name", "tool!"])
def test_tool_spec_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="tool name"):
        ToolSpec(name, "Invalid", {}, None, _handler, RiskLevel.READ)


@pytest.mark.parametrize("timeout", [0.0, -0.1, float("nan")])
def test_tool_spec_rejects_non_positive_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        ToolSpec("valid", "Valid", {}, None, _handler, RiskLevel.READ, timeout)


def test_tool_spec_rejects_non_callable_handler() -> None:
    with pytest.raises(TypeError, match="handler"):
        ToolSpec("valid", "Valid", {}, None, None, RiskLevel.READ)  # type: ignore[arg-type]


def test_tool_result_is_immutable() -> None:
    result = ToolResult(ok=True, code="ok")

    with pytest.raises(FrozenInstanceError):
        result.ok = False  # type: ignore[misc]


def test_artifact_representation() -> None:
    artifact = ArtifactRef(
        kind="document",
        path="/tmp/report.pdf",
        uri="file:///tmp/report.pdf",
        mime_type="application/pdf",
    )
    result = ToolResult(ok=True, code="created", artifacts=(artifact,))

    assert result.artifacts == (artifact,)
    assert artifact.kind == "document"
    assert artifact.path == "/tmp/report.pdf"
    assert artifact.uri == "file:///tmp/report.pdf"
    assert artifact.mime_type == "application/pdf"
