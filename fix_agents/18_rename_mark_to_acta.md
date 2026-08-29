# Агент 18 — Rename `mark` → `acta`

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


## Важно

Работай одновременно с остальными агентами в своём worktree, но этот commit финальный интегратор должен применять ПОСЛЕДНИМ.

## Цель

Полностью переименовать namespace:

`mark` → `acta`

только с маленькой буквы.

## Требования

Переименовать:

- `mark/` → `acta/`
- `mark.*` → `acta.*`

во всём repository.

Проверить:

- Python imports;
- dynamic imports;
- strings;
- config;
- tests;
- scripts;
- docs;
- packaging;
- pyproject/setup;
- test fixtures;
- type checking;
- mocks;
- patch paths;
- CLI;
- server;
- UI;
- iOS-related references;
- tooling.

## Очень важно

Не делать тупой global replace слова `mark`.

Менять только случаи, относящиеся к Python/package namespace или filesystem path проекта.

Обычные переменные/слова `mark`, `mark_as_read` и т. п. не менять, если они не относятся к namespace.

## Acceptance criteria

После применения commit поверх интегрированной ветки:

```bash
find . -type d -name mark
grep -R "from mark\\|import mark\\|mark/" .
```

не должны находить старые project namespace references, кроме явно документированных historical/migration notes.

Все imports должны использовать `acta.*`.

Commit должен содержать только rename/migration, без функционального redesign.
