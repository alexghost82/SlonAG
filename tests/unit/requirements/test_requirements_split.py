"""Text-level checks for the platform requirements split."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

OWNED_REQUIREMENTS = (
    "requirements-base.txt",
    "requirements-macos.txt",
    "requirements-windows.txt",
    "requirements-linux.txt",
    "requirements.txt",
)

WINDOWS_ONLY = (
    "pygetwindow",
    "comtypes",
    "pycaw",
    "win10toast",
    "pywinauto",
)

NON_WINDOWS_FILES = (
    "requirements-base.txt",
    "requirements-macos.txt",
    "requirements-linux.txt",
    "requirements.txt",
)

REQ_LINE = re.compile(
    r"""
    ^\s*
    (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)
    (?P<extras>\[[^\]]+\])?
    (?P<spec>\s*(?:[=<>!~]=?|===)\s*[^;#]+)?
    """,
    re.VERBOSE,
)
INCLUDE_LINE = re.compile(r"^\s*-r\s+(?P<path>\S+)")


def _req(name: str) -> Path:
    return REPO_ROOT / name


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _iter_requirement_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        comment = stripped.find("#")
        if comment != -1:
            stripped = stripped[:comment].strip()
        if stripped:
            lines.append(stripped)
    return lines


def _parse_package_names(path: Path) -> list[str]:
    names: list[str] = []
    for line in _iter_requirement_lines(path):
        if INCLUDE_LINE.match(line):
            continue
        match = REQ_LINE.match(line)
        if match:
            names.append(match.group("name"))
    return names


def _parse_normalized_names(path: Path) -> list[str]:
    return [_normalize_name(name) for name in _parse_package_names(path)]


def _include_paths(path: Path) -> list[str]:
    found: list[str] = []
    for line in _iter_requirement_lines(path):
        match = INCLUDE_LINE.match(line)
        if match:
            found.append(match.group("path"))
    return found


def _load_setup_module():
    path = REPO_ROOT / "setup.py"
    spec = importlib.util.spec_from_file_location("mark_setup", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_owned_requirement_files_exist() -> None:
    for name in OWNED_REQUIREMENTS:
        path = _req(name)
        assert path.is_file(), f"missing {name}"
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("#"), f"{name} must start with a comment"


def test_google_generativeai_absent_from_owned_files() -> None:
    banned = _normalize_name("google-generativeai")
    for name in OWNED_REQUIREMENTS:
        names = _parse_normalized_names(_req(name))
        assert banned not in names, f"{name} still lists google-generativeai"


def test_google_genai_present_in_base() -> None:
    names = _parse_normalized_names(_req("requirements-base.txt"))
    assert "google-genai" in names


def test_pyqt6_present_in_base() -> None:
    names = _parse_normalized_names(_req("requirements-base.txt"))
    assert "pyqt6" in names


def test_windows_only_packages_not_in_base_macos_linux_or_shim() -> None:
    banned = {_normalize_name(pkg) for pkg in WINDOWS_ONLY}
    for name in NON_WINDOWS_FILES:
        found = banned.intersection(_parse_normalized_names(_req(name)))
        assert not found, f"{name} lists Windows-only packages: {sorted(found)}"


def test_windows_file_lists_windows_only_packages() -> None:
    names = set(_parse_normalized_names(_req("requirements-windows.txt")))
    missing = [pkg for pkg in WINDOWS_ONLY if _normalize_name(pkg) not in names]
    assert not missing, f"requirements-windows.txt missing {missing}"


def test_pillow_not_duplicated_inside_a_single_file() -> None:
    pillow = _normalize_name("Pillow")
    for name in OWNED_REQUIREMENTS:
        names = _parse_normalized_names(_req(name))
        assert names.count(pillow) <= 1, f"{name} lists pillow/Pillow more than once"


def test_no_duplicate_packages_inside_a_single_file() -> None:
    for name in OWNED_REQUIREMENTS:
        names = _parse_normalized_names(_req(name))
        dupes = sorted({item for item in names if names.count(item) > 1})
        assert not dupes, f"{name} has duplicate packages: {dupes}"


def test_requirements_txt_is_shim() -> None:
    path = _req("requirements.txt")
    text = path.read_text(encoding="utf-8")
    assert _include_paths(path) == ["requirements-base.txt"]
    assert _parse_package_names(path) == []
    lowered = text.lower()
    assert "requirements-macos.txt" in lowered
    assert "requirements-windows.txt" in lowered
    assert "requirements-linux.txt" in lowered
    for pkg in WINDOWS_ONLY:
        assert pkg not in lowered


def test_os_files_include_base() -> None:
    for name in (
        "requirements-macos.txt",
        "requirements-windows.txt",
        "requirements-linux.txt",
    ):
        assert _include_paths(_req(name)) == ["requirements-base.txt"]


def test_shim_requirement_lines_do_not_name_windows_packages() -> None:
    lines = "\n".join(_iter_requirement_lines(_req("requirements.txt"))).lower()
    for pkg in WINDOWS_ONLY:
        assert pkg not in lines


def test_setup_maps_os_to_requirements_file() -> None:
    setup = _load_setup_module()
    select = setup.requirements_file_for_os
    assert select("darwin") == "requirements-macos.txt"
    assert select("win32") == "requirements-windows.txt"
    assert select("win") == "requirements-windows.txt"
    assert select("windows") == "requirements-windows.txt"
    assert select("linux") == "requirements-linux.txt"
    assert select("linux2") == "requirements-linux.txt"


def test_setup_source_mentions_slon_not_legacy_names() -> None:
    source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    assert "Slon" in source
    assert "XXXIX" not in source
    assert "XXV" not in source
    assert "requirements-dev.txt" not in source
    assert "playwright" in source
    assert 'if __name__ == "__main__"' in source
