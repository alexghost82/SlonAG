"""Russian-language messages for the self-improvement pipeline.

All user-facing messages, errors, and status updates use these strings.
"""

from __future__ import annotations

# ── Status messages ───────────────────────────────────────────

RU_OBSERVATION_REGISTERED = "Наблюдение зарегистрировано"
RU_OBSERVATION_TOOL_FAILURE = "Ошибка инструмента: {tool} ({code})"
RU_OBSERVATION_TOOL_TIMEOUT = "Таймаут инструмента: {tool} ({seconds}s)"
RU_OBSERVATION_PROVIDER_SLOW = "Медленный провайдер: {provider} ({latency}ms)"
RU_OBSERVATION_PROVIDER_FAILED = "Ошибка провайдера: {provider}"
RU_OBSERVATION_PREFERENCE_CORRECTION = "Коррекция предпочтения: {type}"

# ── Candidate messages ───────────────────────────────────────

RU_CANDIDATE_GENERATED = "Сгенерирован кандидат на улучшение: {title}"
RU_CANDIDATE_RISK_SAFE = "Безопасное изменение"
RU_CANDIDATE_RISK_LOW = "Низкий риск"
RU_CANDIDATE_RISK_MEDIUM = "Средний риск"
RU_CANDIDATE_RISK_HIGH = "Высокий риск"

# ── Approval messages ────────────────────────────────────────

RU_APPROVE_SUCCESS = "Улучшение \"{title}\" одобрено пользователем"
RU_REJECT_SUCCESS = "Улучшение \"{title}\" отклонено"
RU_ALREADY_APPROVED = "Улучшение \"{title}\" уже одобрено"
RU_ALREADY_REJECTED = "Улучшение \"{title}\" уже отклонено"
RU_NOT_FOUND = "Улучшение \"{title}\" не найдено"
RU_USER_APPROVAL_REQUIRED = "Требуется одобрение пользователя: {title}"

# ── Evaluation messages ─────────────────────────────────────────

RU_EVALUATION_PASS = "Оценка пройдена (score={score}): {reason}"
RU_EVALUATION_FAIL = "Оценка не пройдена: {reason}"
RU_EVALUATION_SECURITY = "Недопустимое изменение безопасности отклонено"

# ── Apply messages ────────────────────────────────────────────

RU_APPLY_SUCCESS = "Изменение \"{title}\" применено успешно"
RU_APPLY_ERROR = "Ошибка применения: {error}"
RU_APPLY_NO_APPROVAL = "Невозможно применить: требуется одобрение пользователя"

# ── Monitor messages ──────────────────────────────────────────

RU_MONITOR_DEGRADATION = "Обнаружена деградация после применения: {title}"
RU_MONITOR_STABLE = "Наблюдение подтверждено: {title} — без деградации"

# ── Rollback messages ─────────────────────────────────────────

RU_ROLLBACK_SUCCESS = "Откат \"{title}\" выполнен: {reason}"
RU_ROLLBACK_FAILED = "Откат \"{title}\" не выполнен: {reason}"

# ── General messages ──────────────────────────────────────────

RU_NO_CANDIDATES = "Кандидаты не сгенерированы (нужно больше наблюдений)"
RU_STATE_SUMMARY = "Итоговое состояние системы:"
RU_AUDIT_HISTORY_EMPTY = "Аудит пуст"

# ── Error messages ────────────────────────────────────────────

RU_ERROR_SECURITY_VIOLATION = "Запрещённое изменение: усиление безопасности недопустимо"
RU_ERROR_INVALID_STATE_TRANSITION = "Недопустимый переход состояния"
RU_ERROR_MISSING_AUDIT = "Отсутствует запись в журнале аудита"


def ru_f(template: str, **kwargs: object) -> str:
    """Format a Russian message template."""
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, TypeError):
        return template
