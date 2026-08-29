# Агент 23 — Project Packaging / Tooling

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

Создать современный tooling/packaging слой без нарушения существующей установки.

## Зона владения

- `pyproject.toml`
- `.pre-commit-config.yaml`
- `.env.example`
- packaging metadata
- `__main__.py` при необходимости
- tooling documentation

Не изменять production subsystem implementations.

## Задачи

1. Исследовать текущие requirements/setup/install scripts.
2. Создать `pyproject.toml` без разрушения существующей установки.
3. Не дублировать зависимости хаотично.
4. Добавить project metadata.
5. Настроить только реально применимые:
   - pytest;
   - ruff;
   - mypy, если кодовая база действительно готова.
6. Добавить pre-commit для:
   - trailing whitespace;
   - YAML/TOML validation;
   - ruff;
   - secret-pattern detection.
7. `.env.example` должен содержать только placeholders.
8. Никаких настоящих API keys.
9. Проверить root module entrypoint.
10. Если `__main__.py` нужен — добавить минимальный canonical launcher.
11. Проверить installation/import tests.

## Acceptance criteria

- Tooling воспроизводим.
- Packaging не ломает существующий runtime.
