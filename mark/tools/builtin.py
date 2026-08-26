"""Construction of the canonical registry for Slon's legacy built-in tools."""

from __future__ import annotations

from collections.abc import Mapping

from mark.safety.registry import SafetyRule, tool_spec as safety_rule
from mark.tools.contracts import SideEffectClass, ToolSpec
from mark.tools.legacy import LEGACY_HANDLERS
from mark.tools.registry import ToolRegistry


_DESCRIPTIONS: Mapping[str, str] = {
    "read_file": "Прочитать текстовый файл в кодировке UTF-8.",
    "open_app": "Запустить установленное приложение.",
    "web_search": "Найти информацию в интернете.",
    "browser_control": "Управлять веб-браузером.",
    "file_controller": "Читать, создавать, организовывать или изменять файлы.",
    "desktop_control": "Просмотреть или управлять рабочим столом.",
    "computer_control": "Управлять доступными операциями компьютера.",
    "computer_settings": "Просмотреть или изменить настройки компьютера.",
    "cmd_control": "Выполнить локальную команду (устаревший).",
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


def build_builtin_registry() -> ToolRegistry:
    """Build a fresh registry containing each migrated legacy tool once."""
    registry = ToolRegistry()
    for name, handler in LEGACY_HANDLERS.items():
        rule = safety_rule(name)
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
            )
        )
    return registry


__all__ = ["build_builtin_registry"]
