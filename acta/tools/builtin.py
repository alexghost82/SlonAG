"""Construction of the canonical registry for Slon's legacy built-in tools."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from acta.safety.registry import SafetyRule
from acta.safety.registry import tool_spec as safety_rule
from acta.tools.contracts import SideEffectClass, ToolSpec
from acta.tools.legacy import LEGACY_HANDLERS
from acta.tools.registry import ToolRegistry

_DESCRIPTIONS: Mapping[str, str] = {
    "read_file": "Прочитать текстовый файл в кодировке UTF-8.",
    "open_app": "Запустить установленное приложение.",
    "web_search": "Найти информацию в интернете.",
    "browser_control": "Управлять веб-браузером.",
    "file_controller": "Читать, создавать, организовывать или изменять файлы.",
    "desktop_control": "Просмотреть или управлять рабочим столом.",
    "computer_control": "Управлять доступными операциями компьютера.",
    "computer_settings": "Просмотреть или изменить настройки компьютера.",
    "shell_exec": "Выполнить ограниченную команду оболочки с согласованием.",
    "screen_process": "Обработать видимый текст на экране.",
    "reminder": "Просмотр, создание, обновление или отмена напоминаний.",
    "weather_report": "Получить прогноз погоды для города.",
    "flight_finder": "Найти рейсы по маршруту.",
    "youtube_video": "Найти или обработать видео YouTube.",
    "file_processor": "Обработать файл по заданному инструкту.",
    "game_updater": "Просмотреть, установить или обновить игры.",
    "send_message": "Отправить сообщение через платформу.",
    "code_helper": "Выполнить поддерживаемую операцию с кодом.",
    "dev_agent": "Запустить ограниченную задачу разработки.",
    "agent_task": "Отправить цель в очередь задач legacy-агента.",
    "vision_analyze": "Проанализировать изображение (base64) с помощью vision-движка.",
    "stt_listen": "Преобразовать аудио (WAV, base64) в текст с помощью локального STT.",
    "tts_speak": "Преобразовать текст в речь с помощью локального TTS.",
}

_JSON_TYPES: Mapping[str, str] = {
    "str": "string",
    "bool": "boolean",
    "int": "integer",
    "float": "number",
    "list": "array",
}


def _input_schema(rule: SafetyRule) -> dict[str, object]:
    """Translate the safety validator's argument knowledge to JSON Schema."""
    properties = {
        name: {"type": _JSON_TYPES[type_name]}
        for name, type_name in rule.schema.types
    }
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        # Safety validation intentionally permits additional legacy arguments.
        "additionalProperties": True,
    }
    if rule.schema.required:
        schema["required"] = list(rule.schema.required)
    return schema


def get_base_dir() -> Path:
    """Return the project base directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# Capability checkers — return True when the optional runtime is available.
def _check_vision() -> bool:
    """Return True when a vision engine is available."""
    try:
        from acta.vision.engine import build_engine as build_vision_engine
        build_vision_engine()
        return True
    except Exception:  # noqa: BLE001
        return False


def _check_stt() -> bool:
    """Return True when a local STT binary is available."""
    import subprocess
    try:
        # Check for whisper first
        if subprocess.run(["whisper", "--help"], capture_output=True, timeout=5).returncode in (0, 1):
            return True
        # Check for faster-whisper
        repo_root = Path.cwd()
        for candidate in [
            repo_root / "models" / "stt" / "faster-whisper" / "faster-whisper-quant",
            repo_root / "models" / "stt" / "faster-whisper" / "faster-whisper",
        ]:
            if candidate.exists():
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _check_tts() -> bool:
    """Return True when a local TTS binary is available."""
    repo_root = Path.cwd()
    # Check for Piper
    piper_bin = repo_root / "models" / "tts" / "piper" / "piper"
    if piper_bin.exists():
        return True
    # Check for espeak
    try:
        if subprocess.run(["espeak", "--version"], capture_output=True, timeout=5).returncode == 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


_TOOL_CAPABILITY_CHECK: dict[str, callable] = {
    "vision_analyze": _check_vision,
    "stt_listen": _check_stt,
    "tts_speak": _check_tts,
}

_CAPABILITY_MAP: dict[str, str] = {
    "vision_analyze": "vision",
    "stt_listen": "stt",
    "tts_speak": "tts",
}


def build_builtin_registry() -> ToolRegistry:
    """Build a fresh registry containing each migrated legacy tool once.

    Tools with optional runtime dependencies (vision, STT, TTS) are only
    registered when their backend is available.  This prevents false
    capabilities — tools that are advertised but always return ``unavailable``.
    """
    registry = ToolRegistry()

    # 1. Legacy tools
    for name, handler in LEGACY_HANDLERS.items():
        # Skip deprecated tools that have been removed from the catalog.
        if name == "cmd_control":
            continue

        # Gate optional-capability tools on runtime availability.
        checker = _TOOL_CAPABILITY_CHECK.get(name)
        if checker is not None and not checker():
            # Do NOT register — capability is absent at runtime.
            continue

        rule = safety_rule(name)
        capabilities = frozenset((_CAPABILITY_MAP[name],)) if name in _CAPABILITY_MAP else frozenset()
        registry.register(
            ToolSpec(
                name=name,
                description=_DESCRIPTIONS[name],
                input_schema=_input_schema(rule),
                output_schema=None,
                handler=handler,
                risk=rule.risk,
                read_only=rule.risk.value == 0,
                idempotent=rule.risk.value == 0,
                side_effects=rule.risk.value != 0,
                side_effect_class=(
                    SideEffectClass.NONE
                    if rule.risk.value == 0
                    else SideEffectClass.REVERSIBLE
                ),
                parallel_safe=rule.risk.value == 0,
                capabilities=capabilities,
            )
        )

    return registry

    # 2. Preference learning tools
    _register_preference_tools(registry, get_base_dir())

    return registry


def _register_preference_tools(registry: ToolRegistry, base_dir: Path) -> None:
    """Register the preference learning tools."""
    try:
        from acta.preference_learning.tools import build_preference_tools
        from acta.tools.contracts import SideEffectClass

        preference_specs = build_preference_tools(base_dir)
        for name, spec_pair in preference_specs.items():
            spec = spec_pair["spec"]
            handler = spec_pair["handler"]
            registry.register(
                ToolSpec(
                    name=spec["name"],
                    description=spec["description"],
                    input_schema=spec["input_schema"],
                    output_schema=None,
                    handler=handler,
                    risk=spec.get("risk", 1),
                    read_only=spec.get("read_only", False),
                    idempotent=spec.get("read_only", False),
                    side_effects=spec.get("risk", 1) > 0,
                    side_effect_class=(
                        SideEffectClass.REVERSIBLE
                        if spec.get("risk", 1) > 0
                        else SideEffectClass.NONE
                    ),
                    parallel_safe=False,
                )
            )
    except ImportError:
        # Preference learning module not available (e.g. during import-time checks)
        pass


__all__ = ["build_builtin_registry"]
