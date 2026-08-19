# AGENTS.md — Slon

Этот файл задаёт правила для главного интегратора и изолированных implementation sub-agents.

## Репозиторий

- Интеграционный клон: `/Users/slon/Documents/GitHub/Slon`
- Интеграционная ветка: `integration/main`
- Worktrees: `/Users/slon/mark-worktrees/<wave>-<task-id>-<short-name>`
- Ветки задач: `agent/<wave>-<task-id>-<short-name>`
- Never push to third-party/upstream remotes; push only to `alexghost82` when requested; local by default.
- **Git push policy (2026-08-15):** local by default; when push is requested, only `alexghost82`. Never push to third-party or upstream remotes (any other org/user). Non-`alexghost82` remotes may fetch, but `pushUrl` must stay `DISABLED`. A push-capable remote is allowed only under `alexghost82` after the user creates/requests that repo. As of 2026-08-15 no `alexghost82` Slon GitHub repo exists — push remains disabled until then.

## Неприкосновенные правила

1. Существующие незакоммиченные изменения пользователя в других копиях репозитория принадлежат пользователю. Не удалять, не сбрасывать и не перезаписывать их.
2. Никогда не использовать `git reset --hard`, принудительный checkout или массовое удаление.
3. Не добавлять в Git API-ключи, память, модели, логи, пользовательские данные, `.venv` и временные файлы.
4. Каждый саб-агент работает только в собственной ветке и отдельном Git worktree.
5. Саб-агент изменяет только `owned_paths` из своего task-файла.
6. Саб-агент не читает незавершённые рабочие файлы другого агента с целью их последующего изменения.
7. Только главный агент-интегратор переносит изменения в `integration/main`.
8. Саб-агенты не выполняют merge, rebase или cherry-pick чужих веток.
9. Общие центральные файлы нельзя раздавать нескольким агентам одновременно.
10. Если две задачи требуют изменения одного файла, они зависимы.
11. Если задача зависит от ещё не интегрированного API, саб-агент создаёт только согласованный интерфейс или mock в собственном модуле.
12. Любое действие, влияющее на лицензирование, приватность, публичный сетевой доступ, стоимость или необратимое удаление, требует остановки и запроса решения пользователя.

## Обязательный префикс саб-агента

Ты работаешь как изолированный implementation sub-agent.

Работай только в предоставленном Git worktree и только в своей ветке.
Твой base commit указан в task-файле.
Тебе разрешено изменять только Owned paths из task-файла.
Все остальные файлы являются read-only и считаются собственностью других агентов.

Не выполняй merge, rebase, cherry-pick или pull чужих веток.
Не изменяй код, созданный другими агентами.
Не исправляй попутно проблемы вне своей задачи.
Не форматируй весь проект.
Не обновляй lock-файлы, общие contracts, routing tables или центральную конфигурацию, если они явно не входят в Owned paths.

Если для выполнения требуется изменить Forbidden path или общий интерфейс:

1. немедленно останови изменения;
2. опиши точную причину;
3. подготовь короткий change request интегратору;
4. не применяй обходное решение, создающее дублирующую архитектуру.

Перед завершением:

1. выполни только относящиеся к задаче тесты;
2. проверь git diff и отсутствие изменений вне Owned paths;
3. проверь отсутствие секретов и generated artifacts;
4. создай один логический commit;
5. верни SHA, список файлов, тесты, известные ограничения и integration notes.

## Shared files

Внутри одной волны каждый из этих файлов может иметь только одного владельца:

```text
main.py
ui.py
providers/contracts.py
providers/router.py
config/schema.py
server/schemas.py
pyproject.toml
requirements*.txt
locale catalogs
Xcode project files
Package.swift
```

## Stop conditions

- необходимость изменить forbidden path;
- конфликт требований;
- отсутствующий контракт;
- обнаруженная утечка секрета;
- destructive или внешнее действие без разрешения;
- коммерческое утверждение при действующей CC BY-NC 4.0;
- публикация Desktop API в интернет;
- копирование `config/api_keys.json` или `memory/*.json`.
