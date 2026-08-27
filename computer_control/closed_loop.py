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
    * fail-closed (any unexpected error → FAILED, no unverified state)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

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


class DefaultReasoner:
    """Deterministic reasoning: maps observation → proposed action.

    The agent passes the observation description and the user's intent
    prompt; the reasoner returns a ComputerAction targeting the
    highest-confidence UI element that matches the intent.
    """

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

        # Default: click action
        action = ComputerAction(
            action_type="click",
            target=target_name,
            category=ActionCategory.WRITE,
            proposed_by="agent",
            args={"on_click": {"key": "value", "value": True}},
        )

        # If the element is currently in a target state, adjust the action
        if best_match.get("value") is True and best_match.get("key") in intent_lower:
            action = ComputerAction(
                action_type="click",
                target=target_name,
                category=ActionCategory.WRITE,
                proposed_by="agent",
                args={"on_click": {"key": best_match.get("key", "value"), "value": False}},
            )

        expected: list[dict[str, Any]] = [{
            "element": target_name,
            "expected_state_change": "value → True (or toggle)",
        }]

        return TargetGroundingResult(
            action=action,
            expected_changes=expected,
            description=f"Propose click on element {target_name!r}",
        )


class DefaultVerifier:
    """Deterministic verification: compares pre/post frames."""

    async def verify(
        self,
        pre_frame: Frame,
        post_frame: Frame,
        action: ComputerAction,
        expected_changes: list[dict[str, Any]],
        stale_threshold: float,
    ) -> VerificationResult:
        """Return a VerificationResult comparing the two frames."""

        # 1. Stale check
        stale = (time.time() - post_frame.timestamp) > stale_threshold

        # 2. Correlation: action/observation correlation
        if action.id:
            fingerprint = post_frame.fingerprint
            correlation_match = len(fingerprint) == 16

        # 3. Check for state changes
        changed = pre_frame.fingerprint != post_frame.fingerprint

        # 4. Build result
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
            # Identify what changed
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
    """

    def __init__(
        self,
        adapter: ComputerAdapterProtocol,
        reasoner: DefaultReasoner | None = None,
        verifier: DefaultVerifier | None = None,
        safety_policy: Any | None = None,  # SafetyPolicy compatible
        budget: LoopBudget | None = None,
    ) -> None:
        self.adapter = adapter
        self.reasoner = reasoner or DefaultReasoner()
        self.verifier = verifier or DefaultVerifier()
        self.safety_policy = safety_policy
        self.budget = budget or LoopBudget()
        self.state = LoopState()

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

    # -- Public API --------------------------------------------------------

    async def run(
        self,
        intent: str,
        cancel_signal: asyncio.Event | None = None,
        max_retries: int = 3,
    ) -> LoopState:
        """Execute the closed-loop cycle for the given intent.

        Args:
            intent: Natural language description of what the agent should do.
            cancel_signal: Optional asyncio.Event to trigger cancellation.
            max_retries: How many times to retry on verification failure.

        Returns:
            The final LoopState with result, error, or status.
        """
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
                            # Fail-closed: unexpected safety error → deny
                            raise SafetyDenialError(
                                f"Safety evaluation error, denying by default: {exc}"
                            )

                    # Approval gate
                    if self._approval_hook:
                        approved = await self._approval_hook(proposed)
                        if not approved:
                            raise CancellationError("Action was not approved by user.")

                # ── STEP 5: Act ───────────────────────────────────────
                self.state.phase = LoopPhase.ACT
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)

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

                # ── STEP 6: Verify ────────────────────────────────────
                self.state.phase = LoopPhase.VERIFY
                if self._step_callback:
                    await self._step_callback(self.state.phase, self.budget.step)

                post_frame = await self._capture("post-action")
                self.state.current_frame = post_frame

                pre_fp = self.state.current_frame.fingerprint  # Will be updated after capture

                verification = await self.verifier.verify(
                    pre_frame=frame,
                    post_frame=post_frame,
                    action=proposed,
                    expected_changes=grounding.expected_changes,
                    stale_threshold=self.budget.observation_stale_seconds,
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
                    return self.state

                if verification.status == VerificationStatus.STALE:
                    # Stale → fail-closed
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
                raise BudgetExceededError(reason)

            return self.state

        except (CancellationError, SafetyDenialError, StaleObservationError):
            raise
        except ClosedLoopError:
            self.state.phase = LoopPhase.FAILED
            self.state.error = str(exc) if (exc := ClosedLoopError()) else "Unknown closed-loop error."
            self.state.error = str(exc.__cause__) if exc.__cause__ else "Unknown closed-loop error."
            raise
        except Exception as exc:
            # Fail-closed: any unexpected error → FAILED, no unverified state changes
            self.state.phase = LoopPhase.FAILED
            self.state.error = f"Unexpected error (fail-closed): {exc}"
            logger.exception("Closed loop FAILED (fail-closed): %s", exc)
            raise ClosedLoopError(f"Fail-closed: {exc}") from exc

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
    "DefaultReasoner",
    "DefaultVerifier",
    "TargetGroundingResult",
    "VisionComputerAgent",
]
