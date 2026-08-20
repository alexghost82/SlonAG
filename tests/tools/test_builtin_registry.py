"""Contract checks for the canonical built-in tool registry."""

from __future__ import annotations

from mark.safety.registry import registered_tools, risk_for, tool_spec
from mark.tools.builtin import build_builtin_registry
from mark.tools.legacy import LEGACY_HANDLERS


EXPECTED_TOOLS = frozenset(
    {
        "read_file",
        "open_app",
        "web_search",
        "browser_control",
        "file_controller",
        "desktop_control",
        "computer_control",
        "computer_settings",
        "cmd_control",
        "screen_process",
        "reminder",
        "weather_report",
        "flight_finder",
        "youtube_video",
        "file_processor",
        "game_updater",
        "send_message",
        "code_helper",
        "dev_agent",
        "agent_task",
    }
)


def test_builtin_registry_contains_each_migrated_tool_once() -> None:
    registry = build_builtin_registry()

    assert frozenset(registry.names()) == EXPECTED_TOOLS
    assert len(registry.names()) == len(EXPECTED_TOOLS)
    assert frozenset(LEGACY_HANDLERS) == EXPECTED_TOOLS


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
    safety_only = registered_tools() - EXPECTED_TOOLS

    assert safety_only == {
        "save_memory",
        "shutdown_slon",
        "shutdown_jarvis",
        "generated_code",
    }
    assert not safety_only.intersection(build_builtin_registry().names())
