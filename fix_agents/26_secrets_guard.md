# Агент 26 — Secrets Guard

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

Предотвратить случайный commit секретов и чувствительных локальных конфигов.

## Зона владения

- config secret-handling safeguards
- `.gitignore`
- secret-check hooks/config
- security tests

Не изменять реальные user credentials.

## Задачи

1. Проверить tracking status `config/api_keys.json`.
2. Никогда не commit реальные credentials.
3. Проверить `.gitignore`.
4. Добавить regression mechanism, не позволяющий случайно закоммитить:
   - `config/api_keys.json`;
   - `sk-*`;
   - `AIza*`;
   - bearer tokens;
   - private keys.
5. Test values не должны выглядеть как реальные активные credentials, если scanner воспринимает их как secrets.
6. Не переписывать git history.
7. Не делать history rewrite.
8. Не удалять пользовательские локальные secret files.

## Acceptance criteria

- Sensitive config не попадает в commit случайно.
- Secret scanning не требует хранения реальных секретов.
