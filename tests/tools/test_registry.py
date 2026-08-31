from __future__ import annotations

import pytest

from acta.safety.types import RiskLevel
from acta.tools import DuplicateToolError, ToolRegistry, ToolSpec, UnknownToolError


def _spec(
    name: str,
    *,
    capabilities: frozenset[str] = frozenset(),
    scopes: frozenset[str] = frozenset(),
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"The {name} tool",
        input_schema={"type": "object"},
        output_schema=None,
        handler=lambda: None,
        risk=RiskLevel.READ,
        capabilities=capabilities,
        scopes=scopes,
    )


def test_register_lookup_contains_and_names() -> None:
    registry = ToolRegistry()
    spec = _spec("search")

    registry.register(spec)

    assert registry.get("search") is spec
    assert registry.contains("search") is True
    assert registry.contains("missing") is False
    assert registry.names() == ("search",)


def test_duplicate_registration_preserves_original() -> None:
    registry = ToolRegistry()
    original = _spec("search")
    registry.register(original)

    with pytest.raises(DuplicateToolError) as exc_info:
        registry.register(_spec("search"))

    assert exc_info.value.code == "duplicate_tool"
    assert exc_info.value.tool_name == "search"
    assert registry.get("search") is original


def test_unknown_lookup_raises_structured_error() -> None:
    registry = ToolRegistry()

    with pytest.raises(UnknownToolError) as exc_info:
        registry.get("missing")

    assert exc_info.value.code == "unknown_tool"
    assert exc_info.value.tool_name == "missing"


def test_unregister_removes_tool_and_unknown_unregister_raises() -> None:
    registry = ToolRegistry()
    registry.register(_spec("search"))

    registry.unregister("search")

    assert not registry.contains("search")
    with pytest.raises(UnknownToolError):
        registry.unregister("search")


def test_list_and_names_use_deterministic_name_order() -> None:
    registry = ToolRegistry()
    for name in ("zebra", "alpha", "middle"):
        registry.register(_spec(name))

    assert registry.names() == ("alpha", "middle", "zebra")
    assert tuple(spec.name for spec in registry.list()) == registry.names()


def test_select_filters_by_all_required_capabilities() -> None:
    registry = ToolRegistry()
    registry.register(_spec("text", capabilities=frozenset({"text"})))
    registry.register(_spec("vision", capabilities=frozenset({"text", "vision"})))

    selected = registry.select(capabilities={"text", "vision"})

    assert tuple(spec.name for spec in selected) == ("vision",)
    assert registry.select(capabilities=set()) == registry.list()


def test_select_filters_by_all_required_scopes() -> None:
    registry = ToolRegistry()
    registry.register(_spec("public", scopes=frozenset({"read"})))
    registry.register(_spec("writer", scopes=frozenset({"read", "write"})))

    selected = registry.select(scopes={"read", "write"})

    assert tuple(spec.name for spec in selected) == ("writer",)
    assert registry.select(scopes=set()) == registry.list()


def test_select_combines_filters_and_keeps_deterministic_order() -> None:
    registry = ToolRegistry()
    registry.register(
        _spec("zeta", capabilities=frozenset({"tools"}), scopes=frozenset({"local"}))
    )
    registry.register(
        _spec("alpha", capabilities=frozenset({"tools"}), scopes=frozenset({"local"}))
    )
    registry.register(
        _spec("cloud", capabilities=frozenset({"tools"}), scopes=frozenset({"cloud"}))
    )

    selected = registry.select(capabilities={"tools"}, scopes={"local"})

    assert tuple(spec.name for spec in selected) == ("alpha", "zeta")
    assert registry.select() == registry.list()
