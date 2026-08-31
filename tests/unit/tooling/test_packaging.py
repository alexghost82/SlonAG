"""Tests for project packaging and tooling configuration."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture
def pyproject_data(project_root: Path) -> dict:
    with open(project_root / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


class TestPyProjectMetadata:
    """pyproject.toml must contain valid project metadata."""

    def test_name_present(self, pyproject_data: dict) -> None:
        assert "slon" in pyproject_data["project"]["name"]

    def test_version_present(self, pyproject_data: dict) -> None:
        assert pyproject_data["project"]["version"] == "0.1.0"

    def test_requires_python(self, pyproject_data: dict) -> None:
        assert pyproject_data["project"]["requires-python"] == ">=3.11,<3.13"

    def test_license_present(self, pyproject_data: dict) -> None:
        assert "license" in pyproject_data["project"]

    def test_scripts_present(self, pyproject_data: dict) -> None:
        assert "slon" in pyproject_data["project"]["scripts"]


class TestPytestConfig:
    """pytest configuration must be valid."""

    def test_testpaths_defined(self, pyproject_data: dict) -> None:
        assert pyproject_data["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]

    def test_asyncio_mode_auto(self, pyproject_data: dict) -> None:
        assert pyproject_data["tool"]["pytest"]["ini_options"]["asyncio_mode"] == "auto"


class TestPreCommitConfig:
    """.pre-commit-config.yaml must exist and contain required hooks."""

    def test_file_exists(self, project_root: Path) -> None:
        assert (project_root / ".pre-commit-config.yaml").exists()

    @pytest.fixture
    def precommit_data(self, project_root: Path) -> dict:
        import yaml
        with open(project_root / ".pre-commit-config.yaml") as f:
            return yaml.safe_load(f)

    def test_trailing_whitespace_hook(self, precommit_data: dict) -> None:
        for repo in precommit_data["repos"]:
            for hook in repo.get("hooks", []):
                if hook["id"] == "trailing-whitespace":
                    return
        pytest.fail("trailing-whitespace hook not found")

    def test_yaml_validation_hook(self, precommit_data: dict) -> None:
        for repo in precommit_data["repos"]:
            for hook in repo.get("hooks", []):
                if hook["id"] == "check-yaml":
                    return
        pytest.fail("check-yaml hook not found")

    def test_toml_validation_hook(self, precommit_data: dict) -> None:
        for repo in precommit_data["repos"]:
            for hook in repo.get("hooks", []):
                if hook["id"] == "check-toml":
                    return
        pytest.fail("check-toml hook not found")

    def test_ruff_hook(self, precommit_data: dict) -> None:
        for repo in precommit_data["repos"]:
            if "ruff" in repo.get("repo", ""):
                ids = [h["id"] for h in repo.get("hooks", [])]
                assert "ruff" in ids, "ruff lint hook missing"

    def test_secret_detection_hook(self, precommit_data: dict) -> None:
        for repo in precommit_data["repos"]:
            for hook in repo.get("hooks", []):
                if hook["id"] in ("detect-private-key", "gitleaks"):
                    return
        pytest.fail("secret detection hook not found")


class TestEnvExample:
    """.env.example must contain placeholders only, no real secrets."""

    def test_file_exists(self, project_root: Path) -> None:
        assert (project_root / ".env.example").exists()

    def test_no_real_keys(self, project_root: Path) -> None:
        """All non-comment lines with values must contain placeholder text."""
        content = (project_root / ".env.example").read_text()
        placeholder = "your-api-key-here"
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                value = line.split("=", 1)[1].strip()
                assert placeholder in value, (
                    f"Non-placeholder value found: {line}"
                )

    def test_google_api_key_placeholder(self, project_root: Path) -> None:
        content = (project_root / ".env.example").read_text()
        assert "GOOGLE_API_KEY=" in content
        assert "your-api-key-here" in content


class TestEntryPoint:
    """__main__.py must exist and parse correctly."""

    def test_file_exists(self, project_root: Path) -> None:
        assert (project_root / "__main__.py").exists()

    def test_parses(self, project_root: Path) -> None:
        import ast
        with open(project_root / "__main__.py") as f:
            ast.parse(f.read())
