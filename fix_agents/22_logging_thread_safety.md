# Агент 22 — Logging + Thread Safety

# Общие правила

Ты работаешь в отдельном `git worktree` и отдельной ветке от одного общего base SHA ветки `integration/main`.

Обязательные правила:

1. Запиши исходный base SHA в финальный отчёт.
2. Не делай `push`.
3. Не делай `merge`.
4. Не делай `rebase`.
5. Не меняй `remote`.
6. Не используй `git reset --hard`.
7. Не используй `git clean`.
8. Не удаляй чужой код.
9. Не выходи за указанную зону владения без крайней необходимости.
10. Если полноценная интеграция требует изменения файла, принадлежащего другому агенту, не меняй его. Реализуй свой production API и оставь точную integration instruction для финального интегратора.
11. Не создавай fake/stub/shim только ради прохождения тестов.
12. Не ослабляй security, approvals, permissions, privacy, authentication или network restrictions.
13. Пользовательские сообщения, ошибки и статусы должны поддерживать русский язык.
14. После работы запусти максимально полный релевантный набор тестов.
15. Сделай локальный commit с понятным сообщением.
16. Ничего не push.

Финальный отчёт должен содержать:

- branch;
- base SHA;
- commit SHA;
- изменённые файлы;
- что реализовано;
- какие тесты запускались;
- результаты тестов;
- известные ограничения;
- необходимые integration actions.


## Цель

Исправить logging и race conditions в mutable global state.

## Зона владения

- `main.py`
- `or_client.py`
- `actions/shell_exec.py`
- tests этих компонентов

Не менять provider architecture.

## Задачи

1. Убрать module-level `logging.basicConfig` из `or_client.py`.
2. Использовать `logging.getLogger(__name__)` или project logger.
3. Не конфигурировать global logging из library modules.
4. Заменить production `print()` на logging там, где print не является намеренным CLI output.
5. Не логировать secrets.
6. Проверить `_active_procs` на race conditions.
7. Сделать add/remove/iterate/cleanup thread-safe.
8. Проверить `_rate_limited` и другие mutable globals.
9. Использовать подходящий Lock/RLock.
10. Не держать lock во время долгого subprocess wait/network operation.
11. Добавить concurrency tests.

## Acceptance criteria

- Нет неконтролируемого global logging config.
- Mutable global state защищён от race conditions.
