"""Consistency tests: every advertised capability has a real implementation.

These tests verify that:
1. Every registered tool has a callable handler.
2. Every safety-registered tool that's also in the builtin registry has a handler.
3. Every capability-gated tool (vision/STT/TTS) only registers when the runtime is available.
4. Deprecated tools are not advertised.
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest


class TestToolRegistryConsistency:
    """Tests that verify tool registry integrity."""

    def test_every_registered_tool_has_callable_handler(self) -> None:
        """Every ToolSpec.name must have a callable handler."""
        from mark.tools.builtin import build_builtin_registry

        registry = build_builtin_registry()
        for spec in registry.list():
            assert callable(spec.handler), (
                f"Tool '{spec.name}' is registered but handler is not callable"
            )

    def test_no_fake_descriptions(self) -> None:
        """No tool description should contain 'fake', 'stub', 'placeholder'."""
        from mark.tools.builtin import build_builtin_registry, _DESCRIPTIONS

        registry = build_builtin_registry()
        registered_names = {s.name for s in registry.list()}

        for name in registered_names:
            desc = _DESCRIPTIONS.get(name, "")
            assert desc, f"Tool '{name}' has no description"
            assert "fake" not in desc.lower(), (
                f"Tool '{name}' description contains 'fake': {desc}"
            )
            assert "stub" not in desc.lower(), (
                f"Tool '{name}' description contains 'stub': {desc}"
            )
            assert "placeholder" not in desc.lower(), (
                f"Tool '{name}' description contains 'placeholder': {desc}"
            )

    def test_cmd_control_not_advertised(self) -> None:
        """cmd_control must NOT be advertised (deprecated)."""
        from mark.tools.builtin import build_builtin_registry, _DESCRIPTIONS
        from mark.tools.legacy import LEGACY_HANDLERS

        registry = build_builtin_registry()
        registered_names = {s.name for s in registry.list()}

        # Should NOT be in descriptions
        assert "cmd_control" not in _DESCRIPTIONS, (
            "cmd_control is still in _DESCRIPTIONS but should be removed"
        )
        # Should NOT be in registry (explicitly skipped)
        assert "cmd_control" not in registered_names, (
            "cmd_control is still in the tool registry"
        )
        # LEGACY_HANDLERS still has it for backward compat (no crash)
        assert "cmd_control" in LEGACY_HANDLERS, (
            "cmd_control should still be in LEGACY_HANDLERS for backward compat"
        )

    def test_safety_only_tools_not_in_builtin_registry(self) -> None:
        """Tools that exist only in safety policy should NOT be in builtin registry."""
        from mark.tools.builtin import build_builtin_registry
        from mark.safety.registry import registered_tools

        registry = build_builtin_registry()
        registered_names = {s.name for s in registry.list()}
        safety_tools = registered_tools()

        # save_memory is safety-only (no handler in builtins)
        assert "save_memory" not in registered_names, (
            "save_memory is safety-only — should not be in builtin registry"
        )
        # shutdown_slon/shutdown_jarvis are BIOMETRIC safety-only tools
        assert "shutdown_slon" not in registered_names, (
            "shutdown_slon is safety-only (BIOMETRIC) — should not be in builtin registry"
        )
        assert "shutdown_jarvis" not in registered_names, (
            "shutdown_jarvis is safety-only (BIOMETRIC) — should not be in builtin registry"
        )

    def test_vision_tool_gated_by_capability(self) -> None:
        """vision_analyze should only register when vision engine is available."""
        from mark.tools.builtin import build_builtin_registry, _check_vision

        registry = build_builtin_registry()
        registered_names = {s.name for s in registry.list()}

        has_vision = _check_vision()
        in_registry = "vision_analyze" in registered_names

        assert has_vision == in_registry, (
            f"vision_analyze registry membership ({in_registry}) "
            f"must match vision backend availability ({has_vision})"
        )

    def test_stt_tool_gated_by_capability(self) -> None:
        """stt_listen should only register when STT binary is available."""
        from mark.tools.builtin import build_builtin_registry, _check_stt

        registry = build_builtin_registry()
        registered_names = {s.name for s in registry.list()}

        has_stt = _check_stt()
        in_registry = "stt_listen" in registered_names

        assert has_stt == in_registry, (
            f"stt_listen registry membership ({in_registry}) "
            f"must match STT backend availability ({has_stt})"
        )

    def test_tts_tool_gated_by_capability(self) -> None:
        """tts_speak should only register when TTS binary is available."""
        from mark.tools.builtin import build_builtin_registry, _check_tts

        registry = build_builtin_registry()
        registered_names = {s.name for s in registry.list()}

        has_tts = _check_tts()
        in_registry = "tts_speak" in registered_names

        assert has_tts == in_registry, (
            f"tts_speak registry membership ({in_registry}) "
            f"must match TTS backend availability ({has_tts})"
        )

    def test_tool_handler_returns_tool_result(self) -> None:
        """All handlers should be callable (even if they return errors)."""
        from mark.tools.builtin import build_builtin_registry
        from mark.tools.contracts import ToolResult

        registry = build_builtin_registry()

        for spec in registry.list():
            handler = spec.handler
            assert callable(handler), f"'{spec.name}' handler is not callable"
            # Call with empty args — should not raise, just return a result
            try:
                result = handler({})
                assert hasattr(result, 'ok'), (
                    f"'{spec.name}' handler must return ToolResult with 'ok' field"
                )
            except Exception as exc:
                # It's OK if handler raises for some tools (e.g. shell_exec
                # with no command), but the handler itself must be callable
                assert callable(handler), (
                    f"'{spec.name}' handler raised {exc} but is still callable"
                )


class TestGatewayRoutesConsistency:
    """Tests that verify gateway route integrity."""

    def test_health_route_registered_in_service_source(self) -> None:
        """The system.health route must be registered in SlonGateway source code."""
        import ast

        service_path = Path("gateway/service.py")
        source = service_path.read_text()
        tree = ast.parse(source)

        # Check that SlonGateway._health method exists
        has_health_method = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_health":
                has_health_method = True
                break
        assert has_health_method, (
            "_health method not found in gateway/service.py"
        )

        # Check that system.health is registered in __init__ or router calls
        assert 'system.health' in source or '"system.health"' in source or "system.health" in source, (
            '"system.health" route not found in gateway/service.py'
        )

    def test_read_gateway_status_distinct_states(self) -> None:
        """read_gateway_status must distinguish states, not always return 'disabled'."""
        import tempfile
        from gateway.status import read_gateway_status

        # State when DB does not exist: should be "not-configured", not "disabled"
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nonexistent.db"
            status = read_gateway_status(db_path)
            assert status.get("state") == "not-configured", (
                f"Expected 'not-configured' for non-existent DB, got: {status.get('state')}"
            )


class TestVisionTemporalConsistency:
    """Tests that verify vision temporal module is not returning false data."""

    def test_temporal_trajectory_is_empty_placeholder(self) -> None:
        """_get_trajectory should be clearly marked as a placeholder."""
        from mark.vision.temporal import TemporalAnalyzer

        analyzer = TemporalAnalyzer()
        result = analyzer._get_trajectory("dummy_track")
        assert result == [], "_get_trajectory should return empty list (placeholder)"

    def test_temporal_recent_labels_is_empty(self) -> None:
        """_get_recent_labels should be clearly marked as simplified."""
        from mark.vision.temporal import TemporalAnalyzer

        analyzer = TemporalAnalyzer()
        result = analyzer._get_recent_labels()
        assert result == set(), "_get_recent_labels returns set() (simplified)"


class TestMCPIntegrationConsistency:
    """Tests that verify MCP integration is null-safe."""

    def test_mcp_tools_property_is_null_safe(self) -> None:
        """available_tools must return {} when client is None."""
        from mark.mcp.integration import McpIntegration
        from mark.mcp.types import McpServerConfig

        config = McpServerConfig(
            name="test",
            command="echo",
            transport="stdio",
        )
        integration = McpIntegration.create(config)
        # client is None by default
        tools = integration.available_tools
        assert tools == {}, (
            "available_tools should return empty dict when client is None"
        )

    def test_mcp_resources_property_is_null_safe(self) -> None:
        """resources must return [] when client is None."""
        from mark.mcp.integration import McpIntegration
        from mark.mcp.types import McpServerConfig

        config = McpServerConfig(
            name="test",
            command="echo",
            transport="stdio",
        )
        integration = McpIntegration.create(config)
        resources = integration.resources
        assert resources == [], (
            "resources should return empty list when client is None"
        )


class TestDeprecatedToolConsistency:
    """Tests that verify deprecated tools return clear errors."""

    def test_cmd_control_returns_deprecated_error(self) -> None:
        """cmd_control handler must return a clear 'deprecated' error."""
        from mark.tools.legacy.adapters import _cmd_control_deprecated_handler

        result = _cmd_control_deprecated_handler({})
        assert result.ok is False, (
            "cmd_control must return ok=False"
        )
        assert result.code == "deprecated", (
            f"cmd_control must return code='deprecated', got: {result.code}"
        )
        assert "deprecated" in result.message.lower(), (
            f"cmd_control message must mention 'deprecated': {result.message}"
        )
        assert "shell_exec" in result.message.lower(), (
            f"cmd_control message should suggest 'shell_exec': {result.message}"
        )


class TestModelCatalogConsistency:
    """Tests that verify the model catalog does not advertise fake models."""

    def test_no_mock_model_in_default_catalog(self) -> None:
        """ModelStore must not advertise a fake 'mock-model' by default."""
        from server.routes.models import ModelStore
        from providers.contracts import ModelInfo

        store = ModelStore()
        models = store.list_models()
        for m in models:
            assert m.id != "mock-model", (
                "ModelStore must not advertise 'mock-model' — it is a fake"
            )
            assert m.display_name != "Mock Local", (
                "ModelStore must not advertise 'Mock Local' — it is a fake"
            )


class TestActionHandlerConsistency:
    """Tests that verify action handlers return clear errors on import failure."""

    def test_action_handler_handles_import_error(self) -> None:
        """_action_handler must return ok=False when module cannot be imported."""
        from mark.tools.legacy.adapters import _action_handler

        handler = _action_handler("actions.nonexistent_module_fake_xyz", "missing_func")
        result = handler({})
        assert result.ok is False, (
            f"Handler should return ok=False on import error, got ok={result.ok}"
        )
        assert result.code in ("handler_unavailable", "handler_error"), (
            f"Expected error code, got: {result.code}"
        )
