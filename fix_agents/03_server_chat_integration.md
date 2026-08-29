# Агент 03 — Server Chat Production Integration

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

Исправить production defect `/v1/chat`.

## Зона владения

Разрешено:

- `server/**`
- server-specific tests

Не менять:

- `agent/**`
- `mark/bridge/**`
- `providers/**`

## Подтверждённая проблема

Текущий `ChatHandlerWithRuntime` ищет `stack.agent_loop`, хотя canonical RuntimeStack предоставляет factory.

Также route вызывает `agent_loop.run_once(...)`, хотя canonical AgentLoop использует `run(...)`.

## Задачи

1. Убрать production зависимость от несуществующего `stack.agent_loop`.
2. Перейти на явный runtime protocol/factory.
3. Использовать canonical `AgentLoop.run(...)`.
4. Убрать silent fallback на fake `approval_required`, если production runtime сконфигурирован неправильно.
5. Configuration/runtime defect должен возвращать честную typed error.
6. Stub допустим только в специально созданном test/mock handler.
7. Сохранить authentication, idempotency, conversation ID, tool observations и approval semantics.
8. Добавить server integration tests.
9. Проверить multiple tool turns.
10. Проверить provider failure и tool failure.

## Acceptance criteria

- `/v1/chat` реально вызывает canonical AgentLoop.
- Нет вызова несуществующего `run_once`.
- Нет скрытого production fallback на stub.
