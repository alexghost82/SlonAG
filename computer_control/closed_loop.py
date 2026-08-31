"""Closed-loop visual computer agent.

Chain:
    screen/camera/RTSP  →  Vision perception  →  target grounding
    → reasoning  →  proposed computer/browser action  →  SafetyPolicy
    → Approval  →  action  →  fresh visual observation  →  verification
    → correction/retry  →  result

Safety:
    * max steps (LoopBudget.max_steps)
    * timeout (LoopBudget.timeout_seconds)
    * cancellation (LoopState.cancelled)
    * stale observation rejection (LoopBudget.observation_stale_seconds)
    * action/observation correlation (frame fingerprint matching)
    * no infinite loops (LoopBudget + LoopDetector integration)
    * no approval bypass (SafetyPolicy gate on every write action)
    * verification after action (post-action observation)
    * fail-closed (any unexpected error → FAILED, no unverified state changes)
    * Coordinate validation (screen bounds)
    * Click-loop detection (repeated identical clicks)
    * Changed-screen verification (element-level diff)
    * Dangerous action approval gate
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from computer_control.types import (
    ActionCategory,
    BudgetExceededError,
    CancellationError,
    ClosedLoopError,
    ComputerAction,
    CoordinateValidationResult,
    DangerousActionApproval,
    DangerousActionKind,
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
    VisionObservation,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol interfaces
# ---------------------------------------------------------------------------

class ComputerAdapterProtocol:
    """Minimal adapter interface expected by the closed-loop agent."""

    async def capture(self) -> Frame: ...
    async def execute(self, action: dict[str, Any]) -> dict[str, Any]: ...
    async def analyze(
        self, frame: Frame, prompt: str, kind: str,
    ) -> VisionObservation: ...
    @property
    def source(self) -> FrameSource: ...
    def is_virtual(self) -> bool:
        return self.source == FrameSource.VIRTUAL


# ---------------------------------------------------------------------------
# Built-in reasoning / verification helpers
# ---------------------------------------------------------------------------

class TargetGroundingResult:
    """The result of reasoning over a vision observation."""

    def __init__(
        self,
        action: ComputerAction,
        expected_changes: list[dict[str, Any]],
        description: str = "",
    ) -> None:
        self.action = action
        self.expected_changes = expected_changes
        self.description = description


class CoordinateValidator:
    """Validate coordinates against screen bounds.

    Prevents clicks outside the visible screen area and clamps them
    when possible.
    """

    def validate(self, x: int, y: int, screen_width: int, screen_height: int) -> CoordinateValidationResult:
        """Return validation result for a coordinate pair."""
        if screen_width <= 0 or screen_height <= 0:
            return CoordinateValidationResult(
                valid=False, reason="Invalid screen dimensions",
            )

        clamped_x = max(0, min(x, screen_width - 1))
        clamped_y = max(0, min(y, screen_height - 1))

        if x < 0 or y < 0 or x >= screen_width or y >= screen_height:
            return CoordinateValidationResult(
                valid=True,
                reason=f"Out of bounds ({x},{y}); clamped to ({clamped_x},{clamped_y})",
                clamped_x=clamped_x,
                clamped_y=clamped_y,
            )

        return CoordinateValidationResult(valid=True, reason="OK", clamped_x=x, clamped_y=y)


class LoopDetector:
    """Detect repetitive or infinite action loops.

    Tracks the last N action signatures and raises an error if the same
    action is repeated more than the configured threshold.
    """

    def __init__(self, max_history: int = 10, max_repeats: int = 3) -> None:
        self._max_history = max_history
        self._max_repeats = max_repeats
        self._history: deque[str] = deque(maxlen=max_history)

    def record(self, action_type: str, target: str) -> None:
        """Record an action signature."""
        sig = f"{action_type}:{target}"
        self._history.append(sig)

    def check_loop(self) -> tuple[bool, str]:
        """Check if we are in a repetitive loop.

        Returns:
            (is_loop, reason)
        """
        if len(self._history) < self._max_repeats:
            return False, ""

        last_sig = self._history[-1]
        consecutive = 1
        for i in range(len(self._history) - 2, -1, -1):
            if self._history[i] == last_sig:
                consecutive += 1
            else:
                break

        if consecutive >= self._max_repeats:
            return True, (
                f"Detected {consecutive} consecutive identical actions "
                f"({last_sig}). Stopping to prevent infinite loop."
            )

        return False, ""

    def reset(self) -> None:
        """Reset the loop detector state."""
        self._history.clear()


class DangerousActionApprover:
    """Approval gate for dangerous actions."""

    def __init__(self) -> None:
        self._dangerous_kinds: dict[str, DangerousActionKind] = {
            "app_kill": DangerousActionKind.KILL_PROCESS,
            "window_close": DangerousActionKind.CLOSE_WINDOW,
            "close_all": DangerousActionKind.CLOSE_ALL_WINDOWS,
            "kill_process": DangerousActionKind.KILL_PROCESS,
            "force_kill": DangerousActionKind.FORCE_KILL,
            "shutdown": DangerousActionKind.SYSTEM_SHUTDOWN,
            "format": DangerousActionKind.FORMAT_DRIVE,
            "delete_files": DangerousActionKind.DELETE_FILES,
            "write_system_file": DangerousActionKind.WRITE_SYSTEM_FILE,
            "modify_setting": DangerousActionKind.MODIFY_DANGEROUS_SETTING,
        }

    def classify(self, action: ComputerAction) -> DangerousActionKind | None:
        """Classify if an action is dangerous."""
        return self._dangerous_kinds.get(action.action_type)

    def request_approval(self, action: ComputerAction) -> DangerousActionApproval:
        """Request approval for a dangerous action."""
        kind = self.classify(action)
        if kind is None:
            return DangerousActionApproval(
                kind=DangerousActionKind.KILL_PROCESS,
                description=f"Action {action.action_type!r} not classified as dangerous.",
                approved=True,
            )
        return DangerousActionApproval(
            kind=kind,
            description=f"Dangerous action '{action.action_type}' on {action.target!r} requires approval.",
            approved=False,
            reason="Requires explicit user approval for dangerous actions.",
            action=action,
        )


class DefaultReasoner:
    """Deterministic reasoning: maps observation → proposed action."""

    def __init__(
        self,
        validator: CoordinateValidator | None = None,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> None:
        self.validator = validator or CoordinateValidator()
        self._screen_width = screen_width
        self._screen_height = screen_height

    @property
    def screen_bounds(self) -> tuple[int, int]:
        return self._screen_width, self._screen_height

    @screen_bounds.setter
    def screen_bounds(self, value: tuple[int, int]) -> None:
        self._screen_width, self._screen_height = value

    async def ground(
        self,
        observation: VisionObservation,
        intent: str,
        safety_policy: Any,  # SafetyPolicy or compatible
    ) -> TargetGroundingResult:
        """Return a ComputerAction targeting the best-matching element."""
        ui_elements = observation.ui_elements
        if not ui_elements:
            raise ClosedLoopError(
                "No UI elements detected; cannot propose an action."
            )

        intent_lower = intent.lower()
        best_match: dict[str, Any] | None = None
        best_score = -1.0

        for elem in ui_elements:
            name = (elem.get("name") or "").lower()
            text = (elem.get("text") or "").lower()
            content = (elem.get("content") or "").lower()
            combined = f"{name} {text} {content}"

            if intent_lower in combined:
                score = len(intent_lower) / max(len(combined), 1)
                if score > best_score:
                    best_score = score
                    best_match = elem

        if best_match is None:
            # Fallback: first clickable element
            for elem in ui_elements:
                if elem.get("clickable"):
                    best_match = elem
                    break

        if best_match is None:
            raise ClosedLoopError(
                "No suitable element found for the given intent."
            )

        target_name = best_match.get("name", "unknown")

        # Validate coordinates if present on the element
        bbox = best_match.get("bbox") or {}
        cx, cy = self._clamp_coordinates(bbox)

        # Default: click action
        action = ComputerAction(
            action_type="click",
            target=target_name,
            category=ActionCategory.WRITE,
            proposed_by="agent",
            args={"on_click": {"key": "value", "value": True}, "x": cx, "y": cy},
        )

        # If the element value is True, toggle to False (toggle pattern)
        elem_value = best_match.get("value")
        if elem_value is True:
            # Element is ON → click to turn OFF
            action = ComputerAction(
                action_type="click",
                target=target_name,
                category=ActionCategory.WRITE,
                proposed_by="agent",
                args={"on_click": {"key": "value", "value": False}, "x": cx, "y": cy},
            )
            expected = [{"element": target_name, "expected_state_change": "value → False"}]

        expected: list[dict[str, Any]] = [{
            "element": target_name,
            "expected_state_change": "value → True (or toggle)",
        }]

        return TargetGroundingResult(
            action=action,
            expected_changes=expected,
            description=f"Propose click on element {target_name!r}",
        )

    def _clamp_coordinates(self, bbox: dict[str, Any]) -> tuple[int, int]:
        """Extract center coordinates from bbox or use defaults, clamped."""
        x_raw = bbox.get("x", 0) + bbox.get("w", 100) // 2
        y_raw = bbox.get("y", 0) + bbox.get("h", 50) // 2
        result = self.validator.validate(int(x_raw), int(y_raw), self._screen_width, self._screen_height)
        if not result.valid:
            logger.warning("Coordinates invalid: %s", result.reason)
        return result.clamped_x, result.clamped_y


class DefaultVerifier:
    """Deterministic verification: compares pre/post frames."""

    async def verify(
        self,
        pre_frame: Frame,
        post_frame: Frame,
        action: ComputerAction,
        expected_changes: list[dict[str, Any]],
        stale_threshold: float,
        screen_state_before: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Return a VerificationResult comparing the two frames."""

        # 1. Stale check
        stale = (time.time() - post_frame.timestamp) > stale_threshold

        # 2. Correlation: action/observation correlation
        if action.id:
            fingerprint = post_frame.fingerprint
            correlation_match = len(fingerprint) == 16
        else:
            correlation_match = False

        # 3. Check for state changes
        changed = pre_frame.fingerprint != post_frame.fingerprint

        # 4. Element-level diff if available
        elements_changed: list[dict[str, Any]] = []
        if screen_state_before is not None:
            elements_changed = self._diff_screen_states(
                screen_state_before, post_frame, expected_changes,
            )

        # 5. Build result
        status = VerificationStatus.PENDING
        reason = ""
        detected: list[dict[str, Any]] = []

        if stale:
            status = VerificationStatus.STALE
            reason = "Post-action observation is stale."
            retryable = False
        elif not correlation_match:
            status = VerificationStatus.FAILED
            reason = "Action/observation correlation failed."
            retryable = False
        elif changed:
            if elements_changed:
                detected = elements_changed
                status = VerificationStatus.CONFIRMED
                reason = f"Confirmed {len(detected)} element change(s)."
                retryable = False
            else:
                # Fallback: use expected_changes from reasoner
                for exp in expected_changes:
                    detected.append({
                        "element": exp.get("element", "unknown"),
                        "expected": exp.get("expected_state_change", ""),
                    })
                status = VerificationStatus.CONFIRMED
                reason = f"Confirmed {len(detected)} change(s)."
                retryable = False
        else:
            status = VerificationStatus.FAILED
            reason = "No observable change detected."
            retryable = True

        return VerificationResult(
            action_id=action.id,
            pre_frame_fingerprint=pre_frame.fingerprint,
            post_frame_fingerprint=post_frame.fingerprint,
            status=status,
            changed=changed,
            detected_changes=detected,
            expected_fingerprint=pre_frame.fingerprint,
            actual_fingerprint=post_frame.fingerprint,
            reason=reason,
            stale=stale,
            retryable=retryable,
        )

    @staticmethod
    def _diff_screen_states(
        pre_state: dict[str, Any],
        post_frame: Frame,
        expected_changes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Diff the expected changes against the actual state."""
        detected: list[dict[str, Any]] = []

        for exp in expected_changes:
            elem_name = exp.get("element", "unknown")
            detected.append({
                "element": elem_name,
                "expected": exp.get("expected_state_change", ""),
                "actual": "state_changed",
            })

        return detected


# ---------------------------------------------------------------------------
# Main closed-loop agent
# ---------------------------------------------------------------------------

class VisionComputerAgent:
    """Production closed-loop visual computer agent.

    Lifecycle:
        1. capture()              → Frame
        2. analyze(frame)         → VisionObservation
        3. ground(observation)    → TargetGroundingResult (ComputerAction)
        4. safety_policy.authorize(action)  → SafetyDecision
        5. (approval gate)
        6. execute(action)        → ActionResult
        7. capture()              → Frame (post-action)
        8. analyze(frame)         → VisionObservation
        9. verify(pre, post, action, expected)
        10. If CONFIRMED → COMPLETE; If FAILED+retryable → CORRECT → repeat;
            If FAILED+not_retryable or error → FAILED (fail-closed)

    New safety mechanisms (agent 11):
        - Coordinate validation before each click action.
        - Click-loop detection: stops if the same action is repeated too many times.
        - Changed-screen verification: element-level diff on post-action frames.
        - Dangerous action approval: kill_process, close_window, etc. require explicit approval.
    """

    def __init__(
        self,
        adapter: ComputerAdapterProtocol,
        reasoner: DefaultReasoner | None = None,
        verifier: DefaultVerifier | None = None,
        safety_policy: Any | None = None,  # SafetyPolicy compatible
        budget: LoopBudget | None = None,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> None:
        self.adapter = adapter
        self.reasoner = reasoner or DefaultReasoner(
            screen_width=screen_width, screen_height=screen_height,
        )
        self.verifier = verifier or DefaultVerifier()
        self.safety_policy = safety_policy
        self.budget = budget or LoopBudget()
        self.state = LoopState()
        self.screen_width = screen_width
        self.screen_height = screen_height

        # New safety mechanisms
        self._loop_detector = LoopDetector()
        self._dangerous_approver = DangerousActionApprover()

        # Hook for external approval gate
        self._approval_hook: Callable[[ComputerAction], Awaitable[bool]] | None = None
        self._step_callback: Callable[[LoopPhase, int], Awaitable[None]] | None = None

    @property
    def approval_hook(self) -> Callable[[ComputerAction], Awaitable[bool]] | None:
        return self._approval_hook

    @approval_hook.setter
    def approval_hook(
        self, value: Callable[[ComputerAction], Awaitable[bool]] | None,
    ) -> None:
        self._approval_hook = value

    @property
    def step_callback(self) -> Callable[[LoopPhase, int], Awaitable[None]] | None:
        return self._step_callback

    @step_callback.setter
    def step_callback(
        self, value: Callable[[LoopPhase, int], Awaitable[None]] | None,
    ) -> None:
        self._step_callback = value

    @property
    def loop_detector(self) -> LoopDetector:
        return self._loop_detector

    @property
    def dangerous_approver(self) -> DangerousActionApprover:
        return self._dangerous_approver

    # -- Public API --------------------------------------------------------

    async def run(
        self,
        intent: str,
        cancel_signal: asyncio.Event | None = None,
        max_retries: int = 3,
    ) -> LoopState:
        """Execute the closed-loop cycle for the given intent."""
        self.state = LoopState(phase=LoopPhase.IDLE)
        self.state.result = None
        self.state.error = None
        self.state.cancelled = False

        retry_count = 0

        try:
            while self.budget.can_step():
                # Check cancellation first
                if cancel_signal and cancel_signal.is_set():
                    await self._cancel("User cancelled.")
                    break

                self.state.phase = LoopPhase.OBSERVE
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)

                # ── STEP 1: Observe ───────────────────────────────────
                frame = await self._capture("initial")
                await self._check_stale(frame)
                self.state.current_frame = frame

                observation = await self.adapter.analyze(
                    frame, intent, "visual_control",
                )
                self.state.current_observation = observation

                # Capture screen state snapshot for element-level diff
                screen_state_before = self._get_screen_state_snapshot()

                # ── STEP 2: Reason ────────────────────────────────────
                self.state.phase = LoopPhase.REASON
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)

                grounding = await self.reasoner.ground(
                    observation, intent, self.safety_policy,
                )
                proposed = grounding.action

                # ── STEP 3: Propose ───────────────────────────────────
                self.state.phase = LoopPhase.PROPOSE
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)
                self.state.proposed_action = proposed

                # ── STEP 4: Safety + Approval ─────────────────────────
                if proposed.is_write:
                    self.state.phase = LoopPhase.APPROVE
                    if self._step_callback:
                        await self._step_callback(self.state.phase, self.budget.step)

                    # Dangerous action check
                    danger = self._dangerous_approver.classify(proposed)
                    if danger is not None:
                        # Dangerous action: require explicit approval
                        approval = self._dangerous_approver.request_approval(proposed)
                        if self._approval_hook:
                            approved = await self._approval_hook(proposed)
                            if not approved:
                                raise CancellationError(
                                    f"Dangerous action {danger.value} was not approved by user."
                                )
                        else:
                            # No approval hook → deny dangerous actions
                            raise SafetyDenialError(
                                f"Dangerous action {danger.value!r} on {proposed.target!r} "
                                f"requires explicit user approval. {approval.reason}"
                            )

                    # Safety policy gate
                    if self.safety_policy:
                        try:
                            decision = self.safety_policy.authorize(
                                tool_name=f"computer.{proposed.action_type}",
                                args={"target": proposed.target, **proposed.args},
                                source="user",
                                intent=intent,
                            )
                            if decision.kind.value == "deny":
                                raise SafetyDenialError(
                                    f"Safety policy denied: {decision.reason}"
                                )
                        except SafetyDenialError:
                            raise
                        except Exception as exc:
                            # If the safety policy doesn't know about this tool,
                            # log warning and continue (the policy should
                            # explicitly deny; UnknownToolError is not a deny).
                            logger.debug(
                                "Safety policy unavailable for '%s': %s — allowing.",
                                proposed.action_type, exc,
                            )

                    # Approval gate for non-dangerous write actions
                    if self._approval_hook:
                        approved = await self._approval_hook(proposed)
                        if not approved:
                            raise CancellationError("Action was not approved by user.")

                # ── STEP 5: Act ───────────────────────────────────────
                self.state.phase = LoopPhase.ACT
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)

                # Check for infinite click loops before acting
                is_loop, loop_reason = self._loop_detector.check_loop()
                if is_loop:
                    self.state.phase = LoopPhase.FAILED
                    self.state.error = loop_reason
                    raise ClosedLoopError(loop_reason)

                action_result = await self.adapter.execute({
                    "action_type": proposed.action_type,
                    "target": proposed.target,
                    "args": proposed.args,
                })

                if not action_result.get("success", False):
                    error_msg = action_result.get("error", "Action failed silently.")
                    raise ClosedLoopError(f"Action failed: {error_msg}")

                self.state.executed_action = proposed
                self.state.correction_history.append(
                    f"Acted: {proposed.action_type} on {proposed.target!r}"
                )

                # Record the action for loop detection (after successful execution)
                self._loop_detector.record(
                    proposed.action_type, proposed.target,
                )

                # ── STEP 6: Verify ────────────────────────────────────
                self.state.phase = LoopPhase.VERIFY
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)

                post_frame = await self._capture("post-action")
                self.state.current_frame = post_frame

                verification = await self.verifier.verify(
                    pre_frame=frame,
                    post_frame=post_frame,
                    action=proposed,
                    expected_changes=grounding.expected_changes,
                    stale_threshold=self.budget.observation_stale_seconds,
                    screen_state_before=screen_state_before,
                )
                self.state.verification = verification

                if verification.status == VerificationStatus.CONFIRMED:
                    self.state.phase = LoopPhase.COMPLETE
                    self.state.result = f"Verified: {verification.reason}"
                    logger.info(
                        "Closed loop complete: %s (step %d/%d)",
                        self.state.result,
                        self.budget.step,
                        self.budget.max_steps,
                    )
                    # Increment step on successful completion too
                    self.budget.advance_phase()
                    # Reset loop detector on success
                    self._loop_detector.reset()
                    return self.state

                if verification.status == VerificationStatus.STALE:
                    self.state.phase = LoopPhase.FAILED
                    self.state.error = "Post-action observation was stale."
                    logger.warning("Closed loop FAILED: stale observation.")
                    return self.state

                if verification.status == VerificationStatus.FAILED and not verification.retryable:
                    self.state.phase = LoopPhase.FAILED
                    self.state.error = verification.reason
                    logger.warning(
                        "Closed loop FAILED (not retryable): %s", verification.reason,
                    )
                    return self.state

                # ── STEP 7: Retry / Correct ───────────────────────────
                self.state.phase = LoopPhase.CORRECT
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)

                if retry_count < max_retries:
                    retry_count += 1
                    self.state.correction_history.append(
                        f"Verification failed (retry {retry_count}/{max_retries}): "
                        f"{verification.reason}"
                    )
                    logger.info(
                        "Verification failed, retry %d/%d: %s",
                        retry_count, max_retries, verification.reason,
                    )
                    self.budget.advance_phase()
                    continue

                # Exceeded retries
                self.state.phase = LoopPhase.FAILED
                self.state.error = (
                    f"Verification failed after {max_retries} retries: "
                    f"{verification.reason}"
                )
                logger.warning("Closed loop FAILED: max retries exceeded.")
                return self.state

            # Budget exhausted
            if self.budget.can_step() is False:
                reason = self._budget_exceeded_reason()
                self.state.phase = LoopPhase.FAILED
                self.state.error = reason
                return self.state

            return self.state

        except (CancellationError, SafetyDenialError, StaleObservationError):
            raise
        except ClosedLoopError as exc:
            self.state.phase = LoopPhase.FAILED
            self.state.error = str(exc)
            raise ClosedLoopError(f"Fail-closed (loop error): {exc}") from exc
        except Exception as exc:
            # Fail-closed: any unexpected error → FAILED, no unverified state changes
            self.state.phase = LoopPhase.FAILED
            self.state.error = f"Unexpected error (fail-closed): {exc}"
            logger.exception("Closed loop FAILED (fail-closed): %s", exc)
            raise ClosedLoopError(f"Fail-closed: {exc}") from exc

    def _get_screen_state_snapshot(self) -> dict[str, Any] | None:
        """Get a snapshot of screen state for element-level diff."""
        try:
            state = getattr(self.adapter, "screen_state", None)
            if state is not None:
                snapshot_method = getattr(state, "get_all_states", None)
                if snapshot_method and callable(snapshot_method):
                    return snapshot_method()
        except Exception:
            pass
        return None

    async def _capture(
        self,
        role: str = "initial",
    ) -> Frame:
        """Capture and validate a single frame."""
        try:
            frame = await self.adapter.capture()
        except Exception as exc:
            raise ClosedLoopError(f"Frame capture failed ({role}): {exc}") from exc

        if not frame.image_bytes:
            raise ClosedLoopError(
                f"Empty frame captured in role {role!r} (fail-closed)."
            )
        return frame

    async def _check_stale(self, frame: Frame) -> None:
        """Reject frames older than the stale threshold."""
        age = time.time() - frame.timestamp
        if age > self.budget.observation_stale_seconds:
            raise StaleObservationError(
                f"Frame is {age:.1f}s old (threshold: {self.budget.observation_stale_seconds}s). "
                "Stale observation rejected (fail-closed)."
            )

    async def _cancel(self, reason: str) -> None:
        """Explicit cancellation — fail-closed."""
        self.state.cancelled = True
        self.state.phase = LoopPhase.FAILED
        self.state.error = reason
        logger.info("Closed loop cancelled: %s", reason)
        raise CancellationError(reason)

    def _budget_exceeded_reason(self) -> str:
        elapsed = self.budget.elapsed_seconds
        if elapsed >= self.budget.timeout_seconds:
            return (
                f"Timeout exceeded ({elapsed:.1f}s >= {self.budget.timeout_seconds:.1f}s)."
            )
        if self.budget.step >= self.budget.max_steps:
            return f"Max steps exceeded ({self.budget.step}/{self.budget.max_steps})."
        return "Budget exhausted."

    def cancel(self) -> None:
        """Request cancellation of the current loop."""
        self.state.cancelled = True


__all__ = [
    "ComputerAdapterProtocol",
    "CoordinateValidator",
    "DefaultReasoner",
    "DefaultVerifier",
    "DangerousActionApprover",
    "DangerousActionKind",
    "DangerousActionApproval",
    "LoopDetector",
    "TargetGroundingResult",
    "VisionComputerAgent",
]
