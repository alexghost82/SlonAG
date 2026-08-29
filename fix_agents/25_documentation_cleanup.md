# Агент 25 — Documentation + Repository Cleanup

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

Создать README на основании реального проекта и удалить подтверждённый мусор.

## Зона владения

- `README.md`
- `docs/**`
- tracked root test garbage files
- `.gitignore` только при необходимости

Не менять production Python.

## Задачи

1. Создать `README.md` на основании реального текущего проекта.
2. Не придумывать capabilities.
3. Описать:
   - назначение;
   - architecture;
   - supported OS;
   - installation;
   - configuration;
   - запуск desktop;
   - запуск server;
   - providers;
   - privacy/security;
   - testing;
   - troubleshooting.
4. Проверить существующие ADR и ссылаться на них.
5. Проверить файлы:
   - `dest.txt`
   - `dispatch_test.txt`
   - `dispatched.txt`
   - `write_test.txt`
6. Перед удалением выполнить repository-wide search references.
7. Не удалять используемый fixture.
8. Проверить ссылки README.

## Acceptance criteria

- README соответствует фактическому коду.
- Мусор удалён только после доказательства, что он не используется.
