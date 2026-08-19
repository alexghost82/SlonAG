"""Unit tests for Desktop Control API permission gates."""

from __future__ import annotations

from server.auth import DevicePrincipal
from server.permissions import (
    ACTION_APPROVALS_DECIDE,
    ACTION_CHAT_WRITE,
    ACTION_MEMORY_DELETE,
    ACTION_STATUS_READ,
    ACTION_TASKS_CREATE,
    SCOPE_FULL,
    can,
    decide,
    known_actions,
    requires_safety_approval,
    safety_flag_for_action,
)


def _principal(*, scopes: frozenset[str] | None = None) -> DevicePrincipal:
    return DevicePrincipal(
        device_id="dev_1",
        device_name="phone",
        scopes=scopes if scopes is not None else frozenset(),
    )


def test_permission_matrix_basics() -> None:
    principal = _principal()
    assert can(principal, ACTION_STATUS_READ) is True
    assert can(principal, ACTION_CHAT_WRITE) is True
    assert can(principal, ACTION_APPROVALS_DECIDE) is True
    assert can(principal, ACTION_MEMORY_DELETE) is True
    assert can(principal, "unknown.action") is False
    assert can(principal, "") is False


def test_empty_device_id_denied() -> None:
    principal = DevicePrincipal(device_id="")
    assert can(principal, ACTION_STATUS_READ) is False


def test_scoped_principal_requires_matching_scope() -> None:
    limited = _principal(scopes=frozenset({ACTION_STATUS_READ}))
    assert can(limited, ACTION_STATUS_READ) is True
    assert can(limited, ACTION_CHAT_WRITE) is False

    full = _principal(scopes=frozenset({SCOPE_FULL}))
    assert can(full, ACTION_CHAT_WRITE) is True
    assert can(full, ACTION_MEMORY_DELETE) is True


def test_mutating_tool_like_actions_require_safety_approval() -> None:
    assert requires_safety_approval(ACTION_CHAT_WRITE) is True
    assert requires_safety_approval(ACTION_MEMORY_DELETE) is True
    assert requires_safety_approval(ACTION_TASKS_CREATE) is True
    assert requires_safety_approval(ACTION_STATUS_READ) is False
    assert requires_safety_approval(ACTION_APPROVALS_DECIDE) is False


def test_decide_exposes_safety_flag_without_executing_tools() -> None:
    principal = _principal()
    decision = decide(principal, ACTION_CHAT_WRITE)
    assert decision.allowed is True
    assert decision.requires_safety_approval is True
    assert decision.to_dict()["requires_safety_approval"] is True

    status = decide(principal, ACTION_STATUS_READ)
    assert status.allowed is True
    assert status.requires_safety_approval is False

    unknown = decide(principal, "nope")
    assert unknown.allowed is False
    assert unknown.requires_safety_approval is False


def test_safety_flag_for_action_is_route_friendly() -> None:
    flag = safety_flag_for_action(ACTION_MEMORY_DELETE)
    assert flag["action"] == ACTION_MEMORY_DELETE
    assert flag["requires_safety_approval"] is True
    # Must not imply tool execution happened.
    assert "authorized" not in flag
    assert "tool_name" not in flag


def test_known_actions_include_spec_examples() -> None:
    actions = known_actions()
    assert ACTION_STATUS_READ in actions
    assert ACTION_CHAT_WRITE in actions
    assert ACTION_APPROVALS_DECIDE in actions
    assert ACTION_MEMORY_DELETE in actions
