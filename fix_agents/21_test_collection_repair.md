# Агент 21 — Test Collection Repair

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

Добиться полной pytest collection без скрытия production defects.

## Зона владения

- `tests/e2e/vision/test_e2e_rtsp_pipeline.py`
- `tests/integration/test_browser.py`
- только минимальные production imports/dependency declarations, если без этого невозможно исправление

## Задачи

1. Воспроизвести:
   ```bash
   pytest --collect-only
   ```
2. Зафиксировать точные traceback обоих failures.
3. Определить root cause:
   - неправильный import;
   - отсутствующий optional dependency;
   - переименование module;
   - production defect.
4. Исправить root cause.
5. `pytest.importorskip` разрешён только если dependency действительно optional.
6. Нельзя skip/xfail тест ради зелёного результата.
7. После исправления снова выполнить `pytest --collect-only`.
8. Затем запустить оба test modules.
9. Если возможно — полный `pytest`.

## Acceptance criteria

- 0 collection errors.
- Нет новых скрытых skips для production defects.
