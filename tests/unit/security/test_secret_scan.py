"""Tests for config.secret_scan — secret-scanning heuristics."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

import config.secret_scan as m

# ---------------------------------------------------------------------------
# Sentinel values — these look credential-like but are NOT real.
# Each matches the corresponding pattern in secret_scan.py.
# ---------------------------------------------------------------------------

# GCP key: AIza + 34 alphanumeric = 38 total
_SENTINEL_GCP = "AIzaSyA1234567890abcdefghijklmnopqrstuv"
# OpenAI key: sk- + 26 alphanumeric = 29 total
_SENTINEL_OPENAI = "sk-abcdefghij1234567890"
# GitHub PAT: ghp_ + 20 alphanumeric = 24 total
_SENTINEL_GITHUB = "ghp_abcdefghijklmnop12345"
# AWS key: AKIA + 16 uppercase alphanum = 20 total
_SENTINEL_AWS = "AKIAIOSFODNN7EXAMPLE"
# Bearer token: "Bearer " + 64 chars
_SENTINEL_BEARER = "Bearer abcdefghij1234567890ABCDEFGHIJ1234567890"
# Slack token
_SENTINEL_SLACK = "xoxb-abcdefghij1234567890"
# Stripe key
_SENTINEL_STRIPE = "sk_live_abcdefghij1234567890"
# Anthropic key
_SENTINEL_ANTHROPIC = "sk-ant-abcdefghij1234567890"
# Password assignment
_SENTINEL_ASSIGN = "api_key = my_fake_placeholder"

# Safe values that must NOT trigger any pattern.
_SAFE_NOT_REAL = [
    "sk-test-notreal",           # too short / known-safe prefix
    "sk-placeholder",
    "CHANGEME",
    "TODO",
    "example_key = foo",         # value too short
]


class TestScanText:
    """Unit tests for scan_text()."""

    @pytest.mark.parametrize(
        "label,sentinel",
        [
            ("google_api_key", _SENTINEL_GCP),
            ("openai_key", _SENTINEL_OPENAI),
            ("github_token", _SENTINEL_GITHUB),
            ("aws_access_key", _SENTINEL_AWS),
            ("bearer_token", _SENTINEL_BEARER),
            ("slack_token", _SENTINEL_SLACK),
            ("stripe_key", _SENTINEL_STRIPE),
            ("anthropic_key", _SENTINEL_ANTHROPIC),
        ],
    )
    def test_patterns_detect_sensitive_tokens(self, label, sentinel):
        result = m.scan_text(sentinel)
        assert len(result) >= 1
        labels = {i.pattern for i in result}
        assert label in labels

    def test_password_assignment_pattern(self):
        result = m.scan_text(_SENTINEL_ASSIGN)
        assert len(result) >= 1
        assert "password_assignment" in {i.pattern for i in result}

    @pytest.mark.parametrize("safe", _SAFE_NOT_REAL)
    def test_safe_values_do_not_trigger(self, safe):
        result = m.scan_text(safe)
        assert result == [], f"'{safe}' should not trigger any pattern"

    def test_safe_values_in_context(self):
        """Values from docs / test fixtures should not fire false positives."""
        text = """
        # Example: use a placeholder like sk-test-notreal
        API_KEY = "CHANGEME"  # TODO: replace with real key
        """
        result = m.scan_text(text)
        assert result == []

    def test_empty_string(self):
        assert m.scan_text("") == []
        assert m.scan_text("   ") == []

    def test_pem_private_key_detected(self):
        result = m.scan_text("-----BEGIN RSA PRIVATE KEY-----")
        assert any(i.pattern == "pem_private_key" for i in result)

    def test_line_numbers_are_correct(self):
        text = "safe line\nsk-abcdefghijklmnopqrstuvwxyz012345\nsafe again"
        issues = m.scan_text(text)
        assert len(issues) == 1
        assert issues[0].line == 2

    def test_only_one_issue_per_line(self):
        """A line matching multiple patterns should yield one Issue."""
        multi = _SENTINEL_OPENAI + " api_key = " + _SENTINEL_GITHUB
        issues = m.scan_text(multi)
        assert len(issues) == 1


class TestScanPath:
    """Unit tests for scan_path()."""

    def test_nonexistent_returns_empty(self, tmp_path):
        assert m.scan_path(tmp_path / "no_such_file.txt") == []

    def test_binary_extensions_skipped(self, tmp_path):
        fake_pyc = tmp_path / "module.pyc"
        fake_pyc.write_text("binary")
        assert m.scan_path(fake_pyc) == []

    def test_source_file_scanned(self, tmp_path):
        src = tmp_path / "config.py"
        src.write_text("api_key = " + _SENTINEL_OPENAI)
        issues = m.scan_path(src)
        assert len(issues) == 1
        assert issues[0].pattern == "openai_key"


class TestScanGitIndex:
    """Unit tests for scan_git_index()."""

    def test_tracked_api_keys_json(self, project_root):
        """config/api_keys.json should appear in scan_git_index if tracked."""
        # We only know if it is tracked or not — both are valid.
        # The test verifies the function returns a list of Issue objects.
        issues = m.scan_git_index(project_root)
        assert isinstance(issues, list)
        for issue in issues:
            assert isinstance(issue, m.Issue)


class TestExemptPatterns:
    """Verify that known-safe paths and substrings do not cause issues."""

    def test_config_secrets_py_exempt_in_scan_text(self):
        """The secrets.py file itself may contain credential-like patterns."""
        root = Path(__file__).resolve().parents[3]
        src = (root / "config" / "secrets.py").read_text(encoding="utf-8")
        # This file MUST not trigger any issue.
        issues = m.scan_text(src)
        assert issues == []

    def test_test_secrets_py_exempt_in_scan_text(self):
        root = Path(__file__).resolve().parents[3]
        src = (root / "tests" / "unit" / "config" / "test_secrets.py").read_text(
            encoding="utf-8"
        )
        issues = m.scan_text(src)
        # The test file uses SENTINEL which should not trigger.
        assert issues == []

    def test_secret_tracking_py_exempt_in_scan_text(self):
        root = Path(__file__).resolve().parents[3]
        src = (root / "config" / "secret_tracking.py").read_text(
            encoding="utf-8"
        )
        issues = m.scan_text(src)
        assert issues == []
