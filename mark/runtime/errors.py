"""Structured local-runtime error codes and Russian messages.

Messages live in this package so the manager does not edit i18n catalogs.
They must never include API keys, tokens, or other secrets.
"""

from __future__ import annotations

CODE_OK = "ok"
CODE_OOM = "oom"
CODE_NOT_RUNNING = "not_running"
CODE_START_FAILED = "start_failed"
CODE_STOP_FAILED = "stop_failed"
CODE_REMOTE_URL = "remote_url"
CODE_PULL_UNCONFIRMED = "pull_unconfirmed"

ERROR_CODES = frozenset(
    {
        CODE_OK,
        CODE_OOM,
        CODE_NOT_RUNNING,
        CODE_START_FAILED,
        CODE_STOP_FAILED,
        CODE_REMOTE_URL,
        CODE_PULL_UNCONFIRMED,
    }
)

_MESSAGES_RU: dict[str, str] = {
    CODE_OK: "Локальный runtime работает.",
    CODE_OOM: "Недостаточно памяти для запуска локальной модели.",
    CODE_NOT_RUNNING: "Локальный runtime не запущен.",
    CODE_START_FAILED: "Не удалось запустить локальный runtime.",
    CODE_STOP_FAILED: "Не удалось остановить локальный runtime.",
    CODE_REMOTE_URL: "Удалённый адрес runtime запрещён. Разрешены только локальные адреса.",
    CODE_PULL_UNCONFIRMED: "Загрузка модели требует подтверждения размера и лицензии.",
}

_UNKNOWN_RU = "Ошибка локального runtime."


def runtime_message_ru(code: str) -> str:
    """Return the Russian explanation for a structured runtime error code."""
    return _MESSAGES_RU.get(code, _UNKNOWN_RU)


class RuntimeManagerError(Exception):
    """Caller or configuration error. Process failures use ``RuntimeStatus``."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message if message is not None else runtime_message_ru(code))


__all__ = [
    "CODE_NOT_RUNNING",
    "CODE_OK",
    "CODE_OOM",
    "CODE_PULL_UNCONFIRMED",
    "CODE_REMOTE_URL",
    "CODE_START_FAILED",
    "CODE_STOP_FAILED",
    "ERROR_CODES",
    "RuntimeManagerError",
    "runtime_message_ru",
]
