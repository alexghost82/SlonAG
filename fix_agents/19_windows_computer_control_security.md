# Агент 19 — Windows Computer Control Security

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

Устранить потенциальные command injection paths в Windows computer control.

## Зона владения

- `computer_control/_windows.py`
- tests, относящиеся к Windows computer control

Не менять другие subsystem.

## Задачи

1. Проверить все `subprocess.Popen`, `subprocess.run`, `os.system` вызовы.
2. Особенно проверить `app_launch` и участки с `shell=True`.
3. Удалить передачу пользовательской/agent-generated строки в `shell=True`.
4. Предпочитать `shell=False` и argv list.
5. Для запуска приложений:
   - определить безопасный executable;
   - валидировать путь;
   - не интерпретировать shell separators;
   - не разрешать command chaining.
6. Не считать `shlex.split()` полноценной защитой Windows shell injection.
7. Не создавать blacklist, если shell можно полностью исключить.
8. Сохранить существующую функциональность запуска приложений.
9. Добавить security regression tests минимум для:
   - `;`
   - `&&`
   - `||`
   - `|`
   - `>`
   - `<`
   - `%COMSPEC%`
   - `cmd /c`
   - `powershell`
   - quoted executable paths
   - Unicode/homoglyph cases.
10. Проверить все остальные launch/process helpers в этом файле.

## Acceptance criteria

- User/agent input не интерпретируется shell.
- App launch остаётся функциональным.
