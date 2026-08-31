"""Tests for config.secret_tracking — tracking status of secret files."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

import config.secret_tracking as m
from config.secret_tracking import TrackingStatus


class TestCheck:
    """Tests for the check() function."""

    def test_nonexistent_returns_defaults(self, tmp_path):
        fake = tmp_path / "fake_keys.json"
        status = m.check(fake)
        assert status.exists is False
        assert status.is_tracked_by_git is False
        assert status.mode_octal == ""
        assert status.has_read_permissions is False

    def test_existing_file_is_read(self, tmp_path):
        secret = tmp_path / "api_keys.json"
        secret.write_text("{}")
        secret.chmod(0o600)

        status = m.check(secret)
        assert status.exists is True
        assert status.mode_octal == "0o600"
        assert status.has_read_permissions is True

    def test_unreadable_file(self, tmp_path):
        secret = tmp_path / "api_keys.json"
        secret.write_text("{}")
        secret.chmod(0o000)

        try:
            status = m.check(secret)
            # Permission bits may vary by OS / user
            assert status.exists is True
        finally:
            secret.chmod(0o600)  # restore for cleanup

    def test_default_path_resolves_correctly(self):
        status = m.check()  # no args → default
        assert status.path.name == "api_keys.json"
        # The module lives in config/ which is a sibling of tests/
        # Path(__file__).resolve().parents[3] = project root
        project_root = Path(__file__).resolve().parents[3]
        assert status.path.is_relative_to(project_root)


class TestRequireNotTracked:
    """Tests for the require_not_tracked() function."""

    def test_not_tracked_passes(self, tmp_path):
        fake = tmp_path / "api_keys.json"
        fake.write_text("{}")
        require = m.require_not_tracked(fake)  # no exception expected
        assert require is None

    def test_tracked_raises(self):
        """Simulate a tracked file: patch _git_is_tracked to return True."""
        fake = Path("/tmp/fake_api_keys.json")
        with patch("config.secret_tracking.check") as mock_check:
            mock_check.return_value = TrackingStatus(
                path=fake,
                exists=True,
                is_tracked_by_git=True,
                mode_octal="0600",
                has_read_permissions=True,
            )
            with pytest.raises(RuntimeError, match="must NOT be tracked"):
                m.require_not_tracked(fake)


class TestTrackingStatusDataclass:
    """Verify TrackingStatus immutability and fields."""

    def test_fields(self):
        st = TrackingStatus(
            path=Path("test.json"),
            exists=True,
            is_tracked_by_git=False,
            mode_octal="0600",
            has_read_permissions=True,
        )
        assert st.path == Path("test.json")
        assert st.exists is True
        assert st.is_tracked_by_git is False
        assert st.mode_octal == "0600"
        assert st.has_read_permissions is True

    def test_immutability(self):
        st = TrackingStatus(
            path=Path("x"),
            exists=False,
            is_tracked_by_git=False,
            mode_octal="",
            has_read_permissions=False,
        )
        with pytest.raises(Exception):
            st.exists = True  # Frozen dataclass
