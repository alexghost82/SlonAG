from __future__ import annotations

import pytest

from acta.safety.types import RiskLevel
from acta.tools.contracts import ToolSpec
from acta.tools.exporters import export_gemini_tools, export_openai_tools, export_tools


def _handler(arguments: object) -> object:
    return arguments


def _spec(name: str = "file_controller") -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Manage a file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "operation": {"type": "string", "enum": ["read", "write"]},
            },
            "required": ["path", "operation"],
        },
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        handler=_handler,
        risk=RiskLevel.READ,
    )


def test_openai_export_uses_function_format_without_output_schema() -> None:
    exported = export_openai_tools([_spec()])

    assert exported == [
        {
            "type": "function",
            "function": {
                "name": "file_controller",
                "description": "Manage a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "operation": {"type": "string", "enum": ["read", "write"]},
                    },
                    "required": ["path", "operation"],
                },
            },
        }
    ]
    assert "output_schema" not in exported[0]["function"]  # type: ignore[operator]


def test_gemini_export_is_plain_function_declaration() -> None:
    exported = export_gemini_tools([_spec()])

    assert exported == [
        {
            "name": "file_controller",
            "description": "Manage a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "operation": {"type": "string", "enum": ["read", "write"]},
                },
                "required": ["path", "operation"],
            },
        }
    ]


def test_gemini_export_removes_live_unsupported_additional_properties() -> None:
    spec = _spec()
    schema = dict(spec.input_schema)
    schema["additionalProperties"] = True
    schema["properties"] = {
        "nested": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
        }
    }
    spec = ToolSpec(
        name=spec.name,
        description=spec.description,
        input_schema=schema,
        output_schema=spec.output_schema,
        handler=spec.handler,
        risk=spec.risk,
    )

    exported = export_gemini_tools([spec])
    rendered = repr(exported)

    assert "additionalProperties" not in rendered
    assert schema["additionalProperties"] is True


def test_exports_preserve_sequence_and_do_not_mutate_schema() -> None:
    specs = [_spec("z_tool"), _spec("a_tool")]
    original_schema = specs[0].input_schema
    exported = export_openai_tools(specs)

    assert [item["function"]["name"] for item in exported] == ["z_tool", "a_tool"]  # type: ignore[index]
    parameters = exported[0]["function"]["parameters"]  # type: ignore[index]
    assert isinstance(parameters, dict)
    properties = parameters["properties"]
    assert isinstance(properties, dict)
    properties["added"] = {"type": "number"}
    assert "added" not in original_schema["properties"]  # type: ignore[operator]


@pytest.mark.parametrize(
    "provider_id",
    [
        "openai",
        "openrouter",
        "ollama",
        "llama_cpp",
        "llama.cpp",
        "local",
        "openai_compatible",
    ],
)
def test_openai_compatible_providers_share_export(provider_id: str) -> None:
    specs = [_spec()]
    assert export_tools(provider_id, specs) == export_openai_tools(specs)


def test_generic_export_routes_gemini() -> None:
    specs = [_spec()]
    assert export_tools(" GEMINI ", specs) == export_gemini_tools(specs)


def test_unknown_provider_has_clear_error() -> None:
    with pytest.raises(ValueError, match="unsupported tool schema provider"):
        export_tools("mystery", [_spec()])
