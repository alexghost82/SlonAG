# Агент 15 — Observability + No False Capabilities

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

Сделать честное состояние компонентов и диагностику.

## Зона владения

Разрешено:

- observability/status modules
- capability/status reporting
- related tests

Не переписывать функциональные subsystem.

## Требования

Каждый major component должен иметь состояния вроде:

- available;
- unavailable;
- degraded;
- misconfigured;
- disabled.

Нельзя возвращать `ready`, если implementation:

- stub;
- mock;
- test-only shim;
- отсутствует;
- не прошёл validation.

Логи должны содержать, где уместно:

- correlation/run/session IDs;
- provider/model;
- tool call IDs;
- latency;
- recovery status;

и не содержать secrets.

## Acceptance criteria

- Capability reporting отражает реальное состояние runtime.
