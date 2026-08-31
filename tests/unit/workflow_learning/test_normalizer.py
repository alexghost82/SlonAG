"""Tests for workflow_learning.normalizer."""

import pytest

from acta.workflow_learning.normalizer import Normalizer, _detect_string_type
from acta.workflow_learning.types import ParameterSlot, WorkflowCandidate, WorkflowStep


class TestNormalizer:
    """Tests for Normalizer class."""

    def test_extract_string_slot(self):
        normalizer = Normalizer()
        step = WorkflowStep(
            tool_name="file_write",
            args={"path": "/tmp/test.txt", "content": "hello"},
            ok=True,
        )
        slots = normalizer.extract_slots(step)
        assert len(slots) == 2
        names = [s.name for s in slots]
        assert "path" in names

    def test_detect_url_slot(self):
        step = WorkflowStep(tool_name="url_fetch", args={"url": "https://example.com"}, ok=True)
        slots = Normalizer().extract_slots(step)
        url_slot = next(s for s in slots if s.name == "url")
        assert url_slot.slot_type == "url"

    def test_detect_path_slot(self):
        step = WorkflowStep(tool_name="file_read", args={"path": "/home/user/data.csv"}, ok=True)
        slots = Normalizer().extract_slots(step)
        path_slot = next(s for s in slots if s.name == "path")
        assert path_slot.slot_type == "path"

    def test_detect_int_slot(self):
        step = WorkflowStep(tool_name="shell_exec", args={"timeout": 30}, ok=True)
        slots = Normalizer().extract_slots(step)
        timeout_slot = next(s for s in slots if s.name == "timeout")
        assert timeout_slot.slot_type == "int"  # integers detected as int

    def test_detect_bool_slot(self):
        step = WorkflowStep(tool_name="shell_exec", args={"kill_tree": True}, ok=True)
        slots = Normalizer().extract_slots(step)
        kill_slot = next(s for s in slots if s.name == "kill_tree")
        assert kill_slot.slot_type == "boolean"

    def test_extract_candidate_slots(self):
        normalizer = Normalizer()
        candidate = WorkflowCandidate(
            name="test",
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"command": "ls -la /tmp"}, ok=True),
            ],
        )
        result = normalizer.extract_candidate_slots(candidate)
        assert str(0) in result
        assert len(result[str(0)]) > 0

    def test_infer_template(self):
        normalizer = Normalizer()
        candidate = WorkflowCandidate(
            name="test",
            steps=[
                WorkflowStep(
                    tool_name="file_write",
                    args={"path": "/tmp/output.txt", "content": "data"},
                    ok=True,
                ),
            ],
        )
        templates = normalizer.infer_template(candidate)
        assert len(templates) == 1
        assert "_slot" in templates[0].get("path", {})

    def test_key_to_slot_name(self):
        assert Normalizer._key_to_slot_name("file_path") == "file_path"
        assert Normalizer._key_to_slot_name("file-path") == "file_path"
        assert Normalizer._key_to_slot_name("file.path") == "file_path"
        assert Normalizer._key_to_slot_name("  Cmd  ") == "cmd"

    def test_value_type(self):
        assert Normalizer._value_type("hello") == "string"
        assert Normalizer._value_type(42) == "int"
        assert Normalizer._value_type(3.14) == "float"
        assert Normalizer._value_type(True) == "boolean"
        assert Normalizer._value_type(None) == "string"


class TestDetectStringType:
    """Tests for _detect_string_type helper."""

    def test_url(self):
        hint = _detect_string_type("url", "https://example.com")
        assert hint.slot_type == "url"

    def test_path(self):
        hint = _detect_string_type("path", "/home/user/file.txt")
        assert hint.slot_type == "path"

    def test_email(self):
        hint = _detect_string_type("email", "user@example.com")
        assert hint.slot_type == "string"

    def test_number(self):
        hint = _detect_string_type("count", "42")
        assert hint.slot_type == "int"

    def test_float(self):
        hint = _detect_string_type("timeout", "3.14")
        assert hint.slot_type == "float"

    def test_uuid(self):
        hint = _detect_string_type("id", "550e8400-e29b-41d4-a716-446655440000")
        assert hint.slot_type == "string"

    def test_field_pattern(self):
        hint = _detect_string_type("query", "hello world")
        assert hint.slot_type == "string"

    def test_plain_string(self):
        hint = _detect_string_type("name", "hello world")
        assert hint.slot_type == "string"
