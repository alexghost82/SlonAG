# Агент 04 — Semantic Memory Core

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

Исправить MemoryStore и memory contracts.

## Зона владения

Разрешено:

- `mark/memory/**`
- memory-specific tests

Не менять:

- `agent/runtime.py`
- `mark/bridge/**`
- preference learning

## Задачи

1. Исправить `Proposal(frozen=True)` mutation defect.
2. Не присваивать поля frozen dataclass напрямую.
3. Использовать immutable replacement semantics либо осознанно изменить mutability.
4. Проверить dedup для pending, persisted, workspace, user и session.
5. Проверить confidence.
6. Проверить semantic retrieval.
7. Ограничить retrieval context.
8. Не сохранять secrets.
9. Поддержать inspect/delete/clear/disable/enable/export.
10. Persistence failure не должна повреждать DB.
11. Добавить migration/recovery tests.

## Acceptance criteria

- Duplicate path не вызывает `FrozenInstanceError`.
- Retrieval bounded.
- Memory DB остаётся консистентной после ошибок.
