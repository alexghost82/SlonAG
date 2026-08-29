# Агент 01 — Provider Runtime Integrity

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

Исправить production provider layer проекта, не затрагивая server, memory, vision и другие подсистемы.

## Зона владения

Разрешено менять:

- `providers/**`
- provider-related части `config/**`
- provider-specific tests

Не менять:

- `mark/bridge/**`
- `agent/**`
- `server/**`
- UI-файлы

## Обязательные задачи

1. `openai_compat` должен быть полноценным зарегистрированным provider.
2. Router должен явно понимать `openai_compat`.
3. Убрать зависимость от случайного предварительного import для регистрации provider.
4. Provider должен корректно принимать custom `base_url`.
5. `base_url` должен быть нормализован и валидирован.
6. Cloud/local provider classification должна быть однозначной.
7. Никогда не делать silent cloud fallback из local provider.
8. `list_models()`, `validate()`, `chat()`, `stream()` должны вести себя согласованно.
9. Ошибки authentication/network/model-not-found должны быть typed и не маскироваться.
10. Добавить regression tests для OpenAI, Gemini, OpenRouter, Ollama, llama.cpp и generic OpenAI-compatible endpoint.
11. Проверить сохранение `tool_call_id`.
12. Не добавлять test-only duck typing, если production contract можно сделать корректно.

## Acceptance criteria

- Provider layer имеет явный production contract.
- Поведение не зависит от import order.
- Custom endpoint реально доходит до adapter.
- Никаких silent fallbacks.
