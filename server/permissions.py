"""Permission gates for Desktop Control API actions.

``can(principal, action)`` answers authorization for paired devices.
Mutating tool-like actions expose ``requires_safety_approval=True`` so routes
can enforce SafetyPolicy without this module executing tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from server.auth import DevicePrincipal

# Actions that map to Desktop Control API capabilities.
ACTION_STATUS_READ = "status.read"
ACTION_EVENTS_SUBSCRIBE = "events.subscribe"
ACTION_CHAT_WRITE = "chat.write"
ACTION_TASKS_LIST = "tasks.list"
ACTION_TASKS_CREATE = "tasks.create"
ACTION_TASKS_CANCEL = "tasks.cancel"
ACTION_APPROVALS_LIST = "approvals.list"
ACTION_APPROVALS_DECIDE = "approvals.decide"
ACTION_MEMORY_GET = "memory.get"
ACTION_MEMORY_DELETE = "memory.delete"
ACTION_MODELS_LIST = "models.list"
ACTION_MODELS_ACTIVATE = "models.activate"
ACTION_SCREEN_CAPTURE = "screen.capture"
ACTION_FILES_READ = "files.read"
ACTION_FILES_WRITE = "files.write"
ACTION_PAIRING_REVOKE = "pairing.revoke"

# Optional scope names a principal may carry; empty scopes = full paired access.
SCOPE_FULL = "desktop.full"


@dataclass(frozen=True)
class ActionSpec:
    """Static metadata for one API action."""

    action: str
    requires_safety_approval: bool
    description: str = ""


@dataclass(frozen=True)
class PermissionDecision:
    """Result of a permission check for routes / approval gating."""

    action: str
    allowed: bool
    requires_safety_approval: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "allowed": self.allowed,
            "requires_safety_approval": self.requires_safety_approval,
        }


_ACTION_SPECS: dict[str, ActionSpec] = {
    ACTION_STATUS_READ: ActionSpec(
        ACTION_STATUS_READ,
        requires_safety_approval=False,
        description="Read desktop status",
    ),
    ACTION_EVENTS_SUBSCRIBE: ActionSpec(
        ACTION_EVENTS_SUBSCRIBE,
        requires_safety_approval=False,
        description="Subscribe to event stream",
    ),
    ACTION_CHAT_WRITE: ActionSpec(
        ACTION_CHAT_WRITE,
        requires_safety_approval=True,
        description="Send chat that may trigger tools",
    ),
    ACTION_TASKS_LIST: ActionSpec(
        ACTION_TASKS_LIST,
        requires_safety_approval=False,
        description="List tasks",
    ),
    ACTION_TASKS_CREATE: ActionSpec(
        ACTION_TASKS_CREATE,
        requires_safety_approval=True,
        description="Create a task that may run tools",
    ),
    ACTION_TASKS_CANCEL: ActionSpec(
        ACTION_TASKS_CANCEL,
        requires_safety_approval=False,
        description="Cancel a task",
    ),
    ACTION_APPROVALS_LIST: ActionSpec(
        ACTION_APPROVALS_LIST,
        requires_safety_approval=False,
        description="List pending approvals",
    ),
    ACTION_APPROVALS_DECIDE: ActionSpec(
        ACTION_APPROVALS_DECIDE,
        requires_safety_approval=False,
        description="Decide an existing approval",
    ),
    ACTION_MEMORY_GET: ActionSpec(
        ACTION_MEMORY_GET,
        requires_safety_approval=False,
        description="Read memory entries",
    ),
    ACTION_MEMORY_DELETE: ActionSpec(
        ACTION_MEMORY_DELETE,
        requires_safety_approval=True,
        description="Delete memory entries",
    ),
    ACTION_MODELS_LIST: ActionSpec(
        ACTION_MODELS_LIST,
        requires_safety_approval=False,
        description="List models",
    ),
    ACTION_MODELS_ACTIVATE: ActionSpec(
        ACTION_MODELS_ACTIVATE,
        requires_safety_approval=False,
        description="Activate a model",
    ),
    ACTION_SCREEN_CAPTURE: ActionSpec(
        ACTION_SCREEN_CAPTURE,
        requires_safety_approval=True,
        description="Capture screen metadata / image",
    ),
    ACTION_FILES_READ: ActionSpec(
        ACTION_FILES_READ,
        requires_safety_approval=False,
        description="Read allowlisted files",
    ),
    ACTION_FILES_WRITE: ActionSpec(
        ACTION_FILES_WRITE,
        requires_safety_approval=True,
        description="Write allowlisted files via tools",
    ),
    ACTION_PAIRING_REVOKE: ActionSpec(
        ACTION_PAIRING_REVOKE,
        requires_safety_approval=False,
        description="Revoke a paired device",
    ),
}


def known_actions() -> frozenset[str]:
    """Return the set of recognized action names."""
    return frozenset(_ACTION_SPECS)


def action_spec(action: str) -> ActionSpec | None:
    """Return the static spec for ``action``, or None if unknown."""
    return _ACTION_SPECS.get(action)


def requires_safety_approval(action: str) -> bool:
    """True when the action is mutating/tool-like and must not bypass SafetyPolicy."""
    spec = _ACTION_SPECS.get(action)
    if spec is None:
        # Unknown mutating-looking actions fail closed toward approval.
        return True
    return spec.requires_safety_approval


def can(principal: DevicePrincipal, action: str) -> bool:
    """Return whether ``principal`` may perform ``action``.

    Paired devices (authenticated principals) may perform all known actions.
    Unknown actions are denied. Optional scopes, when present, must include
    ``desktop.full`` or the exact action name.
    """
    if not isinstance(principal, DevicePrincipal):
        return False
    if not principal.device_id:
        return False
    if action not in _ACTION_SPECS:
        return False
    if principal.scopes:
        if SCOPE_FULL in principal.scopes or action in principal.scopes:
            return True
        return False
    return True


def decide(principal: DevicePrincipal, action: str) -> PermissionDecision:
    """Permission check plus safety-approval flag for route handlers."""
    allowed = can(principal, action)
    return PermissionDecision(
        action=action,
        allowed=allowed,
        requires_safety_approval=requires_safety_approval(action) if allowed else False,
    )


def safety_flag_for_action(action: str) -> Mapping[str, object]:
    """Expose a route-friendly flag without executing tools.

    Does not call ``mark.safety.authorize`` — callers pass a tool name to
    SafetyPolicy separately when they have one.
    """
    return {
        "action": action,
        "requires_safety_approval": requires_safety_approval(action),
    }


__all__ = [
    "ACTION_APPROVALS_DECIDE",
    "ACTION_APPROVALS_LIST",
    "ACTION_CHAT_WRITE",
    "ACTION_EVENTS_SUBSCRIBE",
    "ACTION_FILES_READ",
    "ACTION_FILES_WRITE",
    "ACTION_MEMORY_DELETE",
    "ACTION_MEMORY_GET",
    "ACTION_MODELS_ACTIVATE",
    "ACTION_MODELS_LIST",
    "ACTION_PAIRING_REVOKE",
    "ACTION_SCREEN_CAPTURE",
    "ACTION_STATUS_READ",
    "ACTION_TASKS_CANCEL",
    "ACTION_TASKS_CREATE",
    "ACTION_TASKS_LIST",
    "SCOPE_FULL",
    "ActionSpec",
    "PermissionDecision",
    "action_spec",
    "can",
    "decide",
    "known_actions",
    "requires_safety_approval",
    "safety_flag_for_action",
]
