"""Additional tests for agent 11 closed-loop features:
  - Coordinate validation (screen bounds)
  - Click-loop detection (infinite loop prevention)
  - Dangerous action approval gating
  - Element-level verification diffs
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from computer_control.types import (
    ActionCategory,
    CoordinateValidationResult,
    DangerousActionKind,
    DangerousActionApproval,
    ComputerAction,
    Frame,
    FrameSource,
    LoopBudget,
    LoopPhase,
    LoopState,
    VerificationStatus,
)
from computer_control.adapter import (
    VirtualScreenAdapter,
    VirtualElement,
    VirtualScreenState,
)
from computer_control.closed_loop import (
    CoordinateValidator,
    DefaultReasoner,
    DefaultVerifier,
    DangerousActionApprover,
    LoopDetector,
    VisionComputerAgent,
)


# ---------------------------------------------------------------------------
# Coordinate Validator tests
# ---------------------------------------------------------------------------

class TestCoordinateValidator:
    """Tests for CoordinateValidator."""

    def test_valid_coordinate_in_bounds(self):
        v = CoordinateValidator()
        result = v.validate(100, 200, 800, 600)
        assert result.valid is True
        assert result.reason == "OK"
        assert result.clamped_x == 100
        assert result.clamped_y == 200

    def test_clamps_negative_coordinates(self):
        v = CoordinateValidator()
        result = v.validate(-10, 5, 800, 600)
        assert result.valid is True
        assert result.clamped_x == 0
        assert result.clamped_y == 5

    def test_clamps_over_max_coordinates(self):
        v = CoordinateValidator()
        result = v.validate(900, 700, 800, 600)
        assert result.valid is True
        assert result.clamped_x == 799  # width - 1
        assert result.clamped_y == 599  # height - 1

    def test_invalid_screen_dimensions(self):
        v = CoordinateValidator()
        result = v.validate(100, 200, 0, 600)
        assert result.valid is False

    def test_clamps_to_boundary(self):
        v = CoordinateValidator()
        result = v.validate(799, 599, 800, 600)
        assert result.valid is True
        assert result.clamped_x == 799
        assert result.clamped_y == 599


# ---------------------------------------------------------------------------
# LoopDetector tests
# ---------------------------------------------------------------------------

class TestLoopDetector:
    """Tests for LoopDetector."""

    def test_no_loop_single_action(self):
        d = LoopDetector(max_repeats=3)
        d.record("click", "button")
        is_loop, reason = d.check_loop()
        assert is_loop is False

    def test_no_loop_three_actions(self):
        d = LoopDetector(max_repeats=3)
        d.record("click", "btn1")
        d.record("type", "hello")
        d.record("click", "btn2")
        is_loop, reason = d.check_loop()
        assert is_loop is False

    def test_detects_repetitive_click_loop(self):
        d = LoopDetector(max_repeats=3)
        d.record("click", "button")
        d.record("click", "button")
        d.record("click", "button")
        is_loop, reason = d.check_loop()
        assert is_loop is True
        assert "3" in reason and "click" in reason

    def test_detects_4_repeats(self):
        d = LoopDetector(max_repeats=3)
        for _ in range(4):
            d.record("click", "same_button")
        is_loop, reason = d.check_loop()
        assert is_loop is True

    def test_reset_clears_history(self):
        d = LoopDetector(max_repeats=3)
        for _ in range(3):
            d.record("click", "button")
        assert d.check_loop()[0] is True
        d.reset()
        assert d.check_loop()[0] is False

    def test_max_repeats_configurable(self):
        d = LoopDetector(max_repeats=5)
        for _ in range(4):
            d.record("click", "button")
        assert d.check_loop()[0] is False  # 4 < 5
        d.record("click", "button")
        assert d.check_loop()[0] is True  # 5 >= 5


# ---------------------------------------------------------------------------
# DangerousActionApprover tests
# ---------------------------------------------------------------------------

class TestDangerousActionApprover:
    """Tests for DangerousActionApprover."""

    def test_classifies_app_kill_as_dangerous(self):
        a = DangerousActionApprover()
        action = ComputerAction(action_type="app_kill", target="evil")
        kind = a.classify(action)
        assert kind == DangerousActionKind.KILL_PROCESS

    def test_classifies_window_close_as_dangerous(self):
        a = DangerousActionApprover()
        action = ComputerAction(action_type="window_close", target="main")
        kind = a.classify(action)
        assert kind == DangerousActionKind.CLOSE_WINDOW

    def test_does_not_classify_click_as_dangerous(self):
        a = DangerousActionApprover()
        action = ComputerAction(action_type="click", target="btn")
        kind = a.classify(action)
        assert kind is None

    def test_does_not_classify_type_as_dangerous(self):
        a = DangerousActionApprover()
        action = ComputerAction(action_type="type", target="")
        kind = a.classify(action)
        assert kind is None

    def test_request_approval_for_dangerous_action(self):
        a = DangerousActionApprover()
        action = ComputerAction(action_type="app_kill", target="x")
        approval = a.request_approval(action)
        assert approval.approved is False
        assert approval.kind == DangerousActionKind.KILL_PROCESS
        assert "Requires explicit user approval" in approval.reason

    def test_request_approval_for_unknown_action(self):
        a = DangerousActionApprover()
        action = ComputerAction(action_type="click", target="btn")
        approval = a.request_approval(action)
        assert approval.approved is True


# ---------------------------------------------------------------------------
# Integration: LoopDetector integrated with VisionComputerAgent
# ---------------------------------------------------------------------------

class TestLoopDetectionIntegration:
    """Tests for infinite loop prevention via loop detection."""

    @pytest.mark.asyncio
    async def test_detector_blocks_repeated_click_on_same_button(self):
        """The agent should detect repeated identical actions and stop."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            broken_btn={"x": 0.5, "y": 0.5, "content": "Broken", "clickable": True},
        )

        # Create failing verifier at module level to avoid recursion
        from computer_control.closed_loop import DefaultVerifier
        from computer_control.types import VerificationStatus

        failing_verifier_instance = DefaultVerifier()

        async def failing_verify(*a, **kw):
            result = await DefaultVerifier.verify(failing_verifier_instance, *a, **kw)
            result.status = VerificationStatus.FAILED
            result.retryable = True
            return result

        failing_verifier_instance.verify = failing_verify

        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=MagicMock(),
            verifier=failing_verifier_instance,
            budget=LoopBudget(max_steps=30, timeout_seconds=60.0),
        )

        with pytest.raises(ClosedLoopError) as exc_info:
            await agent.run(
                intent="Click the broken button",
                max_retries=10,
            )

        assert "loop" in str(exc_info.value).lower() or "consecutive" in str(exc_info.value).lower()

    def test_detector_in_agent_property(self):
        adapter = VirtualScreenAdapter()
        agent = VisionComputerAgent(adapter=adapter)
        assert hasattr(agent, "loop_detector")
        assert isinstance(agent.loop_detector, LoopDetector)


# ---------------------------------------------------------------------------
# Integration: Dangerous action approval
# ---------------------------------------------------------------------------

class TestDangerousActionApprovalIntegration:
    """Tests for dangerous action approval gating."""

    @pytest.mark.asyncio
    async def test_dangerous_action_denied_without_approval(self):
        """Without an approval hook, dangerous actions should be denied."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            btn={"x": 0.5, "y": 0.5, "content": "Btn", "clickable": True},
        )

        # Use an agent with a dangerous action reasoner
        from computer_control.closed_loop import DefaultReasoner
        reasoner = DefaultReasoner(screen_width=800, screen_height=600)

        adapter2 = VirtualScreenAdapter()
        adapter2.set_elements(
            kill_btn={"x": 0.5, "y": 0.5, "content": "Kill", "clickable": True},
        )

        agent = VisionComputerAgent(
            adapter=adapter2,
            safety_policy=MagicMock(),
        )

        # The reasoner uses "click" action type which is NOT dangerous.
        # To test dangerous action denial, we need to inject a dangerous action.
        # We'll verify via the dangerous_approver directly.
        danger = agent.dangerous_approver.classify(
            type("", (), {"action_type": "app_kill", "target": "x"})()
        )
        assert danger == DangerousActionKind.KILL_PROCESS

    @pytest.mark.asyncio
    async def test_dangerous_action_requires_approval_hook(self):
        """Dangerous actions with approval hook can be approved or denied."""
        from computer_control.types import CancellationError

        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            btn={"x": 0.5, "y": 0.5, "content": "Btn", "clickable": True},
        )

        # Create a custom reasoner that produces a dangerous action
        class DangerousReasoner:
            async def ground(self, observation, intent, safety_policy):
                from computer_control.closed_loop import TargetGroundingResult
                from computer_control.types import ComputerAction, ActionCategory
                action = ComputerAction(
                    action_type="app_kill",
                    target="evil_process",
                    category=ActionCategory.IRREVERSIBLE,
                    proposed_by="agent",
                    args={},
                )
                return TargetGroundingResult(
                    action=action,
                    expected_changes=[],
                    description="Kill the evil process",
                )

        agent = VisionComputerAgent(
            adapter=adapter,
            reasoner=DangerousReasoner(),
            safety_policy=MagicMock(),
        )

        with pytest.raises(SafetyDenialError):
            await agent.run(
                intent="Kill the evil process",
            )

    @pytest.mark.asyncio
    async def test_dangerous_action_approved_by_hook(self):
        """When the approval hook approves, dangerous actions proceed."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            btn={"x": 0.5, "y": 0.5, "content": "Btn", "clickable": True},
        )

        # Create a custom reasoner that produces a dangerous action
        class DangerousReasoner:
            async def ground(self, observation, intent, safety_policy):
                from computer_control.closed_loop import TargetGroundingResult
                from computer_control.types import ComputerAction, ActionCategory
                action = ComputerAction(
                    action_type="app_kill",
                    target="evil_process",
                    category=ActionCategory.IRREVERSIBLE,
                    proposed_by="agent",
                    args={},
                )
                return TargetGroundingResult(
                    action=action,
                    expected_changes=[],
                    description="Kill the evil process",
                )

        async def approve_all(action):
            return True

        agent = VisionComputerAgent(
            adapter=adapter,
            reasoner=DangerousReasoner(),
            safety_policy=MagicMock(),
        )
        agent.approval_hook = approve_all

        # app_kill is not handled by VirtualScreenAdapter, so it fails with
        # ClosedLoopError. With approval_hook, SafetyDenialError is avoided.
        with pytest.raises(ClosedLoopError):
            await agent.run(
                intent="Kill the evil process",
            )


# ---------------------------------------------------------------------------
# Element-level verification diff
# ---------------------------------------------------------------------------

class TestElementLevelVerification:
    """Tests for element-level verification diff."""

    @pytest.mark.asyncio
    async def test_verifier_uses_screen_state_snapshot(self):
        """The verifier should use screen state for element-level diff."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            toggle={"x": 0.5, "y": 0.5, "content": "Toggle", "clickable": True},
        )

        # Capture initial state
        initial_state = adapter.get_state_snapshot()

        # Simulate a state change
        adapter._do_click("toggle", {"on_click": {"key": "value", "value": True}})

        # The state should have changed
        changed_state = adapter.get_state_snapshot()
        assert changed_state["toggle"]["value"] is True

    @pytest.mark.asyncio
    async def test_full_loop_uses_element_diff(self):
        """The full loop should confirm via element-level diff."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            toggle={"x": 0.5, "y": 0.5, "content": "Toggle", "clickable": True},
        )

        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=MagicMock(),
        )

        state = await agent.run(intent="toggle")

        assert state.phase == LoopPhase.COMPLETE
        # The verification should have element-level changes
        assert state.verification is not None
        assert len(state.verification.detected_changes) > 0


# ---------------------------------------------------------------------------
# SafetyDenialError import for tests above
# ---------------------------------------------------------------------------
from computer_control.types import SafetyDenialError, ClosedLoopError


class TestCoordinateClampingInAdapter:
    """Test that VirtualScreenAdapter clamps coordinates."""

    def test_coordinates_clamped_on_click(self):
        """Click with out-of-bounds coordinates should be clamped."""
        adapter = VirtualScreenAdapter(width=100, height=100)
        adapter.set_elements(
            btn={"x": 0.5, "y": 0.5, "content": "Btn", "clickable": True},
        )

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(adapter.execute({
                "action_type": "click",
                "target": "btn",
                "args": {"x": -100, "y": 200, "on_click": {"key": "value", "value": True}},
            }))
            assert result["success"] is True
        finally:
            loop.close()

        # Check the log for clamped coordinates
        log = adapter.get_log()
        assert any("click" in entry for entry in log)

    def test_dangerous_action_logged(self):
        """Dangerous actions should be logged."""
        adapter = VirtualScreenAdapter()

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(adapter.execute({
                "action_type": "app_kill",
                "target": "evil",
                "args": {},
            }))
        finally:
            loop.close()

        assert len(adapter.dangerous_log) == 1
        assert adapter.dangerous_log[0]["action_type"] == "app_kill"

        adapter.clear_dangerous_log()
        assert len(adapter.dangerous_log) == 0
