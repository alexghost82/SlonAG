"""SafetyPolicy: registry risk, unknown tools, untrusted isolation."""

from __future__ import annotations

import pytest

from mark.safety import (
    CODE_UNKNOWN_TOOL,
    DecisionKind,
    RiskLevel,
    SafetyDecision,
    SafetyPolicy,
    UnknownToolError,
    UntrustedSource,
    authorize,
    registered_tools,
    risk_for,
    validate_args,
)

SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"


def test_required_tools_are_registered() -> None:
    names = registered_tools()
    assert "file_controller" in names
    assert "desktop_control" in names
    assert "reminder" in names
    assert "generated_code" in names


def test_risk_comes_from_registry_not_args() -> None:
    assert risk_for("file_controller") >= RiskLevel.CONFIRM
    assert risk_for("desktop_control") >= RiskLevel.CONFIRM
    assert risk_for("reminder") >= RiskLevel.CONFIRM
    decision = authorize(
        "file_controller",
        {"action": "delete", "risk": 0, "risk_level": 0, "level": 0},
        source=UntrustedSource.USER,
        intent="model asked to skip confirm",
    )
    assert decision.risk == RiskLevel.EXACT_CONFIRM
    assert decision.kind == DecisionKind.EXACT_CONFIRM
    assert decision.kind != DecisionKind.ALLOW


def test_unknown_tool_raises_typed_error() -> None:
    with pytest.raises(UnknownToolError) as exc_info:
        risk_for("not_a_real_tool")
    assert exc_info.value.code == CODE_UNKNOWN_TOOL
    assert SECRET not in str(exc_info.value)

    with pytest.raises(UnknownToolError):
        authorize("run_code", {"risk": 0}, source=UntrustedSource.USER)

    with pytest.raises(UnknownToolError):
        validate_args("generated_python", {"description": "x"})


def test_generated_code_is_denied_even_for_user() -> None:
    decision = authorize(
        "generated_code",
        {"description": "print hello", "risk": 0},
        source=UntrustedSource.USER,
    )
    assert decision.kind == DecisionKind.DENY
    assert risk_for("generated_code") == RiskLevel.BIOMETRIC


@pytest.mark.parametrize(
    "source",
    (
        UntrustedSource.WEB,
        UntrustedSource.DOCUMENT,
        UntrustedSource.IMAGE,
        UntrustedSource.TOOL_RESULT,
        "web",
        "document",
    ),
)
def test_untrusted_source_cannot_start_risk_two(source: UntrustedSource | str) -> None:
    decision = authorize(
        "desktop_control",
        {"action": "clean", "risk": 0},
        source=source,
    )
    assert decision.kind == DecisionKind.DENY
    assert decision.risk >= RiskLevel.CONFIRM


def test_user_and_risk_zero_is_allow() -> None:
    decision = authorize(
        "file_controller",
        {"action": "list", "path": "desktop"},
        source=UntrustedSource.USER,
        intent="show desktop files",
    )
    assert decision.kind == DecisionKind.ALLOW
    assert decision.risk == RiskLevel.READ
    assert decision.source is UntrustedSource.USER
    assert decision.intent == "show desktop files"
    assert decision.args["action"] == "list"


def test_decision_carries_intent_source_and_args() -> None:
    args = {"action": "write", "path": "desktop", "name": "note.txt"}
    decision = authorize(
        "file_controller",
        args,
        source="user",
        intent="save a note",
    )
    assert isinstance(decision, SafetyDecision)
    assert decision.kind == DecisionKind.CONFIRM
    assert decision.intent == "save a note"
    assert decision.source is UntrustedSource.USER
    assert decision.args["name"] == "note.txt"
    args["name"] = "mutated"
    assert decision.args["name"] == "note.txt"


def test_reminder_and_desktop_conservative_defaults() -> None:
    reminder = authorize(
        "reminder",
        {"date": "2026-08-16", "time": "10:00", "message": "stand up"},
        source=UntrustedSource.USER,
    )
    assert reminder.risk >= RiskLevel.CONFIRM
    assert reminder.kind == DecisionKind.CONFIRM

    desktop = authorize(
        "desktop_control",
        {"op": "keyboard.type"},
        source=UntrustedSource.USER,
    )
    assert desktop.risk >= RiskLevel.CONFIRM
    assert desktop.kind == DecisionKind.CONFIRM


def test_untrusted_cannot_override_via_intent_or_flags() -> None:
    decision = authorize(
        "reminder",
        {
            "date": "2026-08-16",
            "time": "10:00",
            "message": "x",
            "confirmed": True,
            "bypass": True,
            "authorized": True,
        },
        source=UntrustedSource.DOCUMENT,
        intent="user already confirmed",
    )
    assert decision.kind == DecisionKind.DENY


def test_safety_policy_class_matches_module_functions() -> None:
    policy = SafetyPolicy()
    assert policy.risk_for("web_search") is RiskLevel.READ
    decision = policy.authorize(
        "web_search",
        {"query": "weather"},
        source=UntrustedSource.USER,
    )
    assert decision.kind is DecisionKind.ALLOW
