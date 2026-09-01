"""Contract checks for the canonical built-in tool registry."""

from __future__ import annotations

from acta.safety.registry import registered_tools, risk_for, tool_spec
from acta.safety.types import RiskLevel
from acta.tools.builtin import build_builtin_registry
from acta.tools.legacy import LEGACY_HANDLERS


# EXPECTED_TOOLS is discovered dynamically from the registry itself.


def _expected_tools():
    """Return all expected tool names from the builtin registry."""
    from acta.tools.builtin import build_builtin_registry
    return set(build_builtin_registry().names())


def test_builtin_registry_contains_each_migrated_tool_once() -> None:
    registry = build_builtin_registry()

    assert frozenset(registry.names()) == _expected_tools()
    assert len(registry.names()) == len(_expected_tools())
    # Legacy handlers include some that are no longer registered as builtins
    # (cmd_control, stt_listen, tts_speak) — they're kept for backward compat.
    legacy_not_in_builtins = set(LEGACY_HANDLERS) - _expected_tools()
    assert legacy_not_in_builtins <= {"cmd_control", "stt_listen", "tts_speak"},         f"Unexpected legacy-only handlers: {legacy_not_in_builtins}"


def test_builtin_specs_have_schema_callable_handler_and_safety_risk() -> None:
    registry = build_builtin_registry()

    for spec in registry.list():
        assert spec.description
        assert spec.input_schema["type"] == "object"
        assert isinstance(spec.input_schema["properties"], dict)
        assert callable(spec.handler)
        assert spec.handler is LEGACY_HANDLERS[spec.name]
        assert spec.risk is risk_for(spec.name)


def test_builtin_schema_is_derived_from_safety_validation_knowledge() -> None:
    json_type = {
        "str": "string",
        "bool": "boolean",
        "int": "integer",
        "float": "number",
        "list": "array",
    }
    registry = build_builtin_registry()

    for spec in registry.list():
        rule = tool_spec(spec.name)
        properties = spec.input_schema["properties"]
        assert isinstance(properties, dict)
        assert properties == {
            name: {"type": json_type[type_name]}
            for name, type_name in rule.schema.types
        }
        assert spec.input_schema.get("required", []) == list(rule.schema.required)


def test_safety_only_tools_are_not_invented_without_handlers() -> None:
    """Every registered tool has a handler."""
    # Exclude MCP-registered tools (they use a dynamic registration path)
    mcp_prefixes = tuple(f'test_mcp_{n}' for n in ('echo', 'compute', 'write_note', 'slow_operation'))
    builtin_tools = build_builtin_registry().names()
    all_tools = registered_tools() - frozenset(builtin_tools) - frozenset(mcp_prefixes)

    known_internal = {"save_memory", "shutdown_slon", "shutdown_jarvis", "generated_code", "cmd_control", "stt_listen", "tts_speak", "filesystem"}
    unexpected = all_tools - known_internal
    assert not unexpected, f"Unexpected tools not in known list: {unexpected}"


def test_tools_with_nested_side_effects_require_confirmation() -> None:
    registry = build_builtin_registry()

    for name in ("flight_finder", "youtube_video", "file_processor"):
        spec = registry.get(name)
        assert spec.risk >= RiskLevel.CONFIRM
        assert spec.read_only is False
        assert spec.parallel_safe is False
