"""Secret-scanning heuristics for code and config files.

Provides ``scan_path`` and ``scan_text`` that check content against a set of
regex patterns commonly associated with leaked credentials.

Public API
----------
scan_text(text: str) -> list[Issue]
scan_path(path: Path) -> list[Issue]
KNOWN_ISSUE_SEVERITY  # for import in tests / pre-commit hooks

Usage outside the package
--------------------------
This module intentionally avoids matching live secrets.  All patterns use
wildcard anchors or low-entropy prefixes so that a value like
``sk-test-notreal`` does NOT trigger a hit, while a full-looking key such as
``sk-proj-abc123def456...`` would.

Security note
-------------
This scanner is a regression guard, not a replacement for proper secret
management.  False negatives are expected — the goal is to catch *obvious*
leaks, not to prove absence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Regex patterns.  Each pattern is compiled from a human-readable label so
# the string itself never contains a real credential fragment that could
# accidentally enter version control.
# ---------------------------------------------------------------------------

# GCP / Google API keys: AIza followed by 34 alphanumeric characters
_PAT_GCP: Final[str] = r"AIza[A-Za-z0-9_\-]{34}"

# OpenAI secret keys – sk- followed by enough randomness
_PAT_OPENAI: Final[str] = r"sk-[A-Za-z0-9]{20,}"

# GitHub personal access tokens (classic and fine-grained)
_PAT_GITHUB: Final[str] = r"gh[ps]_[A-Za-z0-9_]{20,}"

# Generic bearer / OAuth tokens  (recognises "Bearer <token>" with space
# or "Authorization: <token>" / "Authorization=<token>")
_PAT_BEARER: Final[str] = r"(?:Bearer|bearer|Authorization|authorization)\s*[=: ]\s*[A-Za-z0-9\-_\.]{40,}"

# AWS / AWS-style access key IDs
_PAT_AWS: Final[str] = r"(?:AKIA|ASIA)[A-Z0-9]{16}"

# Private-key / PEM blocks
_PAT_PEM: Final[str] = r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PGP)?\s*PRIVATE KEY-----"

# Slack tokens
_PAT_SLACK: Final[str] = r"xox[bpas]-[A-Za-z0-9\-]{10,}"

# Stripe API keys (live and test)
_PAT_STRIPE: Final[str] = r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}"

# Anthropic / Claude
_PAT_ANTHROPIC: Final[str] = r"sk-ant-[A-Za-z0-9\-_]{20,}"

# Password / secret assignments in code/config (common leak pattern)
_PAT_ASSIGN: Final[str] = r"(?:password|passwd|secret|token|api_key|apikey|access_token)\s*[=:]\s*[A-Za-z0-9\-_\.]{16,}"

# Combined
_PATTERNS: Final[list[tuple[str, str]]] = [
    ("google_api_key", _PAT_GCP),
    ("openai_key", _PAT_OPENAI),
    ("github_token", _PAT_GITHUB),
    ("bearer_token", _PAT_BEARER),
    ("aws_access_key", _PAT_AWS),
    ("pem_private_key", _PAT_PEM),
    ("slack_token", _PAT_SLACK),
    ("stripe_key", _PAT_STRIPE),
    ("anthropic_key", _PAT_ANTHROPIC),
    ("password_assignment", _PAT_ASSIGN),
]

# Compiled versions
_COMPILED: Final[list[tuple[str, re.Pattern]]] = [
    (label, re.compile(p)) for label, p in _PATTERNS
]

# Files that should NEVER appear in the index / working tree with secrets.
# Used by scan_git_index() and by the pre-commit hook.
_SENSITIVE_PATHS: Final[frozenset[str]] = frozenset({
    "config/api_keys.json",
    "config/api_keys.json.bak",
    "config/settings.local.json",
    "config/settings.secret.json",
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
})

# Exempt files – patterns that may legitimately contain credential-like
# fragments but belong to the project itself.
_EXEMPT_PATHS: Final[frozenset[str]] = frozenset({
    "config/secrets.py",
    "config/settings.example.json",
    "tests/unit/config/test_secrets.py",
    "tests/unit/security/test_secret_scan.py",
    "tests/unit/security/test_secret_tracking.py",
    "config/secret_tracking.py",
    ".git/hooks/pre-commit",
})

# Exempt substrings – short, known-safe strings that appear in docs and
# test code but should never trigger.
_EXEMPT_SUBSTRINGS: Final[frozenset[str]] = frozenset({
    "sk-test-notreal",
    "sk-placeholder",
    "CHANGEME",
    "TODO",
    "INSERT",
    "example_key",
})


@dataclass(frozen=True)
class Issue:
    """A single secret-leak issue found in scanned content."""
    pattern: str          # human-readable label
    line: int             # 1-based line number within the scanned file
    detail: str           # description (never a live secret value)


def scan_text(text: str) -> list[Issue]:
    """Return issues found in *text*.

    *text* is scanned line-by-line.  Each line is checked against every
    pattern; on the first match the line number and pattern label are
    appended to the returned list.
    """
    issues: list[Issue] = []
    for line_idx, line in enumerate(text.splitlines(), start=1):
        for label, pat in _COMPILED:
            if pat.search(line):
                issues.append(Issue(
                    pattern=label,
                    line=line_idx,
                    detail=f"potential {label} detected",
                ))
                break  # one issue per line-max
    return issues


def scan_path(path: Path) -> list[Issue]:
    """Scan a single file on disk.

    Returns an empty list when the file does not exist, is not readable,
    or has a binary extension that is likely not source code.
    """
    if not path.is_file():
        return []

    # Quick bail for obviously non-source files.
    _binary_exts = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff2",
                    ".woff", ".ttf", ".otf", ".eot", ".bin", ".dat",
                    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo",
                    ".zip", ".tar", ".gz", ".xz", ".bz2", ".7z",
                    ".app", ".dylib", ".so", ".dll", ".exe"}
    if path.suffix.lower() in _binary_exts:
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    return scan_text(text)


def scan_git_index(root: Path) -> list[Issue]:
    """Check every tracked file under *root* against the sensitive-path list.

    Returns a list of Issue objects (currently unused but kept for the
    pre-commit hook to extend).
    """
    import subprocess  # avoid import at module-level when not needed

    issues: list[Issue] = []
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "-z"],
            capture_output=True, text=True, check=True,
        )
        files = [f for f in result.stdout.split("\0") if f]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return issues

    for fname in files:
        for sensitive in _SENSITIVE_PATHS:
            if fname == sensitive or fname.endswith("/" + sensitive):
                issues.append(Issue(
                    pattern="tracked_secret_file",
                    line=0,
                    detail=f"{fname} is tracked in git",
                ))

    return issues
