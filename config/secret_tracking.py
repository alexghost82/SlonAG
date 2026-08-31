"""Tracking status of secret files on disk and in git.

Provides functions to check whether the api_keys.json fallback file
exists, whether it is tracked by git (it should NOT be), and whether
its filesystem permissions are correct (``0600`` on POSIX).
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_KEYS_PATH: Final[Path] = (
    Path(__file__).resolve().parent / "api_keys.json"
)


@dataclass(frozen=True)
class TrackingStatus:
    """Immutable status of a secret file."""
    path: Path
    exists: bool
    is_tracked_by_git: bool
    mode_octal: str           # e.g. "0600"  (empty when file does not exist)
    has_read_permissions: bool  # owner can read


def check(path: Path | None = None) -> TrackingStatus:
    """Return the tracking status of the secret-keys file.

    Parameters
    ----------
    path:
        Override the default ``api_keys.json`` location.  Defaults to the
        file next to this module.
    """
    if path is None:
        path = DEFAULT_KEYS_PATH

    exists = path.is_file()
    mode_octal = ""
    has_read = False
    is_tracked = False

    if exists:
        try:
            mode_octal = oct(stat.S_IMODE(path.stat().st_mode))
            has_read = os.access(path, os.R_OK)
        except OSError:
            pass

        # Check whether the path is tracked in the git repo that
        # contains this file.
        repo_root = _resolve_git_root(path.parent)
        if repo_root is not None:
            is_tracked = _git_is_tracked(repo_root, path)

    return TrackingStatus(
        path=path,
        exists=exists,
        is_tracked_by_git=is_tracked,
        mode_octal=mode_octal,
        has_read_permissions=has_read,
    )


def _resolve_git_root(cwd: Path) -> Path | None:
    """Return the git repo root or ``None``."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _git_is_tracked(repo_root: Path, file_path: Path) -> bool:
    """Return ``True`` if *file_path* is tracked (cached) in git."""
    try:
        rel = file_path.relative_to(repo_root)
    except ValueError:
        return False

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--cached", str(rel)],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def require_not_tracked(path: Path | None = None) -> None:
    """Raise ``RuntimeError`` if the secret file is tracked by git."""
    st = check(path)
    if st.is_tracked_by_git:
        raise RuntimeError(
            f"{st.path} must NOT be tracked by git. "
            "It is listed in .gitignore, but git has cached it."
        )
