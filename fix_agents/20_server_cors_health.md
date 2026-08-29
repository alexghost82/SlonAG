# Агент 20 — Server Hardening: CORS + Health

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

Добавить корректные CORS и health/readiness endpoints без ослабления LAN security.

## Зона владения

- `server/app.py`
- `server/listener.py`
- `server/routes/status.py`
- server-specific tests

Не менять AgentLoop/provider/gateway internals.

## Задачи

1. Проверить реальную HTTP architecture перед изменениями.
2. Добавить `/v1/health`.
3. Отдельно определить readiness, если architecture это поддерживает.
4. Health/readiness не должны заявлять READY при critical runtime failure.
5. Добавить CORS только на уровне реального FastAPI application.
6. Не использовать `allow_origins=["*"]`.
7. Использовать explicit configurable whitelist.
8. По умолчанию deny неизвестные origins.
9. Credentials разрешать только при корректной origin policy.
10. Добавить tests:
    - allowed origin;
    - rejected origin;
    - OPTIONS/preflight;
    - health healthy;
    - degraded dependency;
    - protected routes остаются protected.

## Acceptance criteria

- CORS строгий и конфигурируемый.
- Health/readiness честно отражают runtime.
