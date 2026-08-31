from __future__ import annotations

import sys
from types import SimpleNamespace

from agent import planner
from acta.safety.types import RiskLevel
from acta.tools.contracts import ToolSpec
from acta.tools.registry import ToolRegistry


def _handler(**_: object) -> None:
    return None


def _registry(*specs: ToolSpec) -> ToolRegistry:
    registry = ToolRegistry()
    for spec in specs:
        registry.register(spec)
    return registry


def _spec(name: str, description: str, schema: dict[str, object]) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema=schema,
        output_schema=None,
        handler=_handler,
        risk=RiskLevel.READ,
    )


def test_catalog_is_deterministic_and_derived_from_canonical_specs() -> None:
    registry = _registry(
        _spec(
            "zeta_tool",
            "The later tool.",
            {"properties": {"z": {"type": "integer"}}, "type": "object"},
        ),
        _spec(
            "alpha_tool",
            "The first tool.",
            {"type": "object", "properties": {"b": {}, "a": {}}},
        ),
    )

    catalog = planner.render_planner_tool_catalog(registry)

    assert catalog.index("alpha_tool") < catalog.index("zeta_tool")
    assert "The first tool." in catalog
    assert 'input_schema: {"properties":{"a":{},"b":{}},"type":"object"}' in catalog


def test_planner_prompt_has_no_independent_tool_schema_catalog() -> None:
    assert "AVAILABLE TOOLS AND THEIR PARAMETERS" not in planner.PLANNER_PROMPT
    assert "app_name: string" not in planner.PLANNER_PROMPT
    assert 'action: "update" | "install"' not in planner.PLANNER_PROMPT
    assert "input_schema" not in planner.PLANNER_PROMPT


def test_create_plan_includes_new_registry_tool_without_prompt_edit(
    monkeypatch,
) -> None:
    registry = _registry(
        _spec(
            "future_builtin",
            "A newly registered built-in.",
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )
    )
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def generate_content(self, user_input: str) -> object:
            captured["user_input"] = user_input
            return SimpleNamespace(text='{"goal":"test","steps":[]}')

    fake_genai = SimpleNamespace(
        configure=lambda **kwargs: captured.update(configure=kwargs),
        GenerativeModel=FakeModel,
    )
    fake_google = SimpleNamespace(generativeai=fake_genai, __path__=[])
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)
    monkeypatch.setattr(planner, "_get_api_key", lambda: "offline-test-key")

    result = planner.create_plan("test", registry=registry)

    instruction = captured["system_instruction"]
    assert isinstance(instruction, str)
    assert "future_builtin" in instruction
    assert "A newly registered built-in." in instruction
    assert '"required":["value"]' in instruction
    assert result == {"goal": "test", "steps": []}
