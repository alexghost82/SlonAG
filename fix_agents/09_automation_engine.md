# Агент 09 — Automation Engine

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

Проверить production AutomationEngine и довести его до production.

## Зона владения

Только:

- `mark/automation/**`
- tests

## Задачи

Проверить:

1. one-shot;
2. interval;
3. recurring;
4. cron;
5. enable/disable;
6. cancellation;
7. persistent state;
8. restart recovery;
9. run history;
10. failure history;
11. idempotency;
12. отсутствие duplicate side effects после restart;
13. timezone;
14. malformed cron;
15. missed schedules;
16. concurrent execution;
17. clean shutdown.

Не использовать `SimpleAutomationEngine` или test-only реализацию как доказательство production correctness.

## Acceptance criteria

- Restart не создаёт duplicate execution.
- Recurring/cron semantics детерминированы.
