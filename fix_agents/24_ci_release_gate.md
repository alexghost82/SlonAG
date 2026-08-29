# Агент 24 — CI Release Gate

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

Добавить GitHub Actions CI, который реально падает при проблемах.

## Зона владения

- `.github/workflows/**`
- CI-specific config only

Не менять production code.

## Задачи

Создать CI с обязательными steps:

1. checkout;
2. поддерживаемая версия Python согласно реальному проекту;
3. dependency install;
4. pytest collection;
5. pytest;
6. ruff, если принят в `pyproject.toml`;
7. mypy только если configuration действительно рабочая.

## Запрещено

- `continue-on-error: true` для обязательных checks;
- `|| true`;
- маскирование failures;
- fake green hardware tests.

## Дополнительно

1. Optional hardware tests должны быть явно environment-gated.
2. CPU CI не должен притворяться, что протестировал GPU/RTSP hardware path.
3. Cache допустим.
4. Secrets только через GitHub secrets.
5. Добавить workflow validation/config check, если возможно.

## Acceptance criteria

- CI красный при реальном unit/integration failure.
- Нет шагов, скрывающих ошибки.
