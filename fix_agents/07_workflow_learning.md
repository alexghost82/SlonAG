# Агент 07 — Workflow Learning

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

Проверить и закончить `mark/workflow_learning`.

## Зона владения

Только:

- `mark/workflow_learning/**`
- tests

## Требуемый pipeline

observation
→ normalization
→ repeated-pattern detection
→ candidate
→ confidence/evidence
→ approval
→ parameterization
→ execution
→ outcome
→ update/deprecate

## Задачи

1. Корректные state transitions.
2. Логичные terminal states.
3. Workflow нельзя выполнять без необходимых permissions.
4. Никакого silent self-activation опасных workflows.
5. Idempotency.
6. Rollback/deactivate.
7. Bounded history.
8. Persistence/restart.
9. Tests реального executor path.

## Acceptance criteria

- Lifecycle полностью проверен.
- Опасный workflow не запускается без разрешения.
