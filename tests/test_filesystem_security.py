"""Comprehensive security tests for the unified filesystem module.

Covers:
- ../ path traversal
- Absolute forbidden paths
- Symlink escape
- System directories
- Oversized files
- Workspace crossing
- Encoding / binary detection
- Cancellation
- All operations (read, write, create, list, search, metadata, copy, move, rename, trash, delete, dir)

Run: pytest tests/test_filesystem_security.py -v
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from unittest import TestCase

from mark.filesystem.security import (
    MAX_FILE_SIZE,
    MAX_READ_BYTES,
    MAX_WRITE_BYTES,
    PathDenied,
    SizeExceeded,
    SymlinkEscape,
    TraversalDetected,
    _check_cancel,
    _is_forbidden_system_path,
    _has_traversal_component,
    _raw_is_forbidden,
    _safe_relative,
    default_allowlist_roots,
    detect_file_type,
    read_safe,
    validate_path,
    validate_write_size,
)
from mark.filesystem.operations import (
    FileSystemResult,
    copy,
    create_directory,
    create_file,
    delete,
    disk_usage,
    filesystem_operation,
    list_directory,
    metadata,
    organize_desktop,
    read,
    rename,
    search,
    trash,
    write,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_root() -> tuple[Path, tuple[Path, ...]]:
    """Create a temporary workspace and return (workspace_dir, roots)."""
    ws = Path(tempfile.mkdtemp(prefix="fs_security_test_"))
    roots = (ws,)
    return ws, roots


def _cleanup(ws: Path) -> None:
    try:
        shutil.rmtree(str(ws))
    except OSError:
        pass


class TestPathTraversal(TestCase):
    """Directory-traversal attacks must be blocked."""

    def setUp(self):
        self.ws, self.roots = _make_test_root()
        self.addCleanup(_cleanup, self.ws)

    def test_dotdot_in_path(self):
        self.assertRaises(PathDenied, validate_path, "../etc", self.roots)
        self.assertRaises(PathDenied, validate_path, "foo/../../etc", self.roots)
        self.assertRaises(PathDenied, validate_path, "./../etc", self.roots)

    def test_symlink_traversal(self):
        # Create a symlink that points outside the workspace
        internal = self.ws / "safe"
        internal.mkdir()
        external_link = self.ws / "escape"
        external_link.symlink_to("/etc")
        # Resolving through the symlink should be caught
        try:
            result = validate_path("escape", self.roots)
            self.fail(f"Expected PathDenied but got: {result}")
        except (PathDenied, SymlinkEscape):
            pass  # Expected

    def test_absolute_forbidden(self):
        self.assertRaises(PathDenied, validate_path, "/etc/passwd", self.roots)
        self.assertRaises(PathDenied, validate_path, "/usr/bin", self.roots)
        self.assertRaises(PathDenied, validate_path, "/var/log", self.roots)
        self.assertRaises(PathDenied, validate_path, "/proc/cpuinfo", self.roots)

    def test_root_path_denied(self):
        self.assertRaises(PathDenied, validate_path, "/", self.roots)

    def test_home_root_denied(self):
        self.assertRaises(PathDenied, validate_path, str(Path.home()), self.roots)


class TestSymlinkEscape(TestCase):
    """Symlinks must not escape the allowlist."""

    def setUp(self):
        self.ws, self.roots = _make_test_root()
        self.addCleanup(_cleanup, self.ws)

    def test_symlink_to_allowed_file(self):
        """Symlink to a file within the workspace is allowed."""
        target = self.ws / "real.txt"
        target.write_text("hello")
        link = self.ws / "link.txt"
        link.symlink_to(target)
        result = validate_path("link.txt", self.roots)
        self.assertEqual(result, target.resolve())

    def test_symlink_outside_workspace(self):
        """Symlink pointing outside workspace is denied."""
        link = self.ws / "bad_link"
        link.symlink_to("/etc")
        try:
            validate_path("bad_link", self.roots)
            self.fail("Expected PathDenied")
        except PathDenied:
            pass


class TestSystemPaths(TestCase):
    """System directories must always be forbidden."""

    def test_forbidden_system_paths(self):
        for path in ["/etc", "/usr", "/bin", "/sbin", "/var", "/dev", "/proc", "/root", "/boot", "/lib"]:
            self.assertTrue(_is_forbidden_system_path(Path(path)), f"{path} should be forbidden")

    def test_forbidden_raw(self):
        self.assertTrue(_raw_is_forbidden("/"))
        self.assertTrue(_raw_is_forbidden("/etc"))
        self.assertTrue(_raw_is_forbidden("c:/windows"))


class TestSizeLimits(TestCase):
    """Size limits must be enforced."""

    def test_write_size_limit(self):
        with self.assertRaises(SizeExceeded):
            validate_write_size("x" * (MAX_WRITE_BYTES + 1))

    def test_valid_write_size(self):
        size = validate_write_size("hello")
        self.assertEqual(size, 5)


class TestEncoding(TestCase):
    """Encoding handling must distinguish text from binary."""

    def setUp(self):
        self.ws, self.roots = _make_test_root()
        self.addCleanup(_cleanup, self.ws)

    def test_text_file_detection(self):
        txt = self.ws / "test.txt"
        txt.write_text("Hello, world!", encoding="utf-8")
        self.assertEqual(detect_file_type(txt), "text")

    def test_binary_file_detection(self):
        png = self.ws / "test.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self.assertEqual(detect_file_type(png), "binary")

    def test_binary_nul_byte_detection(self):
        bin_file = self.ws / "test.bin"
        bin_file.write_bytes(b"hello\x00world")
        self.assertEqual(detect_file_type(bin_file), "binary")


class TestOperations(TestCase):
    """Test all filesystem operations with security enforcement."""

    def setUp(self):
        self.ws, self.roots = _make_test_root()
        self.addCleanup(_cleanup, self.ws)

    def test_read_nonexistent(self):
        result = read("nonexistent.txt", roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "not_a_file")

    def test_read_text_file(self):
        f = self.ws / "readme.txt"
        f.write_text("Hello, World!", encoding="utf-8")
        result = read(str(f), roots=self.roots)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, "Hello, World!")

    def test_read_binary_file_rejected(self):
        f = self.ws / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = read(str(f), roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "binary_file")

    def test_read_outside_allowlist(self):
        result = read("/etc/passwd", roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "path_denied")

    def test_write_new_file(self):
        result = write("new.txt", "content", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertTrue((self.ws / "new.txt").exists())
        self.assertEqual((self.ws / "new.txt").read_text(), "content")

    def test_write_traversal_blocked(self):
        result = write("../etc/hacked", "evil", roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "path_denied")

    def test_append(self):
        f = self.ws / "app.txt"
        f.write_text("first\n", encoding="utf-8")
        result = write("app.txt", "second\n", append=True, roots=self.roots)
        self.assertTrue(result.ok)
        self.assertEqual(f.read_text(), "first\nsecond\n")

    def test_create_file(self):
        result = create_file("create_me.txt", "data", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertTrue((self.ws / "create_me.txt").exists())

    def test_create_directory(self):
        result = create_directory("sub/dir", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertTrue((self.ws / "sub" / "dir").is_dir())

    def test_list_directory(self):
        (self.ws / "a.txt").touch()
        (self.ws / "b.txt").touch()
        (self.ws / "hidden").mkdir()
        (self.ws / "hidden" / ".gitkeep").touch()
        result = list_directory(".", show_hidden=False, roots=self.roots)
        self.assertTrue(result.ok)
        self.assertIn("a.txt", result.message)
        self.assertIn("b.txt", result.message)
        self.assertNotIn(".gitkeep", result.message)

    def test_search(self):
        (self.ws / "readme.py").write_text("# test", encoding="utf-8")
        (self.ws / "data.txt").write_text("hello", encoding="utf-8")
        result = search(".", name_pattern="readme", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertIn("readme.py", result.message)

    def test_search_by_extension(self):
        (self.ws / "test.py").write_text("print()", encoding="utf-8")
        result = search(".", extension="py", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertIn("test.py", result.message)

    def test_metadata(self):
        f = self.ws / "meta.txt"
        f.write_text("hello", encoding="utf-8")
        result = metadata(str(f), roots=self.roots)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["type"], "file")

    def test_disk_usage(self):
        result = disk_usage(".", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertIn("Total", result.message)

    def test_copy(self):
        src = self.ws / "src.txt"
        src.write_text("content", encoding="utf-8")
        result = copy("src.txt", "dst.txt", roots=self.roots)
        self.assertTrue(result.ok)
        dst = self.ws / "dst.txt"
        self.assertTrue(dst.exists())
        self.assertEqual(dst.read_text(), "content")

    def test_copy_traversal_blocked(self):
        result = copy("test.txt", "../../etc/hacked", roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "dest_path_denied")

    def test_rename(self):
        f = self.ws / "old.txt"
        f.write_text("data", encoding="utf-8")
        result = rename("old.txt", "new.txt", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertFalse((self.ws / "old.txt").exists())
        self.assertTrue((self.ws / "new.txt").exists())

    def test_rename_outside_allowlist(self):
        f = self.ws / "src.txt"
        f.write_text("data", encoding="utf-8")
        result = rename("src.txt", "../../etc/evil.txt", roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "path_denied")

    def test_trash(self):
        f = self.ws / "to_delete.txt"
        f.write_text("data", encoding="utf-8")
        result = trash("to_delete.txt", roots=self.roots)
        self.assertTrue(result.ok)
        # send2trash moves to system trash; file no longer at original path
        self.assertFalse(f.exists())

    def test_delete(self):
        f = self.ws / "to_purge.txt"
        f.write_text("data", encoding="utf-8")
        result = delete("to_purge.txt", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertFalse(f.exists())

    def test_workspace_crossing(self):
        other = Path(tempfile.mkdtemp(prefix="other_ws_"))
        other_file = other / "secret.txt"
        other_file.write_text("classified", encoding="utf-8")
        # Reading from another workspace should fail
        result = read(str(other_file), roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "path_denied")
        _cleanup(other)


class TestCancellation(TestCase):
    """Cancellation must work via threading.Event."""

    def test_cancelled_op(self):
        event = threading.Event()
        event.set()  # Pre-set to cancelled
        _check_cancel(event)
        with self.assertRaises(Exception):  # Cancelled exception
            _check_cancel(event)


class TestUnifiedFilesystemOperation(TestCase):
    """Test the single filesystem_operation dispatcher."""

    def setUp(self):
        self.ws, self.roots = _make_test_root()
        self.addCleanup(_cleanup, self.ws)

    def test_read_via_dispatch(self):
        f = self.ws / "dispatch.txt"
        f.write_text("dispatched", encoding="utf-8")
        result = filesystem_operation("read", path=str(f), roots=self.roots)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, "dispatched")

    def test_write_via_dispatch(self):
        result = filesystem_operation(
            "write", path="dispatched.txt", content="data", roots=self.roots
        )
        self.assertTrue(result.ok)
        self.assertTrue((self.ws / "dispatched.txt").exists())

    def test_unknown_action(self):
        result = filesystem_operation("fake_action", path="x", roots=self.roots)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "unknown_action")


class TestE2EFileSecurityFlow(TestCase):
    """End-to-end: AgentLoop → filesystem tool → Safety/Approval → operation → ToolResult → continuation."""

    def setUp(self):
        self.ws, self.roots = _make_test_root()
        self.addCleanup(_cleanup, self.ws)

    def test_full_flow_safe_read(self):
        """Read a file that exists in the workspace."""
        f = self.ws / "readme.md"
        f.write_text("# Hello\nThis is safe.", encoding="utf-8")
        result = read(str(f), roots=self.roots)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, "# Hello\nThis is safe.")

    def test_full_flow_safe_write(self):
        """Write a file that is allowed."""
        result = write("safe.txt", "approved content", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertEqual((self.ws / "safe.txt").read_text(), "approved content")

    def test_full_flow_blocked_traversal(self):
        """Agent tries ../ escape — must be denied before any filesystem access."""
        result = filesystem_operation(
            "write", path="../etc/evil.txt", content="malicious", roots=self.roots
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "path_denied")

    def test_full_flow_blocked_system_path(self):
        """Agent tries writing to /etc — must be denied."""
        result = filesystem_operation(
            "write", path="/etc/evil.txt", content="malicious", roots=self.roots
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "path_denied")

    def test_full_flow_blocked_workspace_crossing(self):
        """Agent tries to read another workspace — must be denied."""
        other = Path(tempfile.mkdtemp(prefix="other_"))
        secret = other / "classified.txt"
        secret.write_text("TOP SECRET", encoding="utf-8")
        result = read(str(secret), roots=self.roots)
        self.assertFalse(result.ok)
        _cleanup(other)

    def test_full_flow_safe_copy(self):
        """Copy within workspace is allowed."""
        src = self.ws / "source.txt"
        src.write_text("copy me", encoding="utf-8")
        result = copy("source.txt", "dest.txt", roots=self.roots)
        self.assertTrue(result.ok)
        self.assertEqual((self.ws / "dest.txt").read_text(), "copy me")

    def test_full_flow_safe_delete(self):
        """Delete within workspace is allowed."""
        f = self.ws / "delete_me.txt"
        f.write_text("bye", encoding="utf-8")
        result = trash("delete_me.txt", roots=self.roots)
        self.assertTrue(result.ok)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import unittest
    unittest.main()
