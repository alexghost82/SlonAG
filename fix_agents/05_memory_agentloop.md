# Агент 05 — Memory ↔ AgentLoop

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

Исправить несовместимость memory callback API внутри AgentLoop.

## Зона владения

Разрешено:

- `agent/**`
- agent-specific tests

Не менять:

- `mark/memory/**`
- `mark/bridge/**`

## Подтверждённая проблема

Один callback используется одновременно как:

- `retrieve(query) -> context`
- `persist(user, assistant)`

## Задачи

Разделить на два production interfaces:

1. `memory_context_callback(user_input) -> str`
2. `memory_on_turn_complete(user_input, assistant_output) -> None`

Дополнительно:

3. Memory context должен быть bounded.
4. Memory failure не должна ломать основной chat.
5. Ошибки memory должны логироваться.
6. Добавить tests: retrieval, write callback, exception, no memory, bounded context, multi-turn.
7. Не менять MemoryStore implementation.

## Acceptance criteria

- Read/write contracts разделены.
- AgentLoop корректно работает как с memory, так и без неё.
