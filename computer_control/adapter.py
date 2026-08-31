"""Computer adapter — abstract interface between the loop and the
underlying screen/camera/RTSP subsystem.

Provides two concrete adapters:
  * VirtualScreenAdapter — deterministic state machine for E2E tests.
  * ScreenshotAdapter   — real OS screenshot capture (mss-based).

Enhancements by agent 11:
  * Coordinate clamping on click actions (screen bounds).
  * Dangerous action execution logging.
"""

from __future__ import annotations

import abc
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from computer_control.types import (
    ActionCategory,
    Frame,
    FrameSource,
    VisionObservation,
)


# ---------------------------------------------------------------------------
# Base adapter
# ---------------------------------------------------------------------------

class ComputerAdapter(abc.ABC):
    """Abstract adapter for screen/camera/RTSP capture and action execution."""

    @property
    @abc.abstractmethod
    def source(self) -> FrameSource:
        ...

    @abc.abstractmethod
    async def capture(self) -> Frame:
        """Capture a single frame and return it."""
        ...

    @abc.abstractmethod
    async def execute(self, action: Any) -> dict[str, Any]:
        """Execute a computer action. Returns result metadata."""
        ...

    @abc.abstractmethod
    async def analyze(self, frame: Frame, prompt: str, kind: str) -> VisionObservation:
        """Analyze a frame through the vision engine."""
        ...

    def is_virtual(self) -> bool:
        return self.source == FrameSource.VIRTUAL


# ---------------------------------------------------------------------------
# Deterministic virtual screen for E2E
# ---------------------------------------------------------------------------

@dataclass
class VirtualElement:
    """A deterministic UI element on the virtual screen."""

    name: str
    x: float  # normalized 0-1
    y: float  # normalized 0-1
    width: float = 0.1
    height: float = 0.05
    content: str = ""  # text label
    state: dict[str, Any] = field(default_factory=dict)
    clickable: bool = True


@dataclass
class VirtualScreenState:
    """Mutable state of the virtual screen."""

    elements: dict[str, VirtualElement] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    width: int = 800
    height: int = 600

    def add_element(self, elem: VirtualElement) -> None:
        self.elements[elem.name] = elem

    def set_state(self, name: str, key: str, value: Any) -> bool:
        if name in self.elements:
            self.elements[name].state[key] = value
            self.log.append(f"set {name}.{key} = {value}")
            return True
        return False

    def get_state(self, name: str, key: str, default: Any = None) -> Any:
        if name in self.elements:
            return self.elements[name].state.get(key, default)
        return default

    def get_all_states(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, elem in self.elements.items():
            result[name] = dict(elem.state)
            if elem.content:
                result[name]["content"] = elem.content
            result[name]["visible"] = elem.state.get("visible", True)
        return result

    def clear_log(self) -> list[str]:
        entries = list(self.log)
        self.log.clear()
        return entries


class DeterministicVisionEngine:
    """Deterministic vision engine that returns structured observations
    derived from the virtual screen state. No real AI model needed."""

    def analyze(
        self, frame: Frame, prompt: str, kind: str,
        screen_state: VirtualScreenState,
    ) -> VisionObservation:
        state = screen_state.get_all_states()
        detected: list[dict[str, Any]] = []
        ui_elements: list[dict[str, Any]] = []

        for name, elem in screen_state.elements.items():
            if not elem.state.get("visible", True):
                continue

            entry: dict[str, Any] = {
                "name": name,
                "type": "button" if elem.clickable else "text",
                "content": elem.content or "",
                "bbox": {
                    "x": int(elem.x * screen_state.width),
                    "y": int(elem.y * screen_state.height),
                    "w": int(elem.width * screen_state.width),
                    "h": int(elem.height * screen_state.height),
                },
                "state": dict(elem.state),
            }
            detected.append(entry)
            ui_elements.append({
                "name": name,
                "clickable": elem.clickable,
                "role": "button" if elem.clickable else "static",
                "text": elem.content,
                "content": elem.content,
                **entry["state"],
            })

        state_hash = hashlib.sha256(
            str(screen_state.get_all_states()).encode()
        ).hexdigest()[:32]
        fake_image = f"VIRTUAL_FRAME:{state_hash}:{frame.index}".encode()

        prompt_lower = prompt.lower()
        target_match = None
        for name in screen_state.elements:
            if name.lower() in prompt_lower:
                target_match = name
                break

        return VisionObservation(
            frame_fingerprint=frame.fingerprint,
            frame_index=frame.index,
            detected_objects=detected,
            ui_elements=ui_elements,
            ocr_text=" | ".join(
                f"{k}:{v.get('content','')}" for k, v in state.items()
            ),
            description=f"Virtual screen with {len(detected)} visible elements",
            confidence=1.0,
        )


class VirtualScreenAdapter(ComputerAdapter):
    """Deterministic virtual screen for E2E tests.

    The virtual screen holds a mutable state. Actions modify the state
    in a fully predictable way. The deterministic vision engine then
    "sees" the modified state and returns structured observations.

    Enhancements by agent 11:
      * Coordinate clamping on click actions.
      * Dangerous action logging.
    """

    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        vision_prompt_suffix: str = "",
        clamp_coordinates: bool = True,
    ) -> None:
        self._state = VirtualScreenState(width=width, height=height)
        self._state_index = 0
        self._width = width
        self._height = height
        self._vision_prompt_suffix = vision_prompt_suffix
        self._engine = DeterministicVisionEngine()
        self._frame_cache: dict[int, bytes] = {}
        self._clamp_coordinates = clamp_coordinates
        self._dangerous_log: list[dict[str, Any]] = []

    def set_element(
        self, name: str, x: float, y: float,
        content: str = "", clickable: bool = True,
        **kwargs: Any,
    ) -> VirtualElement:
        elem = VirtualElement(
            name=name, x=x, y=y, content=content,
            clickable=clickable, state=kwargs,
        )
        self._state.add_element(elem)
        return elem

    def set_elements(self, **kwargs: dict[str, dict[str, Any]]) -> list[VirtualElement]:
        results: list[VirtualElement] = []
        for name, props in kwargs.items():
            results.append(self.set_element(
                name=name,
                x=props.get("x", 0.5),
                y=props.get("y", 0.5),
                content=props.get("content", ""),
                clickable=props.get("clickable", True),
                **{k: v for k, v in props.items() if k not in ("x", "y", "content", "clickable")},
            ))
        return results

    @property
    def screen_state(self) -> VirtualScreenState:
        return self._state

    def get_state_snapshot(self) -> dict[str, Any]:
        return self._state.get_all_states()

    def get_log(self) -> list[str]:
        return list(self._state.log)

    @property
    def dangerous_log(self) -> list[dict[str, Any]]:
        """Log of dangerous actions attempted on this adapter."""
        return list(self._dangerous_log)

    def clear_dangerous_log(self) -> None:
        self._dangerous_log.clear()

    @property
    def source(self) -> FrameSource:
        return FrameSource.VIRTUAL

    async def capture(self) -> Frame:
        """Generate a deterministic frame from current screen state."""
        self._state_index += 1
        index = self._state_index

        if index in self._frame_cache:
            image_bytes = self._frame_cache[index]
        else:
            state_hash = hashlib.sha256(
                str(self._state.get_all_states()).encode()
            ).hexdigest()[:32]
            image_bytes = f"VIRTUAL_FRAME:{state_hash}:{index}".encode()
            self._frame_cache[index] = image_bytes

        return Frame(
            source=FrameSource.VIRTUAL,
            image_bytes=image_bytes,
            index=index,
            width=self._width,
            height=self._height,
        )

    async def execute(self, action: Any) -> dict[str, Any]:
        """Execute an action on the virtual screen.

        Enhancements by agent 11:
          * Coordinate clamping before click actions.
          * Dangerous action logging.
        """
        if isinstance(action, dict):
            action_type = action.get("action_type", "")
            target = action.get("target", "")
            args = action.get("args", {})
        else:
            action_type = getattr(action, "action_type", "")
            target = getattr(action, "target", "")
            args = getattr(action, "args", {})

        result: dict[str, Any] = {
            "action_type": action_type,
            "target": target,
            "success": False,
        }

        # ── Dangerous action logging ────────────────────────────────
        dangerous_kinds = {"app_kill", "close_window", "kill_process", "shutdown", "format"}
        if action_type in dangerous_kinds:
            self._dangerous_log.append({
                "action_type": action_type,
                "target": target,
                "timestamp": time.time(),
            })

        # ── Click actions with coordinate clamping ──────────────────
        if action_type == "click":
            result["success"] = self._do_click(target, args)
        elif action_type == "type":
            text = args.get("text", "")
            if target:
                self._state.set_state(target, "last_input", text)
            result["success"] = True
            self._state.log.append(f"type into {target}: {text!r}" if target else f"type: {text!r}")
        elif action_type == "set_state":
            elem_name = args.get("element", "")
            key = args.get("key", "")
            value = args.get("value")
            result["success"] = self._state.set_state(elem_name, key, value)
        elif action_type == "set_elements":
            all_ok = True
            for item in args.get("elements", []):
                name = item.get("name", "")
                self._state.set_state(name, item.get("key", "value"), item.get("value"))
            result["success"] = True
        elif action_type == "screenshot":
            frame = await self.capture()
            result["success"] = True
            result["fingerprint"] = frame.fingerprint
        else:
            result["success"] = False
            result["error"] = f"Unknown action type: {action_type}"

        return result

    def _do_click(self, target: str, args: dict[str, Any]) -> bool:
        """Handle a click on a named element."""
        if not target or target not in self._state.elements:
            return False

        elem = self._state.elements[target]
        if not elem.clickable:
            return False

        x = args.get("x", int(elem.x * self._width))
        y = args.get("y", int(elem.y * self._height))
        if self._clamp_coordinates:
            x = max(0, min(x, self._width - 1))
            y = max(0, min(y, self._height - 1))

        on_click = args.get("on_click")
        if on_click and isinstance(on_click, dict):
            key = on_click.get("key", "value")
            value = on_click.get("value")
            if value is not None:
                self._state.set_state(target, key, value)
            else:
                current = self._state.get_state(target, key, False)
                self._state.set_state(target, key, not current)

        self._state.log.append(f"click {target} at ({x},{y})")
        return True

    async def analyze(
        self, frame: Frame, prompt: str, kind: str,
    ) -> VisionObservation:
        """Return a deterministic observation from the virtual screen state."""
        full_prompt = f"{prompt} {self._vision_prompt_suffix}".strip()
        return self._engine.analyze(
            frame, full_prompt, kind, self._state,
        )


# ---------------------------------------------------------------------------
# Screenshot adapter (real OS)
# ---------------------------------------------------------------------------

class ScreenshotAdapter(ComputerAdapter):
    """Captures real OS screenshots using mss."""

    def __init__(self, monitor_index: int = 1) -> None:
        self._monitor_index = monitor_index
        self._mss = None
        self._try_import()

    def _try_import(self) -> None:
        try:
            import mss
            self._mss = mss
        except ImportError:
            self._mss = None

    @property
    def source(self) -> FrameSource:
        return FrameSource.SCREENSHOT

    async def capture(self) -> Frame:
        if self._mss is None:
            raise RuntimeError("mss not available")

        with self._mss.mss() as sct:
            shot = sct.grab(self._mss.monitors[self._monitor_index])
        import mss.tools
        image_bytes = mss.tools.to_png(shot.rgb, shot.size)

        return Frame(
            source=FrameSource.SCREENSHOT,
            image_bytes=image_bytes,
            width=shot.width,
            height=shot.height,
        )

    async def execute(self, action: Any) -> dict[str, Any]:
        raise NotImplementedError(
            "ScreenshotAdapter does not support actions."
        )

    async def analyze(
        self, frame: Frame, prompt: str, kind: str,
    ) -> VisionObservation:
        raise NotImplementedError(
            "ScreenshotAdapter does not include a vision engine."
        )


__all__ = [
    "ComputerAdapter",
    "DeterministicVisionEngine",
    "VirtualScreenAdapter",
    "VirtualScreenState",
    "VirtualElement",
    "ScreenshotAdapter",
]
