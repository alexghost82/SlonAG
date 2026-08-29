# Агент 06 — Preference Learning

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

Довести существующий `mark/preference_learning` до production-ready состояния.

## Зона владения

Только:

- `mark/preference_learning/**`
- tests этой subsystem

## Задачи

Проверить и реализовать полностью:

1. preference candidate creation;
2. explicit corrections;
3. confidence;
4. evidence;
5. provenance;
6. decay;
7. conflicts;
8. superseding old preference;
9. inspect;
10. edit;
11. delete;
12. forget;
13. pause/disable;
14. clear;
15. export;
16. secret filtering;
17. bounded storage;
18. deterministic tests.

## Acceptance criteria

- Слабый одиночный косвенный сигнал не превращается автоматически в постоянное предпочтение.
- Пользователь может полностью управлять сохранёнными предпочтениями.
