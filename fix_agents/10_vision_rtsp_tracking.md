# Агент 10 — Vision / RTSP / Tracking

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

Полностью проверить и закончить production Vision subsystem.

## Зона владения

Только:

- `mark/vision/**`
- vision tests

## Проверить

1. images;
2. screenshots;
3. camera;
4. RTSP;
5. video;
6. sampled frame sequences;
7. OCR;
8. detection;
9. localization/bounding boxes;
10. tracking;
11. persistent person/object IDs;
12. same-entity association;
13. appearance/disappearance;
14. trajectories;
15. temporal history;
16. event/change/activity understanding.

## RTSP требования

- настоящий frame parsing;
- bounded queues;
- timestamps;
- stale-frame dropping;
- backpressure;
- reconnect;
- cancellation;
- timeout;
- no infinite buffering;
- cleanup;
- max active tracks;
- stale TTL.

Никаких fake empty detectors как production implementation.

## Acceptance criteria

- RTSP/video pipeline bounded и отменяемый.
- Tracking state ограничен и очищается.
