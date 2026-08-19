"""Construction of the canonical registry for Slon's legacy built-in tools."""

from __future__ import annotations

from collections.abc import Mapping

from mark.safety.registry import SafetyRule, tool_spec as safety_rule
from mark.tools.contracts import ToolSpec
from mark.tools.legacy import LEGACY_HANDLERS
from mark.tools.registry import ToolRegistry


_DESCRIPTIONS: Mapping[str, str] = {
    "open_app": "Open an installed application.",
    "web_search": "Search the web for information.",
    "browser_control": "Control the web browser.",
    "file_controller": "Read, create, organize, or modify files.",
    "desktop_control": "Inspect or control the desktop environment.",
    "computer_control": "Control supported computer operations.",
    "computer_settings": "Inspect or change computer settings.",
    "cmd_control": "Run a supported local command task.",
    "screen_process": "Process visible screen text.",
    "reminder": "List, create, update, or cancel reminders.",
    "weather_report": "Get a weather report for a city.",
    "flight_finder": "Find flights matching an itinerary.",
    "youtube_video": "Find or process a YouTube video.",
    "file_processor": "Process a file according to an instruction.",
    "game_updater": "Inspect, install, or update games.",
    "send_message": "Send a message through a supported platform.",
    "code_helper": "Perform a supported code operation.",
    "dev_agent": "Run a scoped software development task.",
    "agent_task": "Submit a goal to the legacy agent task queue.",
}

_JSON_TYPES: Mapping[str, str] = {
    "str": "string",
    "bool": "boolean",
    "int": "integer",
    "float": "number",
    "list": "array",
}


def _input_schema(rule: SafetyRule) -> dict[str, object]:
    """Translate the safety validator's argument knowledge to JSON Schema."""
    properties = {
        name: {"type": _JSON_TYPES[type_name]}
        for name, type_name in rule.schema.types
    }
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        # Safety validation intentionally permits additional legacy arguments.
        "additionalProperties": True,
    }
    if rule.schema.required:
        schema["required"] = list(rule.schema.required)
    return schema


def build_builtin_registry() -> ToolRegistry:
    """Build a fresh registry containing each migrated legacy tool once."""
    registry = ToolRegistry()
    for name, handler in LEGACY_HANDLERS.items():
        rule = safety_rule(name)
        registry.register(
            ToolSpec(
                name=name,
                description=_DESCRIPTIONS[name],
                input_schema=_input_schema(rule),
                output_schema=None,
                handler=handler,
                risk=rule.risk,
            )
        )
    return registry


__all__ = ["build_builtin_registry"]
