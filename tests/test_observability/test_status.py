"""Tests for observability/status.py."""

import sys
import json
from pathlib import Path

import pytest

# Ensure repo is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from observability.status import (
    ComponentState,
    ComponentStatus,
    ComponentRegistry,
    available,
    unavailable,
    degraded,
    misconfigured,
    disabled,
    create_registry,
    check_all_components,
    get_component_status,
    all_statuses,
    _check_python_version,
    _check_i18n,
    _check_secrets,
)


class TestComponentState:
    def test_state_values(self):
        assert available == "available"
        assert unavailable == "unavailable"
        assert degraded == "degraded"
        assert misconfigured == "misconfigured"
        assert disabled == "disabled"


class TestComponentStatus:
    def test_is_ready_available(self):
        s = ComponentStatus(name="test", state=ComponentState.AVAILABLE)
        assert s.is_ready is True

    def test_is_ready_not_available(self):
        s = ComponentStatus(name="test", state=ComponentState.UNAVAILABLE)
        assert s.is_ready is False

    def test_to_dict(self):
        s = ComponentStatus(name="test", state=ComponentState.AVAILABLE,
                            message="OK", details="details", version="1.0")
        d = s.to_dict()
        assert d["name"] == "test"
        assert d["state"] == "available"
        assert d["message"] == "OK"
        assert d["details"] == "details"
        assert d["version"] == "1.0"
        assert "last_checked" in d


class TestComponentRegistry:
    def test_register_and_get(self):
        reg = ComponentRegistry()
        checker = lambda: ComponentStatus(
            name="my_comp", state=ComponentState.AVAILABLE, message="works"
        )
        reg.register("my_comp", checker)
        result = reg.get("my_comp")
        assert result is not None
        assert result.is_ready is True
        assert result.message == "works"

    def test_unregister(self):
        reg = ComponentRegistry()
        result = reg.get("unknown_comp")
        assert result is not None
        assert result.state == ComponentState.UNAVAILABLE

    def test_summary(self):
        reg = ComponentRegistry()
        reg.register("comp1", lambda: ComponentStatus(
            name="comp1", state=ComponentState.AVAILABLE
        ))
        reg.register("comp2", lambda: ComponentStatus(
            name="comp2", state=ComponentState.UNAVAILABLE
        ))
        summary = reg.summary()
        assert summary["component_count"] == 2
        assert summary["state_counts"]["available"] == 1
        assert summary["state_counts"]["unavailable"] == 1


class TestBuiltInCheckers:
    def test_python_version(self):
        s = _check_python_version()
        assert s.name == "python_version"
        assert s.state in (ComponentState.AVAILABLE, ComponentState.MISCONFIGURED)

    def test_i18n(self):
        s = _check_i18n()
        assert s.name == "i18n"
        # Should be either available or degraded (depending on i18n files)
        assert s.state in (ComponentState.AVAILABLE, ComponentState.DEGRADED,
                           ComponentState.UNAVAILABLE)

    def test_secrets(self):
        s = _check_secrets()
        assert s.name == "secrets"
        assert s.state in (ComponentState.AVAILABLE, ComponentState.MISCONFIGURED,
                           ComponentState.DISABLED)


class TestFullReport:
    def test_check_all_components(self):
        report = check_all_components()
        assert "component_count" in report
        assert "state_counts" in report
        assert "components" in report
        assert report["component_count"] >= 5  # at least python, i18n, secrets, config

    def test_all_statuses(self):
        statuses = all_statuses()
        assert "python_version" in statuses
        assert "i18n" in statuses
        assert "secrets" in statuses


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
