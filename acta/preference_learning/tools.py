"""Tool handlers for the preference learning system.

These handlers are registered in the canonical tool registry and exposed
to the AgentLoop as user-controllable tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from acta.preference_learning.engine import PreferenceEngine
from acta.tools.contracts import ToolResult


def build_preference_tools(base_dir: Path) -> dict[str, dict[str, Any]]:
    """Return the tool specs for preference learning."""
    engine = PreferenceEngine(base_dir)

    return {
        "preference_inspect": {
            "spec": {
                "name": "preference_inspect",
                "description": "Inspect a learned preference by key or list all preferences.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Preference key to inspect (omit to list all)."},
                        "query": {"type": "string", "description": "Search preferences by keyword."},
                    },
                    "additionalProperties": False,
                },
                "risk": 0,
                "read_only": True,
            },
            "handler": _pref_inspect(engine),
        },
        "preference_add": {
            "spec": {
                "name": "preference_add",
                "description": "Add or update a user preference. Used by the agent to learn explicit preferences.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Short identifier, e.g. 'preferred_theme'."},
                        "value": {"type": "string", "description": "The preference value."},
                        "description": {"type": "string", "description": "Human-readable description."},
                        "pref_type": {"type": "string", "description": "explicit|choice|habit|correction|interaction|project_context.", "enum": ["explicit", "choice", "habit", "correction", "interaction", "project_context"]},
                        "action": {"type": "string", "description": "apply|avoid|prompt|inform.", "enum": ["apply", "avoid", "prompt", "inform", "override"]},
                        "priority": {"type": "string", "description": "critical|high|medium|low.", "enum": ["critical", "high", "medium", "low"]},
                        "category": {"type": "string", "description": "e.g. ui, communication, automation."},
                        "tags": {"type": "array", "description": "Tags for filtering.", "items": {"type": "string"}},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
                "risk": 1,
            },
            "handler": _pref_add(engine),
        },
        "preference_edit": {
            "spec": {
                "name": "preference_edit",
                "description": "Edit a preference (create a new version).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Preference key to edit."},
                        "value": {"type": "string", "description": "New value (omit to keep)."},
                        "description": {"type": "string", "description": "New description (omit to keep)."},
                        "category": {"type": "string", "description": "New category (omit to keep)."},
                        "tags": {"type": "array", "description": "New tags (omit to keep).", "items": {"type": "string"}},
                    },
                    "required": ["key"],
                    "additionalProperties": False,
                },
                "risk": 1,
            },
            "handler": _pref_edit(engine),
        },
        "preference_delete": {
            "spec": {
                "name": "preference_delete",
                "description": "Hard-delete a preference. Use preference_forget for soft delete.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Preference key to delete."},
                    },
                    "required": ["key"],
                    "additionalProperties": False,
                },
                "risk": 2,
            },
            "handler": _pref_delete(engine),
        },
        "preference_forget": {
            "spec": {
                "name": "preference_forget",
                "description": "Soft-forget a preference. Retains audit trail but stops using it.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Preference key to forget."},
                    },
                    "required": ["key"],
                    "additionalProperties": False,
                },
                "risk": 2,
            },
            "handler": _pref_forget(engine),
        },
        "preference_reinforce": {
            "spec": {
                "name": "preference_reinforce",
                "description": "Reinforce a preference by boosting its confidence. Call when the user confirms or repeatedly uses a preference.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Preference key to reinforce."},
                        "amount": {"type": "number", "description": "Confidence boost (default 0.1).", "default": 0.1},
                    },
                    "required": ["key"],
                    "additionalProperties": False,
                },
                "risk": 1,
            },
            "handler": _pref_reinforce(engine),
        },
    }


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------

def _pref_inspect(engine: PreferenceEngine):
    def handler(args: Mapping[str, object]) -> ToolResult:
        key = str(args.get("key", ""))
        query = str(args.get("query", ""))

        if query:
            results = engine.search_preferences(query, top_k=20)
            return ToolResult(
                ok=True, code="ok",
                message=f"Found {len(results)} matching preferences.",
                data=results,
            )
        elif key:
            details = engine.inspect_preference(key)
            if "error" in details:
                return ToolResult(ok=False, code="not_found", message=f"Preference not found: {key}")
            return ToolResult(ok=True, code="ok", message=f"Preference: {key}", data=details)
        else:
            prefs = engine.list_all_preferences()
            return ToolResult(
                ok=True, code="ok",
                message=f"Total: {len(prefs)} preference(s).",
                data=prefs,
            )
    return handler


def _pref_add(engine: PreferenceEngine):
    def handler(args: Mapping[str, object]) -> ToolResult:
        from acta.preference_learning.types import LearningSource, PreferenceAction, PreferenceType, PriorityLevel
        key = str(args.get("key", ""))
        value = str(args.get("value", ""))
        if not key or not value:
            return ToolResult(ok=False, code="invalid", message="key and value are required.")

        try:
            pref_type = PreferenceType(str(args.get("pref_type", "explicit")))
        except ValueError:
            pref_type = PreferenceType.EXPLICIT
        try:
            action = PreferenceAction(str(args.get("action", "apply")))
        except ValueError:
            action = PreferenceAction.APPLY
        try:
            priority = PriorityLevel(str(args.get("priority", "medium")))
        except ValueError:
            priority = PriorityLevel.MEDIUM

        tags = args.get("tags")
        if isinstance(tags, list):
            tags = [str(t) for t in tags]

        item = engine.add_preference(
            key=key, value=value,
            description=str(args.get("description", "")),
            pref_type=pref_type, action=action, priority=priority,
            source=LearningSource.MANUAL_ENTRY,
            category=str(args.get("category", "")),
            tags=tags,
        )
        active = item.active
        return ToolResult(
            ok=True, code="ok",
            message=f"Preference '{key}' saved (version {active.version}, confidence {active.confidence:.2f}).",
            data={"key": key, "version": active.version, "confidence": active.confidence},
        )
    return handler


def _pref_edit(engine: PreferenceEngine):
    def handler(args: Mapping[str, object]) -> ToolResult:
        key = str(args.get("key", ""))
        if not key:
            return ToolResult(ok=False, code="invalid", message="key is required.")

        try:
            item = engine.edit_preference(
                key,
                value=str(args["value"]) if "value" in args else None,
                description=str(args["description"]) if "description" in args else None,
                category=str(args["category"]) if "category" in args else None,
                tags=[str(t) for t in args["tags"]] if "tags" in args and isinstance(args["tags"], list) else None,
            )
            active = item.active
            return ToolResult(
                ok=True, code="ok",
                message=f"Preference '{key}' updated to version {active.version}.",
                data={"key": key, "version": active.version},
            )
        except KeyError as e:
            return ToolResult(ok=False, code="not_found", message=str(e))
    return handler


def _pref_delete(engine: PreferenceEngine):
    def handler(args: Mapping[str, object]) -> ToolResult:
        key = str(args.get("key", ""))
        if not key:
            return ToolResult(ok=False, code="invalid", message="key is required.")
        if engine.delete_preference(key):
            return ToolResult(ok=True, code="ok", message=f"Preference '{key}' hard-deleted.")
        return ToolResult(ok=False, code="not_found", message=f"Preference not found: {key}")
    return handler


def _pref_forget(engine: PreferenceEngine):
    def handler(args: Mapping[str, object]) -> ToolResult:
        key = str(args.get("key", ""))
        if not key:
            return ToolResult(ok=False, code="invalid", message="key is required.")
        if engine.forget_preference(key):
            return ToolResult(ok=True, code="ok", message=f"Preference '{key}' forgotten (audit trail preserved).")
        return ToolResult(ok=False, code="not_found", message=f"Preference not found: {key}")
    return handler


def _pref_reinforce(engine: PreferenceEngine):
    def handler(args: Mapping[str, object]) -> ToolResult:
        key = str(args.get("key", ""))
        if not key:
            return ToolResult(ok=False, code="invalid", message="key is required.")
        amount = float(args.get("amount", 0.1))
        decision = engine.reinforce(key, amount=amount)
        return ToolResult(
            ok=True, code="ok",
            message=decision.reason,
            data={
                "action": decision.action,
                "item_id": decision.item_id,
                "old_confidence": decision.old_confidence,
                "new_confidence": decision.new_confidence,
            },
        )
    return handler
