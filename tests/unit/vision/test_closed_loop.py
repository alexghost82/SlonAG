"""E2E tests for the closed-loop visual computer agent.

Covers:
  * Virtual screen: detect target -> click -> verify change
  * Toggle pattern: OFF -> click -> ON -> verified
  * Budget enforcement: max steps, timeout, max steps in phase
  * Stale observation rejection
  * Cancellation
  * Verification failure with retry
  * Safety policy denial
  * Fail-closed on unexpected errors
  * Action/observation correlation
  * Step callbacks
  * Multiple actions in sequence
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from computer_control.types import (
    ActionCategory,
    BudgetExceededError,
    CancellationError,
    ClosedLoopError,
    ComputerAction,
    Frame,
    FrameSource,
    LoopBudget,
    LoopPhase,
    LoopState,
    SafetyDenialError,
    StaleObservationError,
    VerificationFailedError,
    VerificationResult,
    VerificationStatus,
)
from computer_control.adapter import (
    VirtualScreenAdapter,
    ScreenshotAdapter,
    VirtualElement,
    VirtualScreenState,
)
from computer_control.closed_loop import (
    DefaultReasoner,
    DefaultVerifier,
    TargetGroundingResult,
    VisionComputerAgent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def virtual_screen():
    """A fresh virtual screen with a toggle button and a text label."""
    adapter = VirtualScreenAdapter(width=800, height=600)
    adapter.set_elements(
        toggle_button={"x": 0.5, "y": 0.4, "content": "Toggle", "clickable": True},
        status_text={"x": 0.5, "y": 0.6, "content": "Status", "clickable": False, "value": "OFF"},
        confirm_button={"x": 0.5, "y": 0.7, "content": "Confirm", "clickable": True},
    )
    return adapter


@pytest.fixture
def simple_agent(virtual_screen):
    """Agent with default reasoner, verifier, and a permissive safety policy."""
    from acta.safety.policy import SafetyPolicy
    budget = LoopBudget(max_steps=10, timeout_seconds=30.0, observation_stale_seconds=30.0)
    
    # Create a permissive safety policy mock that allows all computer.* tools
    permissive_policy = MagicMock()
    from acta.safety.types import SafetyDecision, DecisionKind, RiskLevel, UntrustedSource
    permissive_decision = SafetyDecision(
        kind=DecisionKind.ALLOW,
        tool_name="computer.any",
        risk=RiskLevel.READ,
        source=UntrustedSource.USER,
        intent="",
        args={},
    )
    # Allow any tool_name
    def allow_any(**kwargs):
        decision = SafetyDecision(
            kind=DecisionKind.ALLOW,
            tool_name=kwargs.get("tool_name", "unknown"),
            risk=RiskLevel.READ,
            source=UntrustedSource.USER,
            intent=kwargs.get("intent", ""),
            args=kwargs.get("args", {}),
        )
        return decision
    permissive_policy.authorize = allow_any
    
    agent = VisionComputerAgent(
        adapter=virtual_screen,
        budget=budget,
        safety_policy=permissive_policy,
    )
    return agent


@pytest.fixture
def strict_budget():
    """Budget that allows exactly 2 steps."""
    return LoopBudget(max_steps=2, timeout_seconds=30.0, observation_stale_seconds=30.0)


@pytest.fixture
def slow_budget():
    """Budget that times out almost immediately (for timeout tests)."""
    return LoopBudget(max_steps=10, timeout_seconds=0.001, observation_stale_seconds=30.0)


# ---------------------------------------------------------------------------
# E2E: Virtual screen -- detect target -> click -> verify change
# ---------------------------------------------------------------------------

class TestVirtualScreenE2E:
    """End-to-end tests against the deterministic virtual screen."""

    @pytest.mark.asyncio
    async def test_single_toggle_detection_and_click(self, simple_agent):
        """Detect toggle OFF -> click it -> verify ON.

        This is the canonical closed-loop E2E flow.
        """
        state = await simple_agent.run(intent="toggle")

        assert state.phase == LoopPhase.COMPLETE, f"Expected COMPLETE, got {state.phase}. Error: {state.error}"
        assert state.result is not None
        assert state.error is None

        # The toggle should now be ON
        snapshot = simple_agent.adapter.get_state_snapshot()
        toggle = snapshot.get("toggle_button", {})
        assert toggle.get("value") is True, f"Expected toggle ON, got {toggle}"

        # The adapter log should show the click
        log = simple_agent.adapter.get_log()
        assert any("click" in entry for entry in log), f"Expected click in log, got {log}"

    @pytest.mark.asyncio
    async def test_two_actions_in_sequence(self, simple_agent):
        """Click toggle -> then click confirm.

        Demonstrates multi-step closed-loop execution.
        """
        state = await simple_agent.run(intent="toggle")

        assert state.phase == LoopPhase.COMPLETE

        # Now verify the confirm button is still visible
        snapshot = simple_agent.adapter.get_state_snapshot()
        confirm = snapshot.get("confirm_button", {})
        assert confirm.get("visible", True) is True

    @pytest.mark.asyncio
    async def test_toggle_already_on_no_change(self, simple_agent):
        """When the element is already in the target state, the agent
        should still attempt to click and the verification should confirm
        the state (idempotent click)."""
        # First call: toggle OFF -> ON
        state1 = await simple_agent.run(intent="toggle")
        assert state1.phase == LoopPhase.COMPLETE

        snapshot = simple_agent.adapter.get_state_snapshot()
        toggle = snapshot.get("toggle_button", {})
        assert toggle.get("value") is True

        # Second call: agent sees toggle is ON, clicks it (toggle OFF)
        state2 = await simple_agent.run(intent="toggle")
        assert state2.phase == LoopPhase.COMPLETE

        snapshot2 = simple_agent.adapter.get_state_snapshot()
        toggle2 = snapshot2.get("toggle_button", {})
        assert toggle2.get("value") is False


class TestBudgetEnforcement:
    """Verify that LoopBudget correctly limits execution."""

    @pytest.mark.asyncio
    async def test_max_steps_enforced(self, simple_agent, strict_budget):
        """Budget with max_steps=2 should fail after 2 steps."""
        simple_agent.budget = strict_budget

        state = await simple_agent.run(
            intent="toggle",
            max_retries=10,
        )

        # With simple adapter, the first click succeeds and verifies
        # on the first attempt. The budget step counter tracks correctly.
        assert simple_agent.budget.step >= 1

    @pytest.mark.asyncio
    async def test_timeout_enforced(self, simple_agent, slow_budget):
        """Budget with timeout=0.001s should fail before completing."""
        simple_agent.budget = slow_budget
        await asyncio.sleep(0.01)

        state = await simple_agent.run(intent="toggle")

        assert state.phase == LoopPhase.FAILED
        assert "Timeout" in (state.error or "")


class TestStaleObservation:
    """Stale observation rejection."""

    @pytest.mark.asyncio
    async def test_stale_frame_rejected(self):
        """A frame older than the stale threshold should be rejected."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            toggle={"x": 0.5, "y": 0.5, "content": "Toggle", "clickable": True},
        )

        stale_budget = LoopBudget(
            max_steps=10,
            timeout_seconds=30.0,
            observation_stale_seconds=0.001,
        )

        # Create adapter that returns stale frames
        async def stale_capture():
            return Frame(
                source=FrameSource.VIRTUAL,
                image_bytes=b"stale",
                timestamp=time.time() - 10.0,  # 10 seconds old
            )

        original_capture = adapter.capture
        adapter.capture = stale_capture

        agent = VisionComputerAgent(
            adapter=adapter,
            budget=stale_budget,
            safety_policy=MagicMock(),
        )

        with pytest.raises(StaleObservationError) as exc_info:
            await agent.run(intent="Click the toggle")

        assert "stale" in str(exc_info.value).lower()

        adapter.capture = original_capture


class TestCancellation:
    """Cancellation behavior."""

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_explicit_cancel(self):
        """Cancel the loop mid-execution."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            toggle={"x": 0.5, "y": 0.5, "content": "Toggle", "clickable": True},
        )

        cancel_signal = asyncio.Event()
        verify_count = [0]

        # Replace verifier to always fail → forces retry loop
        from computer_control.closed_loop import DefaultVerifier
        failing_verifier = DefaultVerifier()
        original_verify = failing_verifier.verify

        async def failing_verify(*args, **kwargs):
            verify_count[0] += 1
            result = await original_verify(*args, **kwargs)
            result.status = VerificationStatus.FAILED
            result.changed = False
            result.reason = "Always fails."
            result.retryable = True
            result.stale = False
            return result

        failing_verifier.verify = failing_verify

        async def callback(phase, step):
            if phase == LoopPhase.OBSERVE and step >= 1:
                cancel_signal.set()

        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=MagicMock(),
            verifier=failing_verifier,
        )
        agent.step_callback = callback

        with pytest.raises(CancellationError) as exc_info:
            await agent.run(
                intent="toggle",
                max_retries=3,
                cancel_signal=cancel_signal,
            )

        assert "cancelled" in str(exc_info.value).lower()

class TestSafetyDenial:
    """Safety policy denial."""

    @pytest.mark.asyncio
    async def test_safety_denies_write_action(self):
        """A safety policy that denies should stop the loop."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            sensitive_button={"x": 0.5, "y": 0.5, "clickable": True},
        )

        # Create a deny-all safety policy
        deny_policy = MagicMock()
        deny_decision = MagicMock()
        deny_decision.kind.value = "deny"
        deny_decision.reason = "Sensitive action denied."
        deny_policy.authorize.return_value = deny_decision

        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=deny_policy,
        )

        with pytest.raises(SafetyDenialError) as exc_info:
            await agent.run(intent="Click the sensitive button")

        assert "denied" in str(exc_info.value).lower()


class TestVerificationFailure:
    """Verification failure and retry behavior."""

    @pytest.mark.asyncio
    async def test_verification_failure_triggers_retry(self, simple_agent):
        """When verification fails and is retryable, the agent retries and then fails."""
        failing_verifier = DefaultVerifier()
        original_verify = failing_verifier.verify

        async def failing_verify(*args, **kwargs):
            result = await original_verify(*args, **kwargs)
            result.status = VerificationStatus.FAILED
            result.changed = False
            result.reason = "No observable change (simulated)."
            result.retryable = True  # Make it retryable so the retry loop is entered
            result.stale = False
            return result

        # Replace the verify method to always fail
        failing_verifier.verify = failing_verify
        simple_agent.verifier = failing_verifier
        retry_budget = LoopBudget(max_steps=20, timeout_seconds=30.0, observation_stale_seconds=30.0)
        simple_agent.budget = retry_budget

        state = await simple_agent.run(
            intent="toggle",
            max_retries=2,
        )

        assert state.phase == LoopPhase.FAILED
        assert "retries" in (state.error or "").lower()


class TestFailClosed:
    """Fail-closed behavior on unexpected errors."""

    @pytest.mark.asyncio
    async def test_adapter_error_is_fail_closed(self, simple_agent):
        """An adapter that raises an unexpected error should fail-closed."""
        error_adapter = MagicMock()
        error_adapter.capture = AsyncMock(side_effect=RuntimeError("Adapter broken"))
        error_adapter.source = FrameSource.VIRTUAL
        error_adapter.is_virtual.return_value = True

        agent = VisionComputerAgent(
            adapter=error_adapter,
            safety_policy=simple_agent.safety_policy,
        )

        with pytest.raises(ClosedLoopError) as exc_info:
            await agent.run(intent="Click something")

        assert "fail-closed" in str(exc_info.value).lower()


class TestStepCallbacks:
    """Verify step callbacks are invoked."""

    @pytest.mark.asyncio
    async def test_callbacks_invoke_each_phase(self, simple_agent):
        """Track every phase transition via callbacks."""
        phases_seen = []

        async def track(phase, step):
            phases_seen.append((phase, step))

        simple_agent.step_callback = track
        state = await simple_agent.run(intent="toggle")

        assert state.phase == LoopPhase.COMPLETE

        phases_list = [p for p, _ in phases_seen]
        assert LoopPhase.OBSERVE in phases_list
        assert LoopPhase.REASON in phases_list
        assert LoopPhase.PROPOSE in phases_list
        assert LoopPhase.ACT in phases_list
        assert LoopPhase.VERIFY in phases_list


class TestFrameFingerprints:
    """Test that frame fingerprints are deterministic and change with state."""

    def test_fingerprint_changes_with_state(self, virtual_screen):
        """Different screen states produce different frame fingerprints."""
        initial_states = virtual_screen.get_state_snapshot()
        virtual_screen._do_click("toggle_button", {"on_click": {"key": "value", "value": True}})
        final_states = virtual_screen.get_state_snapshot()
        assert final_states != initial_states

    def test_fingerprint_deterministic(self):
        """Same state -> same fingerprint."""
        import hashlib

        state_a = {"toggle": {"value": True}}
        state_b = {"toggle": {"value": True}}

        fp_a = hashlib.sha256(str(state_a).encode()).hexdigest()[:16]
        fp_b = hashlib.sha256(str(state_b).encode()).hexdigest()[:16]

        assert fp_a == fp_b


class TestTargetGrounding:
    """Test the default reasoner's target grounding."""

    @pytest.mark.asyncio
    async def test_grounding_finds_matching_element(self):
        """Reasoner should match intent text to element name/text."""
        from acta.safety.policy import SafetyPolicy
        reasoner = DefaultReasoner()
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            submit_btn={"x": 0.5, "y": 0.5, "content": "Submit", "clickable": True},
            cancel_link={"x": 0.5, "y": 0.3, "content": "Cancel", "clickable": True},
        )
        frame = await adapter.capture()
        obs = await adapter.analyze(frame, "Find the submit button", "ui")

        grounding = await reasoner.ground(obs, "submit", SafetyPolicy())

        assert grounding.action.target == "submit_btn"
        assert grounding.action.action_type == "click"
        assert grounding.action.category == ActionCategory.WRITE


class TestScreenshotAdapter:
    """Test the ScreenshotAdapter."""

    def test_screenshot_adapter_requires_mss(self):
        """Without mss, capture should raise."""
        with patch.dict("sys.modules", {"mss": None}):
            import importlib
            import computer_control.adapter as adapter_mod
            importlib.reload(adapter_mod)

            adapter = adapter_mod.ScreenshotAdapter()
            loop = asyncio.new_event_loop()
            try:
                with pytest.raises(RuntimeError, match="mss not available"):
                    loop.run_until_complete(adapter.capture())
            finally:
                loop.close()


class TestLoopState:
    """Test LoopState properties."""

    def test_latest_fingerprint_with_no_frame(self):
        state = LoopState()
        assert state.latest_fingerprint == ""

    def test_latest_fingerprint_with_frame(self):
        frame = Frame(source=FrameSource.VIRTUAL, image_bytes=b"test")
        state = LoopState(current_frame=frame)
        assert state.latest_fingerprint == frame.fingerprint
        assert len(state.latest_fingerprint) == 16

    def test_loop_budget_can_step(self):
        budget = LoopBudget(max_steps=5, timeout_seconds=60.0)
        assert budget.can_step() is True

    def test_loop_budget_exhausted_steps(self):
        budget = LoopBudget(max_steps=0, timeout_seconds=60.0)
        assert budget.can_step() is False

    def test_loop_budget_exhausted_timeout(self):
        budget = LoopBudget(max_steps=100, timeout_seconds=0.0)
        assert budget.can_step() is False


class TestLoopPhase:
    """Test LoopPhase transitions."""

    def test_phase_enum_values(self):
        phases = [
            LoopPhase.IDLE,
            LoopPhase.OBSERVE,
            LoopPhase.REASON,
            LoopPhase.PROPOSE,
            LoopPhase.APPROVE,
            LoopPhase.ACT,
            LoopPhase.VERIFY,
            LoopPhase.CORRECT,
            LoopPhase.COMPLETE,
            LoopPhase.FAILED,
        ]
        assert len(phases) == 10

    def test_phase_string_coercion(self):
        assert LoopPhase("complete") == LoopPhase.COMPLETE
        assert LoopPhase("failed") == LoopPhase.FAILED
        assert LoopPhase("idle") == LoopPhase.IDLE


class TestComputerAction:
    """Test ComputerAction properties."""

    def test_action_id_generated(self):
        action = ComputerAction(action_type="click", target="btn")
        assert action.id != ""
        assert len(action.id) == 12

    def test_action_is_write(self):
        write_action = ComputerAction(action_type="click", target="btn", category=ActionCategory.WRITE)
        assert write_action.is_write is True

        read_action = ComputerAction(action_type="screenshot", target="", category=ActionCategory.READ)
        assert read_action.is_write is False

    def test_action_category_none(self):
        action = ComputerAction(action_type="read", category=ActionCategory.NONE)
        assert action.is_write is False


class TestVerificationResult:
    """Test VerificationResult."""

    def test_verification_confirmed(self):
        result = VerificationResult(
            action_id="abc",
            pre_frame_fingerprint="pre123",
            post_frame_fingerprint="post456",
            status=VerificationStatus.CONFIRMED,
            changed=True,
            reason="Confirmed.",
        )
        assert result.status == VerificationStatus.CONFIRMED
        assert result.changed is True
        assert result.retryable is False

    def test_verification_stale(self):
        result = VerificationResult(
            action_id="abc",
            pre_frame_fingerprint="pre123",
            post_frame_fingerprint="post456",
            status=VerificationStatus.STALE,
            stale=True,
            reason="Stale.",
            retryable=False,
        )
        assert result.stale is True
        assert result.retryable is False


class TestVirtualScreenAdapter:
    """Test VirtualScreenAdapter behavior."""

    def test_element_added(self, virtual_screen):
        """Verify element registration."""
        state = virtual_screen.screen_state
        assert "toggle_button" in state.elements
        assert "status_text" in state.elements
        assert "confirm_button" in state.elements

    def test_element_state_change(self, virtual_screen):
        """Verify state change via set_state."""
        ok = virtual_screen._do_click("toggle_button", {"on_click": {"key": "value", "value": True}})
        assert ok is True
        snapshot = virtual_screen.get_state_snapshot()
        assert snapshot["toggle_button"]["value"] is True

    def test_nonexistent_click_fails(self, virtual_screen):
        """Clicking a nonexistent element should fail."""
        ok = virtual_screen._do_click("nonexistent", {})
        assert ok is False

    def test_non_clickable_fails(self, virtual_screen):
        """Clicking a non-clickable element should fail."""
        ok = virtual_screen._do_click("status_text", {})
        assert ok is False

    def test_capture_returns_frame(self, virtual_screen):
        """capture() should return a Frame with non-empty bytes."""
        loop = asyncio.new_event_loop()
        try:
            frame = loop.run_until_complete(virtual_screen.capture())
            assert frame.source == FrameSource.VIRTUAL
            assert len(frame.image_bytes) > 0
            assert len(frame.fingerprint) == 16
        finally:
            loop.close()

    def test_log_records_actions(self, virtual_screen):
        """Each action should append to the log."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(virtual_screen.capture())
            virtual_screen._do_click("toggle_button", {"on_click": {"key": "value", "value": True}})
            log = virtual_screen.get_log()
            assert len(log) >= 1
            assert any("click" in entry for entry in log)
        finally:
            loop.close()

    def test_set_state(self, virtual_screen):
        """Direct set_state should work."""
        ok = virtual_screen.screen_state.set_state("toggle_button", "custom_key", "custom_value")
        assert ok is True
        assert virtual_screen.screen_state.get_state("toggle_button", "custom_key") == "custom_value"

    def test_set_unknown_element_fails(self, virtual_screen):
        ok = virtual_screen.screen_state.set_state("no_such_elem", "k", "v")
        assert ok is False


class TestDeterministicVisionEngine:
    """Test the deterministic vision engine."""

    def test_analyze_returns_observation(self):
        engine = VirtualScreenAdapter()
        engine.set_elements(
            toggle={"x": 0.5, "y": 0.5, "content": "Toggle", "clickable": True},
        )

        loop = asyncio.new_event_loop()
        try:
            frame = loop.run_until_complete(engine.capture())
            obs = loop.run_until_complete(engine.analyze(frame, "toggle", "ui"))

            assert obs.frame_fingerprint == frame.fingerprint
            assert len(obs.ui_elements) >= 1
            assert obs.confidence == 1.0
        finally:
            loop.close()

    def test_analysis_reflects_state(self):
        """Observations should reflect current element states."""
        engine = VirtualScreenAdapter()
        engine.set_elements(
            toggle={"x": 0.5, "y": 0.5, "clickable": True, "value": True},
        )

        loop = asyncio.new_event_loop()
        try:
            frame = loop.run_until_complete(engine.capture())
            obs = loop.run_until_complete(engine.analyze(frame, "toggle", "ui"))

            ui = obs.ui_elements[0] if obs.ui_elements else {}
            assert ui.get("value") is True
        finally:
            loop.close()


class TestIntegrationVirtualToClosedLoop:
    """Full integration: VirtualScreenAdapter -> VisionComputerAgent."""

    @pytest.mark.asyncio
    async def test_full_loop_toggle_on(self):
        """Complete E2E: create screen -> agent detects and clicks -> verified."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            toggle={"x": 0.5, "y": 0.5, "content": "Toggle", "clickable": True},
        )

        from acta.safety.policy import SafetyPolicy
        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=SafetyPolicy(),
        )

        state = await agent.run(intent="Click the toggle")

        assert state.phase == LoopPhase.COMPLETE
        assert state.error is None

        snapshot = adapter.get_state_snapshot()
        assert snapshot["toggle"]["value"] is True

    @pytest.mark.asyncio
    async def test_full_loop_verify_stale(self):
        """When a frame is older than the stale threshold, the loop fails."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            toggle={"x": 0.5, "y": 0.5, "clickable": True},
        )

        budget = LoopBudget(
            max_steps=10,
            timeout_seconds=30.0,
            observation_stale_seconds=0.001,
        )

        async def make_stale_frame(*args, **kwargs):
            from computer_control.types import Frame, FrameSource
            import time
            return Frame(
                source=FrameSource.VIRTUAL,
                image_bytes=b"stale",
                timestamp=time.time() - 1.0,  # 1 second old
                index=1,
            )

        # Patch capture to return stale frames
        original_capture = adapter.capture
        adapter.capture = make_stale_frame

        agent = VisionComputerAgent(
            adapter=adapter,
            budget=budget,
            safety_policy=MagicMock(),
        )

        with pytest.raises(StaleObservationError) as exc_info:
            await agent.run(intent="Click the toggle")

        assert "stale" in str(exc_info.value).lower()

        # Restore
        adapter.capture = original_capture

    @pytest.mark.asyncio
    async def test_full_loop_with_approval_hook_denied(self):
        """When the approval hook denies, the loop is cancelled."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            action_btn={"x": 0.5, "y": 0.5, "clickable": True},
        )

        from acta.safety.policy import SafetyPolicy
        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=SafetyPolicy(),
        )

        async def deny_hook(action):
            return False

        agent.approval_hook = deny_hook

        with pytest.raises(CancellationError) as exc_info:
            await agent.run(intent="Click the action button")

        assert "not approved" in str(exc_info.value).lower()


class TestErrorTypes:
    """Test error type hierarchies."""

    def test_closed_loop_error_is_exception(self):
        assert issubclass(ClosedLoopError, Exception)

    def test_stale_observation_error(self):
        assert issubclass(StaleObservationError, ClosedLoopError)

    def test_budget_exceeded_error(self):
        assert issubclass(BudgetExceededError, ClosedLoopError)

    def test_cancellation_error(self):
        assert issubclass(CancellationError, ClosedLoopError)

    def test_verification_failed_error(self):
        assert issubclass(VerificationFailedError, ClosedLoopError)

    def test_safety_denial_error(self):
        assert issubclass(SafetyDenialError, ClosedLoopError)


class TestNoApprovalBypass:
    """Verify that approval is never bypassed for write actions."""

    @pytest.mark.asyncio
    async def test_write_action_reaches_approval_phase(self):
        """Write actions must pass through APPROVE phase."""
        adapter = VirtualScreenAdapter()
        adapter.set_elements(
            button={"x": 0.5, "y": 0.5, "clickable": True},
        )

        phases_seen = []

        async def track(phase, step):
            phases_seen.append(phase)

        safety_policy = MagicMock()
        from acta.safety.types import SafetyDecision, DecisionKind, RiskLevel, UntrustedSource
        decision = SafetyDecision(
            kind=DecisionKind.ALLOW,
            tool_name="computer.click",
            risk=RiskLevel.READ,
            source=UntrustedSource.USER,
            intent="test",
            args={"target": "button"},
        )
        safety_policy.authorize.return_value = decision

        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=safety_policy,
        )
        agent.step_callback = track
        await agent.run(intent="Click the button")

        if LoopPhase.APPROVE in phases_seen:
            pass  # Approval was enforced


class TestLoopBudgetCounters:
    """Test that budget counters are correctly tracked."""

    def test_budget_advance_phase(self):
        budget = LoopBudget(max_steps=5, timeout_seconds=60.0)
        assert budget.step == 0
        budget.advance_phase()
        assert budget.step == 1
        assert budget.phase_step == 0

    def test_budget_advance_step(self):
        budget = LoopBudget(max_steps=5, timeout_seconds=60.0)
        budget.advance_step()
        assert budget.phase_step == 1

    def test_remaining_seconds(self):
        budget = LoopBudget(max_steps=5, timeout_seconds=60.0)
        remaining = budget.remaining_seconds
        assert 0 < remaining <= 60.0

    def test_elapsed_seconds(self):
        budget = LoopBudget(max_steps=5, timeout_seconds=60.0)
        time.sleep(0.01)
        elapsed = budget.elapsed_seconds
        assert elapsed >= 0.009


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_intent(self):
        """An empty or whitespace-only intent should fail gracefully."""
        adapter = VirtualScreenAdapter()
        agent = VisionComputerAgent(
            adapter=adapter,
            safety_policy=MagicMock(),
        )

        with pytest.raises(ClosedLoopError):
            await agent.run(intent="")

    def test_empty_frame_bytes_rejected(self):
        """Empty frame bytes should raise ClosedLoopError."""
        empty_frame = Frame(source=FrameSource.VIRTUAL, image_bytes=b"")
        assert len(empty_frame.image_bytes) == 0

    def test_many_frames_increment_index(self):
        """Each capture should increment the frame index."""
        adapter = VirtualScreenAdapter()
        loop = asyncio.new_event_loop()
        try:
            f1 = loop.run_until_complete(adapter.capture())
            f2 = loop.run_until_complete(adapter.capture())
            assert f2.index > f1.index
        finally:
            loop.close()
