"""Parameter extraction and normalization.

Takes concrete values from observed steps and extracts parameter slots.
Supports:
  - String values with detected patterns (paths, URLs, emails, numbers)
  - Type inference from value content
  - Required vs optional (based on variability across repetitions)
  - Slot naming convention
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from mark.workflow_learning.types import ParameterSlot, WorkflowCandidate, WorkflowStep


# Pattern detectors
_URL_RE = re.compile(r'^https?://')
_PATH_RE = re.compile(r'^[/~]|^\.?/|^[a-zA-Z]:[\\/]')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_NUMBER_RE = re.compile(r'^-?\d+(\.\d+)?$')
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_BOOL_RE = re.compile(r'^(true|false|yes|no|on|off)$', re.IGNORECASE)


@dataclass(frozen=True)
class _SlotHint:
    """A detected parameter hint from a value."""

    suggested_name: str
    slot_type: str
    is_required: bool = True


class Normalizer:
    """Normalize observed tool arguments into parameter slots.

    Usage:
        normalizer = Normalizer()

        # Single step
        slots = normalizer.extract_slots(step)

        # Multi-step candidate
        slots = normalizer.extract_candidate_slots(candidate)
    """

    # Known field name patterns -> slot type
    _FIELD_PATTERNS: list[tuple[str, str, str]] = [
        (r"path|filepath|file_path|file|source|dest|destination|output", "path", "File path"),
        (r"url|uri|link|endpoint|address", "url", "URL"),
        (r"email|mail|e-mail", "string", "Email address"),
        (r"timeout|delay|interval|duration", "float", "Time value"),
        (r"count|limit|max|min|size|threshold", "int", "Numeric value"),
        (r"verbose|dry_run|force|confirm", "boolean", "Flag"),
        (r"query|search|prompt|text|content|description|name", "string", "Text value"),
        (r"color|hex|theme|style", "string", "Visual value"),
        (r"command|cmd", "string", "Command"),
    ]

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_slots(self, step: WorkflowStep) -> list[ParameterSlot]:
        """Extract parameter slots from a single step's arguments."""
        slots: list[ParameterSlot] = []
        for key, value in step.args.items():
            hint = self._hint_for(key, value)
            slots.append(ParameterSlot(
                name=hint.suggested_name,
                slot_type=hint.slot_type,
                required=hint.is_required,
                description=hint.suggested_name.replace("_", " ").title(),
            ))
        return slots

    def extract_candidate_slots(
        self, candidate: WorkflowCandidate
    ) -> dict[str, list[ParameterSlot]]:
        """Extract parameter slots for all steps in a candidate.

        Returns a dict mapping step index to list of slots.
        Also considers variability across repetitions.
        """
        result: dict[str, list[ParameterSlot]] = {}

        for idx, step in enumerate(candidate.steps):
            base_slots = self.extract_slots(step)

            # Check variability: if the same arg key has different values
            # across repetitions, it's definitely a parameter
            value_sets = self._collect_values(candidate, step)
            for slot in base_slots:
                if slot.name in value_sets and len(value_sets[slot.name]) > 1:
                    slot.required = True
                elif slot.name in value_sets and len(value_sets[slot.name]) == 1:
                    slot.default = list(value_sets[slot.name])[0]

            result[str(idx)] = base_slots

        return result

    def infer_template(self, candidate: WorkflowCandidate) -> list[dict[str, Any]]:
        """Convert a candidate's steps into argument templates.

        Each step's args dict is converted so that concrete values
        are replaced by slot references: ``"${slot_name}"``.

        Returns a list of template dicts, one per step.
        """
        templates: list[dict[str, Any]] = []

        for step in candidate.steps:
            template: dict[str, Any] = {}
            for key, value in step.args.items():
                slot_name = self._key_to_slot_name(key)
                template[slot_name] = {"_slot": slot_name, "_type": self._value_type(value)}
            templates.append(template)

        return templates

    def infer_step_descriptors(
        self, candidate: WorkflowCandidate
    ) -> list[dict[str, Any]]:
        """Build step descriptors from a parameterized candidate.

        Returns a list of dicts ready to serialize as StepDescriptor.
        """
        from mark.safety import risk_for

        descriptors = []
        for idx, step in enumerate(candidate.steps):
            slot_names = [s.name for s in self.extract_slots(step)]
            descriptors.append({
                "tool_name": step.tool_name,
                "arg_template": self.infer_template(candidate)[idx] if idx < len(self.infer_template(candidate)) else {},
                "required_slots": slot_names,
                "safety_risk": risk_for(step.tool_name),
            })

        return descriptors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hint_for(key: str, value: Any) -> _SlotHint:
        """Detect the best parameter slot for a key-value pair."""
        if value is None:
            return _SlotHint(suggested_name=key, slot_type="string", is_required=False)

        if isinstance(value, bool):
            return _SlotHint(suggested_name=key, slot_type="boolean", is_required=True)

        if isinstance(value, int):
            return _SlotHint(suggested_name=key, slot_type="int", is_required=True)

        if isinstance(value, float):
            return _SlotHint(suggested_name=key, slot_type="float", is_required=True)

        if isinstance(value, str):
            return _detect_string_type(key, value)

        if isinstance(value, (list, dict)):
            return _SlotHint(suggested_name=key, slot_type="string", is_required=True)

        return _SlotHint(suggested_name=key, slot_type="string", is_required=True)

    @staticmethod
    def _key_to_slot_name(key: str) -> str:
        """Convert an argument key to a slot name."""
        name = key.lower().strip()
        # Replace separators with underscores
        name = re.sub(r'[-_.\s]+', '_', name)
        name = re.sub(r'[^a-z0-9_]', '', name)
        # Strip leading underscores
        name = name.strip('_')
        return name or "param"

    @staticmethod
    def _value_type(value: Any) -> str:
        """Infer the slot type from a value."""
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "string"
        return "string"

    def _collect_values(
        self, candidate: WorkflowCandidate, step: WorkflowStep
    ) -> dict[str, set[str]]:
        """Collect all values for each arg key across candidate steps.

        This is used to detect variability: if the same key has different
        values in different repetitions, it should be a parameter.
        """
        value_sets: dict[str, set[str]] = defaultdict(set)
        for s in candidate.steps:
            if s.tool_name == step.tool_name:
                for k, v in s.args.items():
                    value_sets[k].add(str(v))
        return dict(value_sets)


def _detect_string_type(key: str, value: str) -> _SlotHint:
    """Detect the parameter type for a string value."""
    if _UUID_RE.match(value):
        return _SlotHint(suggested_name=key, slot_type="string", is_required=True)
    if _URL_RE.match(value):
        return _SlotHint(suggested_name=key, slot_type="url", is_required=True)
    if _PATH_RE.match(value):
        return _SlotHint(suggested_name=key, slot_type="path", is_required=True)
    if _EMAIL_RE.match(value):
        return _SlotHint(suggested_name=key, slot_type="string", is_required=True)
    if _NUMBER_RE.match(value):
        if '.' in value:
            return _SlotHint(suggested_name=key, slot_type="float", is_required=True)
        return _SlotHint(suggested_name=key, slot_type="int", is_required=True)
    if _BOOL_RE.match(value):
        return _SlotHint(suggested_name=key, slot_type="boolean", is_required=True)

    # Check field name patterns
    value_lower = value.lower()
    for pattern, slot_type, desc in Normalizer._FIELD_PATTERNS:
        if pattern in key.lower() or pattern in value_lower:
            return _SlotHint(suggested_name=key, slot_type=slot_type, is_required=True)

    return _SlotHint(suggested_name=key, slot_type="string", is_required=True)
