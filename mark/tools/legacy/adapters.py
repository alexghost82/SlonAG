"""Thin adapters from canonical tool arguments to legacy Slon actions.

Imports deliberately happen at execution time.  Several legacy action modules
load optional desktop automation packages, and merely building a tool registry
must remain safe in headless/offline environments.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path
from typing import Any

from mark.tools.contracts import ToolResult
from mark.filesystem.operations import filesystem_operation, FileSystemResult


LegacyHandler = Callable[[Mapping[str, object]], ToolResult]


def with_legacy_speak(
    handler: Callable[[Mapping[str, object]], object],
    speak: Callable[..., object] | None,
) -> Callable[[Mapping[str, object]], object]:
    """Bind one compatibility callback without adding it to model arguments."""
    if speak is None or not getattr(handler, "_accepts_legacy_context", False):
        return handler

    def contextual_handler(args: Mapping[str, object]) -> object:
        return handler(args, _speak=speak)  # type: ignore[call-arg]

    return contextual_handler


def with_legacy_context(
    handler: Callable[[Mapping[str, object]], object],
    *,
    speak: Callable[..., object] | None = None,
    player: object | None = None,
) -> Callable[[Mapping[str, object]], object]:
    """Bind legacy UI callbacks at composition time, outside model arguments."""
    if not getattr(handler, "_accepts_legacy_context", False):
        return handler

    def contextual_handler(args: Mapping[str, object]) -> object:
        return handler(args, _speak=speak, _player=player)  # type: ignore[call-arg]

    return contextual_handler


def normalize_legacy_result(result: object) -> ToolResult:
    """Convert the result conventions used by ``actions/*`` to ``ToolResult``."""
    if isinstance(result, ToolResult):
        return result
    if result is None:
        return ToolResult(ok=True, code="legacy.ok")
    if isinstance(result, str):
        return ToolResult(ok=True, code="legacy.ok", message=result)
    if isinstance(result, dict):
        return ToolResult(ok=True, code="legacy.ok", data=result)
    if isinstance(result, bool):
        return ToolResult(
            ok=result,
            code="legacy.ok" if result else "legacy.failed",
            data=result,
        )
    # Preserve opaque legacy values as data. Adapters with a real failure
    # convention must translate it explicitly instead of claiming success.
    return ToolResult(ok=True, code="legacy.ok", data=result)


def _action_handler(
    module_name: str,
    function_name: str,
    *,
    accepts_speak: bool = False,
) -> LegacyHandler:
    def handler(
        args: Mapping[str, object], *, _speak: Callable[..., object] | None = None,
        _player: object | None = None,
    ) -> ToolResult:
        action = getattr(import_module(module_name), function_name)
        kwargs: dict[str, Any] = {"parameters": dict(args), "player": _player}
        if accepts_speak:
            kwargs["speak"] = _speak
        return normalize_legacy_result(action(**kwargs))

    handler.__name__ = f"{function_name}_handler"
    handler._accepts_legacy_context = True  # type: ignore[attr-defined]
    return handler


open_app_handler = _action_handler("actions.open_app", "open_app")
web_search_handler = _action_handler("actions.web_search", "web_search")
browser_control_handler = _action_handler("actions.browser_control", "browser_control")
file_controller_handler = _action_handler("actions.file_controller", "file_controller")
desktop_control_handler = _action_handler("actions.desktop", "desktop_control")
computer_control_handler = _action_handler(
    "actions.computer_control", "computer_control"
)
computer_settings_handler = _action_handler(
    "actions.computer_settings", "computer_settings"
)
screen_process_handler = _action_handler("actions.screen_processor", "screen_process")
reminder_handler = _action_handler("actions.reminder", "reminder")
weather_report_handler = _action_handler("actions.weather_report", "weather_action")
flight_finder_handler = _action_handler(
    "actions.flight_finder", "flight_finder", accepts_speak=True
)
youtube_video_handler = _action_handler(
    "actions.youtube_video", "youtube_video", accepts_speak=True
)
file_processor_handler = _action_handler(
    "actions.file_processor", "file_processor", accepts_speak=True
)
game_updater_handler = _action_handler(
    "actions.game_updater", "game_updater", accepts_speak=True
)
send_message_handler = _action_handler("actions.send_message", "send_message")
code_helper_handler = _action_handler(
    "actions.code_helper", "code_helper", accepts_speak=True
)
dev_agent_handler = _action_handler(
    "actions.dev_agent", "dev_agent", accepts_speak=True
)


def read_file_handler(args: Mapping[str, object]) -> ToolResult:
    """Canonical narrow read helper used by the iterative agent runtime.

    Delegated to the unified filesystem security layer.
    """
    result = filesystem_operation(
        "read",
        path=str(args.get("path", "")),
        max_chars=int(args.get("max_chars", 2097152)),
    )
    return ToolResult(
        ok=result.ok,
        code=result.code,
        message=result.message,
        data=result.data,
    )


def agent_task_handler(args: Mapping[str, object]) -> ToolResult:
    """Preserve the existing asynchronous task-queue bridge from ``main.py``."""
    task_queue = import_module("agent.task_queue")
    priority_value = args.get("priority", "normal")
    priority_name = (
        priority_value.lower() if isinstance(priority_value, str) else "normal"
    )
    priority_map = {
        "low": task_queue.TaskPriority.LOW,
        "normal": task_queue.TaskPriority.NORMAL,
        "high": task_queue.TaskPriority.HIGH,
    }
    task_id = task_queue.get_queue().submit(
        goal=str(args.get("goal", "")),
        priority=priority_map.get(priority_name, task_queue.TaskPriority.NORMAL),
        speak=None,
    )
    return normalize_legacy_result(f"Task started (ID: {task_id}).")



# Wave 22: shell_exec — bounded subprocess executor
shell_exec_handler = _action_handler("actions.shell_exec", "shell_exec")

# cmd_control is deprecated/broken; delegate to shell_exec for backward compat.
def _cmd_control_deprecated_handler(args: Mapping[str, object]) -> ToolResult:
    """Deprecated shim: route broken cmd_control to canonical shell_exec.

    Maps legacy argument names (``cmd`` → ``command``) so callers
    using the old tool name still work through the approved pipeline.
    """
    cmd = args.get("command", args.get("cmd", ""))
    if isinstance(cmd, str) and cmd.strip():
        kwargs: dict[str, object] = {"command": cmd}
        cwd = args.get("cwd")
        if cwd is not None:
            kwargs["cwd"] = cwd
        timeout = args.get("timeout")
        if timeout is not None:
            kwargs["timeout"] = timeout
        return shell_exec_handler(kwargs)
    # No command at all — shell_exec will produce the proper error.
    return shell_exec_handler({"command": ""})


# === Wave 24: Vision + STT + TTS tool handlers ===

def vision_analyze(args: Mapping[str, object]) -> ToolResult:
    """Analyze an image (base64-encoded) using the vision engine."""
    import base64

    image_b64 = args.get("image_base64", "")
    prompt = args.get("prompt", "")
    kind = args.get("kind", "describe")

    if not image_b64 or not isinstance(image_b64, str):
        return ToolResult(
            ok=False, code="missing_field",
            message="image_base64 is required and must be a string.",
        )
    if not prompt:
        return ToolResult(
            ok=False, code="missing_field",
            message="prompt is required and must be non-empty.",
        )

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        return ToolResult(
            ok=False, code="invalid_image",
            message="image_base64 is not valid base64.",
        )

    if len(image_bytes) == 0:
        return ToolResult(
            ok=False, code="missing_field",
            message="image_base64 decodes to empty data.",
        )

    try:
        from mark.vision.provider import LocalVisionProvider
        from mark.vision.engine import build_engine as build_vision_engine
        from providers.contracts import VisionRequest, ModelInfo
        from providers.errors import ProviderError

        try:
            engine = build_vision_engine()
        except Exception:
            return ToolResult(
                ok=False, code="vision_unavailable",
                message="Vision engine не доступен. Установите vision модель.",
            )

        repo_root = Path.cwd()
        temp_dir = str(repo_root / "tmp" / "vision-snapshots")
        (Path(temp_dir) / "vision-snapshots").mkdir(parents=True, exist_ok=True)

        provider = LocalVisionProvider(
            engine=engine,
            allow_cloud=False,
            temp_dir=temp_dir,
            privacy_profile="fully_local",
        )

        request = VisionRequest(
            model=ModelInfo(
                provider_id="vision_local",
                model_id="local-vision",
                display_name="Local Vision",
                text=True,
            ),
            image=image_bytes,
            prompt=prompt,
            kind=kind,
        )

        response = provider.analyze(request)
        from mark.vision.provider import VisionResponse
        if isinstance(response, VisionResponse):
            return ToolResult(
                ok=True, code="vision_ok",
                message=f"Vision analysis ({kind}): {response.text[:500]}",
            )
        return ToolResult(
            ok=False, code="vision_error",
            message=f"Vision analysis failed: {response}",
        )
    except ProviderError as exc:
        return ToolResult(
            ok=False, code="vision_error",
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False, code="vision_error",
            message=f"Vision tool error: {exc}",
        )


def stt_listen(args: Mapping[str, object]) -> ToolResult:
    """Transcribe audio (base64-encoded WAV) to text using local STT."""
    import base64

    audio_b64 = args.get("audio_base64", "")
    language = args.get("language", "ru")

    if not audio_b64 or not isinstance(audio_b64, str):
        return ToolResult(
            ok=False, code="missing_field",
            message="audio_base64 is required and must be a string.",
        )

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return ToolResult(
            ok=False, code="invalid_audio",
            message="audio_base64 is not valid base64.",
        )

    if len(audio_bytes) == 0:
        return ToolResult(
            ok=False, code="missing_field",
            message="audio_base64 decodes to empty data.",
        )

    try:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            wav_path = f.name

        try:
            result = subprocess.run(
                ["whisper", wav_path, "--model", "base", "--lang", language[:2] or "ru",
                 "--output_format", "txt"],
                capture_output=True, text=True, timeout=30.0,
            )
            if result.returncode == 0:
                text = result.stdout.strip()
                if text:
                    return ToolResult(ok=True, code="stt_ok", message=text[:1000])
        except FileNotFoundError:
            pass

        import wave
        try:
            with wave.open(wav_path, "rb") as wf:
                framerate = wf.getframerate()
                frames = wf.getnframes()
                duration = frames / framerate if framerate > 0 else 0
            if duration > 0.5:
                return ToolResult(
                    ok=True, code="stt_no_model",
                    message=f"Аудио обнаружено ({duration:.1f}с), но STT модель недоступна.",
                )
        except Exception:
            pass

        return ToolResult(
            ok=False, code="stt_no_model",
            message="STT модель недоступна. Установите whisper.",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False, code="stt_timeout",
            message="STT превысил лимит времени (30с).",
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False, code="stt_error",
            message=f"STT ошибка: {exc}",
        )
    finally:
        try:
            import os
            os.unlink(wav_path)
        except Exception:
            pass


def tts_speak(args: Mapping[str, object]) -> ToolResult:
    """Convert text to speech using local TTS."""
    text = args.get("text", "")
    voice = args.get("voice", "ru")

    if not text or not isinstance(text, str):
        return ToolResult(
            ok=False, code="missing_field",
            message="text is required and must be a non-empty string.",
        )

    try:
        import subprocess
        import tempfile

        repo_root = Path.cwd()

        # Try Piper TTS first
        piper_bin = repo_root / "models" / "tts" / "piper" / "piper"
        if piper_bin.exists():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name
            try:
                result = subprocess.run(
                    [str(piper_bin), "-f", wav_path],
                    input=text.encode(), capture_output=True, timeout=30.0,
                )
                if result.returncode == 0 and Path(wav_path).exists():
                    return ToolResult(
                        ok=True, code="tts_ok",
                        message=f"TTS генерация завершена ({Path(wav_path).stat().st_size} байт).",
                    )
            except FileNotFoundError:
                pass
            finally:
                try:
                    import os
                    os.unlink(wav_path)
                except Exception:
                    pass

        # Fallback: espeak
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name

            result = subprocess.run(
                ["espeak", "-w", wav_path, "-v", voice, text],
                capture_output=True, timeout=10.0,
            )
            if result.returncode == 0 and Path(wav_path).exists():
                return ToolResult(
                    ok=True, code="tts_ok",
                    message=f"TTS gen ok (espeak, {Path(wav_path).stat().st_size} bytes).",
                )
        except FileNotFoundError:
            pass

        return ToolResult(
            ok=False, code="tts_unavailable",
            message="TTS недоступна. Установите Piper или eSpeak.",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False, code="tts_timeout",
            message="TTS превысил лимит времени (30с).",
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            ok=False, code="tts_error",
            message=f"TTS ошибка: {exc}",
        )

LEGACY_HANDLERS: Mapping[str, LegacyHandler] = {
    "read_file": read_file_handler,
    "open_app": open_app_handler,
    "web_search": web_search_handler,
    "browser_control": browser_control_handler,
    "file_controller": file_controller_handler,
    "desktop_control": desktop_control_handler,
    "computer_control": computer_control_handler,
    "computer_settings": computer_settings_handler,
    "cmd_control": _cmd_control_deprecated_handler,
    "screen_process": screen_process_handler,
    "reminder": reminder_handler,
    "weather_report": weather_report_handler,
    "flight_finder": flight_finder_handler,
    "youtube_video": youtube_video_handler,
    "file_processor": file_processor_handler,
    "game_updater": game_updater_handler,
    "send_message": send_message_handler,
    "code_helper": code_helper_handler,
    "dev_agent": dev_agent_handler,
    "shell_exec": shell_exec_handler,  # Wave 22: canonical shell executor
    "agent_task": agent_task_handler,
    "vision_analyze": vision_analyze,
    "stt_listen": stt_listen,
    "tts_speak": tts_speak,
}


__all__ = [
    "LEGACY_HANDLERS",
    "LegacyHandler",
    "agent_task_handler",
    "normalize_legacy_result",
    "with_legacy_context",
    "with_legacy_speak",
]
