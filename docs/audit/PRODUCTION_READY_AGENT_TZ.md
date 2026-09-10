# PRODUCTION_READY — Agent Execution Spec

**Clone:** `/Users/alexandr.bogdanov/Documents/GitHub/ghst/SlonAG`  
**Ветка:** `agent/r0-r11-core-hardening` (проверено; HEAD `5de598c`)  
**Дата ТЗ:** 2026-09-09  
**Не merge, не push, не `integration/main`.**  
**Ghost не реализовывать.**  
**Desktop API в интернет не публиковать.**  
**iOS deferred by user; not a gate.** Не включать `ios/**`, iPhone, pairing-on-device, AppProject/MarkRemote как обязательные работы.

Язык инструкций — русский. Пути, символы, команды, nodeid — English.

---

## 0. Goal and verdict target

| Поле | Значение |
| --- | --- |
| Current | `NOT_PRODUCTION_READY` (R11, `docs/audit/SLON_PRODUCTION_READINESS_REPORT.md`) |
| Target | `PRODUCTION_READY` для **software gate** |
| Hardware / iOS | Не требуются для вердикта. Mic barge-in, iOS LAN pairing, GPU/RTSP — documented limitations, не блокер. |

R0–R11 закрыты как волны (12 коммитов). Это «волна закоммичена», не «продукт готов». Канонический стек уже есть: `AgentLoop` / `ProviderRouter` / `ToolExecutor` / `SafetyPolicy` / `JobEngine` / `RuntimeEventBus` / `acta.memory`. Вторую архитектуру не строить.

### Non-negotiables (master DoD минус iOS)

1. Одна плоскость рассуждения: `AgentLoop` владеет tools/memory/session. Gemini Live не второй runtime.
2. Provider-neutral live/voice contract. Core (`agent/runtime.py`) не импортирует Gemini Live.
3. `local_only` / `offline` / `fully_local` — физически без cloud (включая Live, memory extract, embeddings, vision, telemetry).
4. Один AI plane: SDK только в `providers/**` (+ documented `config/onboard.py`).
5. Один memory path: канон `acta.memory` SQLite + provenance.
6. Durable jobs: `runtime.jobs.JobEngine` — source of truth; нет RAM-only production queue.
7. Thin UI: виджеты только commands/events.
8. Tools: `ToolRegistry` → `SafetyPolicy` → Approval → `ToolExecutor`. `acta/tools/executor.py` уже hardened (R1) — не переписывать без leftover-доказательства.
9. Gateway — единственная remote-граница (python). `server/*` остаётся local `/v1`. TLS/pairing/Ed25519 не ослаблять.
10. Обязательный quality gate зелёный: pytest collect+run, `ruff check .`, `ruff format --check .`, `mypy`.
11. Секреты не в логах/исключениях. Нет `print()` на production hot path.
12. Не реализовывать Ghost. Не публиковать Desktop API. Не копировать `config/api_keys.json` / `memory/*.json`.

---

## 1. Rules for every agent

Ты isolated implementation sub-agent. Читай и соблюдай префикс из `AGENTS.md`.

1. Работай только в этом clone и только в своей ветке/worktree. Base commit — из task-файла (сейчас `5de598c`, если интегратор не указал иной).
2. Меняй только `owned_paths`. Остальное read-only.
3. Не merge / rebase / cherry-pick / pull чужих веток. Не push.
4. Не трогай `ios/**`. Не реализуй Ghost.
5. Не создавай вторую архитектуру (второй bus, второй JobEngine, второй memory store, второй AgentLoop).
6. Shared files в одной волне — один владелец: `main.py`, `ui.py` / `ui/**`, `providers/contracts.py`, `providers/router.py`, `config/schema.py`, `server/schemas.py`, `pyproject.toml`, `requirements*.txt`.
7. Если нужен forbidden / shared path вне owned — стоп, change request интегратору. Не дублировать API.
8. Не ослаблять security, не skip/xfail/disable тесты ради зелёного, не расширять `mypy` `ignore_errors` / ruff `exclude`.
9. Не форматировать весь репозиторий. Не массовый `ruff check --fix .` вне своей карты.
10. Перед сдачей: только относящиеся тесты; `git diff` только owned_paths; нет секретов; один логический commit; вернуть SHA, файлы, тесты, limitations, integration notes.
11. Не изобретать PASS. Статус только с командой + exit + counts.

### Запрещённые обходы (см. §6)

`pytest.mark.skip` / `xfail` без environment-gate; `except Exception: pass` на security path; `continue-on-error` в CI; сужение `pyproject.toml` include; `ignore_errors = true` на новые пакеты.

---

## 2. Dependency graph

### Уже закрыто (не переоткрывать, не делать заново)

Доказательства: wave-R1…R10 + R11 report + повторный прогон 2026-09-09.

| Тема | Evidence |
| --- | --- |
| ToolExecutor parallel/retry, hardened `shell_exec`, `_safe_cwd` resolve | R1; `acta/tools/executor.py` не re-do |
| Production `AgentExecutor(` = 0; queued text → AgentLoop | R2; `tests/architecture/test_no_agent_executor_construction.py` |
| SDK allowlist; `or_client` без production callers | R3; `tests/architecture/test_provider_imports.py` |
| SQLite memory + provenance; runtime sqlite untracked | R4 |
| `JobEngine` + event bus catalog | R5; leftover = TaskQueue/automation wiring |
| Gateway/session python tests | R6; iOS MANUAL, не gate |
| Typed `UiCommand`; VoiceBridge; UI не импортирует AgentLoop/ToolExecutor/Router/Live | R7; leftover = виджеты + SlonLive reasoning |
| MCP CONFIRM; FS `/var`; web content UNTRUSTED | R8; leftover = Playwright + MCP `mcp` import |
| `voice_*` round-trip; metrics catalog; `/v1/health` sanitize | R9; leftover = wiring + `print()` |
| Staged ruff include `runtime/jobs.py|metrics.py|commands.py`; cross-platform import smoke | R10; `tests/architecture/test_cross_platform_imports.py` **2 passed** — не писать заново |
| Health/readiness | `server/routes/status.py` `health_check` / `get_status` + `sanitize_body` — отдельная карта не нужна |

### Волны (порядок)

```text
W1  (параллельно, непересекающиеся owned_paths)
    PR-001 Live plane          [A]  shared: main.py
    PR-003 Wave15 AgentLoop    [B]  agent/runtime.py
    PR-009 FS roots coerce     [C]  acta/filesystem/security.py + operations.py

W2  (после W1; PR-001 должен закрыть main.py)
    PR-002 local_only+Live     [A]  main.py + tests/offline + config/schema.py
    PR-004 E2E FS/path         [C]  tests/e2e + leftover FS  (после PR-009)
    PR-008 trash delete        [D]  actions/file_controller.py (после PR-009 если нужен operations.py — тогда D ждёт C)

W3  (параллельно, разные файлы)
    PR-005 Playwright gate     [E]  tests/integration/test_browser + runtime/browser
    PR-006 MCP mcp-dep         [F]  acta/mcp + requirements*.txt  (один владелец requirements)
    PR-007 listener online     [G]  server/listener.py (+ observability если нужно)
    PR-004b automation API     [H]  acta/automation/engine.py
    PR-004c schema aliases     [I]  server/schemas.py  (shared — один владелец)

W4  P1 (после зелёных P0 pytest кластеров, кроме полного ruff/mypy)
    PR-020 TaskQueue→JobEngine [A]  agent/task_queue.py + runtime/jobs.py
    PR-021 Thin UI             [B]  ui/**  (не main.py в той же волне)
    PR-022 Single memory       [A или C]  memory/** + main.py — sequential с тем, кто держит main.py
    PR-023 or_client tests-only[D]
    PR-024 Automation→JobEngine[H]  после PR-004b
    PR-026 logging/print       [E]  без pyproject
    PR-027 metrics wire        [F]  agent/runtime.py после PR-003; иначе ждать
    PR-028 secrets in logs     [G]
    PR-029 bounded queues      [A]  можно слить с PR-020

W5  Quality lint/types (последняя; один владелец pyproject.toml)
    PR-010 ruff check (включённые пакеты, без расширения exclude)
    PR-011 ruff format --check
    PR-012 mypy (stubs / python_version; не ignore_errors на agent/actions/memory)
    PR-025 staged include agent/actions/memory — только после PR-026/022/023 и зелёного check этих модулей
```

**Не параллелить** карты, которые делят файл. `tests/e2e/test_e2e_chain.py` — один владелец на волну (PR-004). `acta/filesystem/operations.py` — PR-009 затем PR-008/PR-004.

### Зависимости по смыслу

```text
PR-001 → PR-002 → PR-021 / PR-022 (main.py)
PR-003 → PR-027 (agent/runtime.py)
PR-009 → PR-004 → (часть pytest P0)
PR-009 → PR-008
PR-004b → PR-024
PR-006 → PR-012 (mcp stub)
pytest P0 cards → PR-010/011/012
модули agent/actions/memory чистые → PR-025
```

---

## 3. Task cards

Доказательная база quality gate (повтор 2026-09-09, не выдуманный PASS):

```text
Command: .venv/bin/python -m pytest tests --tb=no -q --no-header
Result:  17 failed, 2540 passed, 28 skipped, 4 warnings, 33 errors in 78.56s
         exit 1
Совпадает с R11: 17 failed / 2540 passed / 28 skipped / 33 errors.
```

```text
Command: .venv/bin/python -m ruff check . --statistics
Result:  512 errors (F401 219, I001 162, F841 38, F811 25, E402 22, F821 13, …)
         419 fixable. exit 1
```

```text
Command: python -m ruff format --check .
Result:  R11: 253 files would reformat. exit 1  (не перезапускался в этом ТЗ)
```

```text
Command: .venv/bin/python -m mypy --no-error-summary
Result:  8 errors / 8 files (см. PR-012). exit 2
```

---

### PR-001 — Одна плоскость: Live не второй AgentLoop

- **Priority:** P0
- **Why it blocks PRODUCTION_READY:** R11 §5/§22: One AgentLoop = PARTIAL. `SlonLive` владеет realtime tools через `LiveToolBridge`, а не через `AgentLoop`. `main.py:709-711` явно: audio Gemini → SlonLive, не AgentLoop.
- **Evidence:**
  - `main.py:SlonLive` — `create_live_client` (`main.py:642`), `LiveToolBridge.execute` (`main.py:428`), `export_gemini_tools`
  - `main.py:_run_chat_agent` — `if provider_id == "gemini" and "audio" in model_id: return False`
  - `providers/gemini/live.py:create_live_client` — единственная фабрика клиента
  - `runtime/canonical_voice.py:VoiceBridge` — provider-neutral STT→AgentLoop→TTS; **не подключён** к `SlonLive.run`
  - `tests/architecture/test_ui_thin_client.py::test_agent_loop_does_not_import_gemini_live` — AgentLoop чист; Live остаётся в `main.py`
- **Root cause:** R7 оставил Gemini Live как transport, но `SlonLive` по-прежнему сам исполняет tools/memory/session. Это второй reasoning plane.
- **Выбранный дизайн (обязателен, не выбирать заново):**
  1. **Единственный reasoner — `AgentLoop`.** Tools, memory extract/commit, session persist — только через `RuntimeStack` / `AgentLoop`.
  2. **Единственный desktop audio I/O — `VoiceBridge`.** STT → AgentLoop → TTS. Barge-in уже покрыт `tests/unit/speech/voice/test_voice_bridge.py`.
  3. **Gemini Live, если остаётся, — transport-only** внутри `providers/gemini/live.py`: сокет/аудиофреймы. Запрещено: собственный tool loop, собственный memory writer, `LiveToolBridge` как второй executor.
  4. `LiveToolBridge` либо удаляется с production path, либо становится тонким адаптером, который **форвардит** function-call в `AgentLoop`/`ToolExecutor` стека (не исполняет сам).
  5. Core (`agent/runtime.py`) не импортирует `providers.gemini.live` / `google.genai`.
- **Owned paths:**
  - `main.py`
  - `runtime/tool_bridge.py`
  - `runtime/live_session.py`
  - `runtime/lifecycle.py` (только если нужно убрать Live-reasoner glue)
  - `providers/gemini/live.py`
  - `tests/architecture/test_ui_thin_client.py`
  - `tests/unit/main/test_main_glue.py`
  - `docs/audit/PRODUCTION_READY_LIVE_CONTRACT.md` (короткий контракт: кто владеет audio vs tools)
- **Forbidden paths:** `ios/**`, `acta/tools/executor.py`, `pyproject.toml`, `ui/**` (UI — PR-021), `agent/runtime.py` (PR-003)
- **Depends on:** —
- **Implementation steps:**
  1. Зафиксировать контракт в `docs/audit/PRODUCTION_READY_LIVE_CONTRACT.md`: VoiceBridge = audio; AgentLoop = reasoner; `create_live_client` = optional transport.
  2. В `SlonLive.run` / `_run_chat_agent`: audio Gemini больше не обходит AgentLoop. Desktop voice стартует `VoiceBridge` (существующий `runtime.canonical_voice.VoiceBridge`).
  3. Убрать production-исполнение tools из `SlonLive._handle_*` / `LiveToolBridge.execute`. Если Live присылает function_call — передать в `RuntimeStack.create_agent_loop()` / уже созданный loop, не в локальный bridge-executor.
  4. Live memory: оставить только `format_store_for_prompt` / `commit_extracted_facts` через stack (уже R4); не добавлять JSON writer.
  5. Сохранить `create_live_client` только в `providers/gemini/live.py`. `main.py` может вызывать фабрику, но не `from google import genai`.
  6. Обновить `test_main_glue.py`: конструктор `SlonLive` не обязан исполнять tools; если класс станет тонким lifecycle — поправить тесты, не удалять покрытие session/cancel.
  7. Архитектурный тест: `main.py` AST — нет прямого tool-loop без `AgentLoop`; `agent/runtime.py` без `google.genai`.
- **Acceptance tests:**
  ```text
  python -m pytest tests/architecture/test_ui_thin_client.py tests/architecture/test_provider_imports.py tests/unit/speech/voice/test_voice_bridge.py tests/unit/main/test_main_glue.py tests/architecture/test_no_agent_executor_construction.py -q
  ```
  Assert: все passed. `rg -n "LiveToolBridge" main.py runtime/` — нет production execute, либо только forward. `rg -n "from google import genai" main.py` — пусто.
- **DoD:** Документ контракта есть. Нет второго tool-loop. AgentLoop не зависит от Gemini Live. Один commit.
- **Out of scope:** iOS voice, hardware barge-in MANUAL, Ghost, UI widget rewrite (PR-021), offline socket (PR-002).

---

### PR-002 — local_only / offline / fully_local включая Live

- **Priority:** P0
- **Why it blocks:** Master DoD: физический no-cloud. R1 закрыл extract + text_ops; Live всё ещё `create_live_client(api_key=...)` без режима.
- **Evidence:**
  - `main.py:642` `create_live_client` без проверки `local_only` / `offline` / `fully_local`
  - `tests/offline/test_adversarial_network_escape.py` — только memory extract + socket guard; нет Live/embeddings/vision/telemetry
  - R1/R3: `NeverFallbackPolicy` на Router text ops; Live не в harness
- **Root cause:** Offline fail-closed сделан для extract/Router, не для Gemini Live transport и не для остальных cloud side-channels.
- **Owned paths:**
  - `main.py` (после PR-001; тот же владелец волны)
  - `config/schema.py` (shared — только этот агент в волне)
  - `providers/gemini/live.py`
  - `tests/offline/test_adversarial_network_escape.py`
  - `tests/offline/test_live_local_only.py` (новый)
  - `tests/unit/providers/test_local_only_regression_gate.py` (дополнить)
- **Forbidden paths:** `ios/**`, `acta/tools/executor.py`, `pyproject.toml`
- **Depends on:** PR-001
- **Implementation steps:**
  1. Единый predicate (переиспользовать `_settings_forbid_cloud` / NetworkPolicy): `offline` | `local_only` | `fully_local` | `local_with_tools` | `tools_only` → cloud запрещён.
  2. `create_live_client` / `SlonLive.run` / VoiceBridge cloud STT/TTS: fail-closed, без скрытого fallback.
  3. Memory extract уже no-op offline — не ломать. Embeddings/vision/telemetry: любой non-loopback connect в этих режимах должен падать тем же harness.
  4. Расширить adversarial fixture на `google.genai` / Live connect и на вызовы telemetry. Не ослаблять тест, если `main.py` ещё ходит в cloud — чинить код.
  5. Не добавлять cloud fallback «на всякий случай».
- **Acceptance tests:**
  ```text
  python -m pytest tests/offline tests/unit/providers/test_local_only_regression_gate.py -q
  ```
  Assert: non-loopback connect под offline/local_only/fully_local → FAIL теста или fail-closed код; Live не создаёт client. Существующие 421 offline/security не регрессируют (кроме уже известных browser/Playwright).
- **DoD:** Live не уходит в cloud в forbid-режимах. Adversarial harness покрывает Live + extract. Один commit.
- **Out of scope:** hardware mic, iOS, расширение mypy ignore.

---

### PR-003 — Wave 15 offline AgentLoop

- **Priority:** P0
- **Why it blocks:** Spec Wave 15 «offline multi-turn agent» = CONTRADICTED. Два красных теста — production `AgentLoop`, не косметика.
- **Evidence (повторный прогон):**
  - `tests/integration/test_wave15_offline_agent.py::test_offline_agent_multi_turn_tool_execution`  
    `Observation.ok is False`; `kind=SAFETY_DENIAL` на `read_file` пути в `tmp_path`.
  - `tests/integration/test_wave15_offline_agent.py::test_offline_agent_budget_enforcement_turns`  
    expected `'max turns (3) reached'` in reason; actual `"Detected 3 consecutive identical tool calls for 'dummy_tool'"`  
    (`agent/runtime.py` LoopDetector после `record_call`, до исчерпания `max_turns`).
- **Root cause:**
  1. `SafetyPolicy()` + builtin `read_file` отклоняет pytest tmp (нет workspace allowlist в тесте / политика режет path).
  2. R2 loop-detector срабатывает на 3 одинаковых `dummy_tool` раньше, чем `LoopBudget.max_turns=3` становится причиной останова. Оба инварианта нужны: loop-detect **и** turn budget.
- **Owned paths:**
  - `agent/runtime.py`
  - `agent/executor.py` (`execute_agent_loop` только если нужно прокинуть workspace/policy)
  - `tests/integration/test_wave15_offline_agent.py`
  - при необходимости `acta/safety/policy.py` **только** если не хватает test hook — не ослаблять DENY для production
- **Forbidden paths:** `main.py`, `ios/**`, `acta/tools/executor.py` (не re-do), `pyproject.toml`
- **Depends on:** —
- **Implementation steps:**
  1. Multi-turn: дать тесту workspace = `tmp_path` (SafetyPolicy/ToolExecutor allowlist / trusted source), **или** зарегистрировать test-only read tool. Не делать `read_file` глобально ALLOW на любой path.
  2. После фикса: `result.ok is True`, observation содержит `Secret content 123`, 2 provider request.
  3. Budget: проверять `LoopBudget.is_exceeded()` / `turn_count >= max_turns` **до или вместо** loop-detector, когда лимит ходов уже достигнут; loop-detector оставить для случаев, когда budget ещё не исчерпан. Не удалять LoopDetector.
  4. Не менять остальные wave15 тесты на skip. `test_offline_agent_legacy_execute_plan_intact` уже green (R2).
- **Acceptance tests:**
  ```text
  python -m pytest tests/integration/test_wave15_offline_agent.py tests/unit/agent/test_runtime.py -q
  ```
  Assert: 0 failed. Оба nodeid выше passed. Loop-detector тесты (если есть) не сломаны.
- **DoD:** Wave 15 offline multi-turn + max_turns — green. Один commit.
- **Out of scope:** JobEngine, Live, ruff.

---

### PR-004 — E2E chain: FS, isolation, path-traversal

- **Priority:** P0
- **Why it blocks:** E2E path-traversal красный на production `validate_path`. Это security path, не «хрупкий UI-тест».
- **Evidence:**
  - `tests/e2e/test_e2e_chain.py::TestFilesystemTool::test_read_write_file` — `Path outside allowlist` на pytest tmp (`/private/var/folders/...`); handler без `roots=tmp_workspace`.
  - `::TestWorkspaceIsolation::test_workspace_isolation` — `TraversalDetected` на `ws1/../workspace2/...` (ожидали `None`).
  - `::TestPathTraversalSymlink::test_path_traversal_blocked` — тот же raise; плюс API `validate_path(..., str)` vs roots tuple.
- **Root cause:** После R8 `validate_path` **raises** `TraversalDetected` / `PathDenied` и возвращает `Path`, а e2e написан под старый контракт `None`. `file_controller` legacy handler не получает workspace roots.
- **Owned paths:**
  - `tests/e2e/test_e2e_chain.py` (только эти классы; не трогать зелёные без нужды)
  - `acta/filesystem/security.py` (после PR-009 или вместе, если один агент)
  - `acta/tools/legacy/adapters.py` (прокинуть roots/workspace в `file_controller` **без** ослабления default allowlist)
- **Forbidden paths:** не расширять `default_allowlist_roots()` до всего `/var` или `/`. Не `shell=True`. `ios/**`.
- **Depends on:** PR-009 (roots coerce), иначе тот же файл `security.py`.
- **Implementation steps:**
  1. Не ослаблять deny traversal. Либо e2e ловит `TraversalDetected` и считает block успехом, либо публичный helper `try_validate_path` → `Path | None` для API, который обещал None. Production deny остаётся.
  2. `test_read_write_file`: передать `roots=(tmp_workspace,)` в handler/args. Default allowlist не обязан включать pytest tmp.
  3. Symlink: `validate_path(link/secret, tmp_path)` по-прежнему deny (None или exception). Не allow symlink escape.
  4. Не менять `tests/test_filesystem_security.py` (уже green после R8).
- **Acceptance tests:**
  ```text
  python -m pytest \
    tests/e2e/test_e2e_chain.py::TestFilesystemTool::test_read_write_file \
    tests/e2e/test_e2e_chain.py::TestWorkspaceIsolation::test_workspace_isolation \
    tests/e2e/test_e2e_chain.py::TestPathTraversalSymlink::test_path_traversal_blocked \
    tests/test_filesystem_security.py \
    tests/security/test_mcp_fs_r8.py -q
  ```
  Assert: listed e2e + FS suite passed. Никакого allow `/etc/passwd`.
- **DoD:** Три nodeid green. Traversal по-прежнему blocked. Один commit.
- **Out of scope:** Playwright, automation `list_rules` (PR-004b), schemas (PR-004c).

---

### PR-004b — E2E AutomationEngine.list_rules

- **Priority:** P0 (красный e2e production API)
- **Evidence:** `tests/e2e/test_e2e_chain.py::TestAutomation::test_automation_engine` — `AttributeError: 'AutomationEngine' object has no attribute 'list_rules'`. Engine = scheduler (`acta/automation/engine.py`), API — `AutomationJob`, не `AutomationRule`.
- **Root cause:** Тест ждёт старый shim `register(rule)` / `list_rules()`.
- **Owned paths:** `acta/automation/engine.py`, `acta/automation/types.py` (если нужен `AutomationRule` alias), `tests/e2e/test_e2e_chain.py` (только `TestAutomation` / `TestRestartAutomation` — **если PR-004 уже владеет этим файлом в той же волне, делать одним агентом sequential, не параллелить**)
- **Forbidden paths:** второй JobEngine, удаление JSON schedule store в этой карте (это PR-024).
- **Depends on:** не параллелить с PR-004 на одном `test_e2e_chain.py`.
- **Implementation steps:**
  1. Добавить тонкий совместимый `register` + `list_rules()` **или** поправить тест на публичный API (`add_job` / list job names). Предпочтительно: shim → существующие `AutomationJob`, без второго движка.
  2. `register` не должен исполнять action в обход будущего JobEngine (no-op / schedule only).
- **Acceptance tests:**
  ```text
  python -m pytest tests/e2e/test_e2e_chain.py::TestAutomation tests/e2e/test_e2e_chain.py::TestRestartAutomation tests/unit/automation -q
  ```
- **DoD:** nodeid green; unit automation не красные.
- **Out of scope:** enqueue в JobEngine (PR-024).

---

### PR-004c — E2E server schema aliases

- **Priority:** P0
- **Evidence:** `tests/e2e/test_e2e_chain.py::TestServerRoutes::test_server_routes_exist` — `ImportError: cannot import name 'ChatRequestSchema' from 'server.schemas'`. В файле есть `ChatRequest`, нет `*Schema` имён.
- **Root cause:** тест ждёт старые имена; канон — dataclasses в `server/schemas.py`.
- **Owned paths:** `server/schemas.py` (shared — единственный владелец волны), `tests/e2e/test_e2e_chain.py::TestServerRoutes` (тот же агент, что PR-004, если файл общий)
- **Forbidden paths:** не публиковать новые internet routes; не менять pairing/TLS поля.
- **Depends on:** sequential с любым другим владельцем `server/schemas.py`.
- **Implementation steps:**
  1. Добавить aliases: `ChatRequestSchema = ChatRequest`, и аналоги для импортируемых имён **или** поправить тест на `ChatRequest` / существующие классы. Aliases не меняют wire format.
  2. Если `SessionCreateSchema` / `ToolResultSchema` отсутствуют — добавить тонкие dataclasses, совместимые с тестом, без новой архитектуры.
- **Acceptance tests:**
  ```text
  python -m pytest tests/e2e/test_e2e_chain.py::TestServerRoutes tests/unit/server -q --ignore=tests/unit/server/test_listener.py
  ```
  Затем отдельно listener после PR-007.
- **DoD:** import + instantiate не падают.
- **Out of scope:** listener `online` (PR-007).

---

### PR-005 — Playwright / browser: честный environment gate

- **Priority:** P0 (CI не должен быть красным из‑за отсутствия Chromium на laptop; и не должен прятать реальные fail)
- **Why it blocks:** 33 ERROR + 3 FAIL + `test_browser_cleanup_on_shutdown` — локально нет Chromium. CI workflow **уже** делает `python -m playwright install --with-deps chromium` (`.github/workflows/ci-release-gate.yml`). Значит на CI это должен быть настоящий run, не skip.
- **Evidence:**
  - ERROR fixture `service()` → `BrowserLaunchError: Chromium не установлен` (`runtime/browser/service.py:94`)
  - Nodeids ERROR — все в `tests/integration/test_browser/test_browser_service.py` (33):  
    `TestAvailability::test_service_status_after_start`,  
    `TestNavigation::{test_load_local_html,test_navigate_http,test_navigate_adds_https,test_navigate_timeout}`,  
    `TestClick::{test_click_submit_button,test_click_text,test_click_role,test_click_increment}`,  
    `TestType::{test_type_into_selector,test_type_clears_first,test_press_key_tab,test_press_key_enter}`,  
    `TestDOM::{test_dom_get_text_body,test_dom_get_text_selector,test_dom_evaluate,test_bounded_extraction}`,  
    `TestForm::{test_fill_form,test_fill_and_submit}`,  
    `TestTabs::{test_list_tabs,test_create_tab,test_switch_tab,test_close_tab}`,  
    `TestCookies::{test_set_and_get_cookie,test_clear_cookies}`,  
    `TestScreenshot::test_screenshot_returns_png`,  
    `TestLifecycle::{test_close_page,test_close_all}`,  
    `TestBrowserControlActions::{test_action_navigate,test_action_click,test_action_fill_form,test_action_status,test_action_unknown}`
  - FAIL (нет Chromium, assert READY):  
    `::TestAvailability::test_detect_availability_when_ready`  
    `::TestAvailability::test_runtime_status_when_ready`  
    `::TestLifecycle::test_start_stop_twice_is_idempotent`
  - `tests/security/test_beta_security_gates.py::test_browser_cleanup_on_shutdown` — тот же `BrowserLaunchError`
- **Root cause:** fixture `start()` бросает ERROR вместо skip, когда runtime `NOT_READY`. Availability-тесты **требуют** READY на любой машине. CI Chromium ставит — локальный Mac в R11 не ставил.
- **Owned paths:**
  - `tests/integration/test_browser/test_browser_service.py`
  - `tests/security/test_beta_security_gates.py`
  - `runtime/browser/status.py` / `runtime/browser/service.py` (только skip-friendly detect, не вырезать engine)
  - `.github/workflows/ci-release-gate.yml` — **только если** нужно явно пометить browser как gated; **не** удалять `playwright install` из CI
- **Forbidden paths:** `xfail`, `continue-on-error`, удаление pytest job, `ios/**`
- **Depends on:** —
- **Implementation steps:**
  1. Ввести marker `@pytest.mark.playwright` (или reuse существующий). Fixture: если `detect_runtime_availability() != READY` → `pytest.skip("Playwright Chromium not installed")`, не ERROR.
  2. Availability-тесты: два слоя: (a) `test_detect_reports_missing_or_ready` без Chromium = NOT_READY/missing message; (b) `test_*_when_ready` skip unless READY.
  3. CI: оставить `playwright install`; на CI READY=true → тесты **бегут и должны пройти**. Не skip на CI.
  4. Не ставить Chromium в репозиторий. Не считать локальный skip = PASS продукта; в отчёте писать SKIPPED vs CI PASS.
  5. `test_browser_cleanup_on_shutdown`: тот же skip, если нет runtime; при READY — cleanup обязан закрыть browser.
- **Acceptance tests:**
  ```text
  python -m pytest tests/integration/test_browser/test_browser_service.py tests/security/test_beta_security_gates.py::test_browser_cleanup_on_shutdown --tb=no -q
  ```
  Локально без Chromium: 0 error, 0 fail, N skipped.  
  С Chromium (как CI): 0 failed.  
  Полный `pytest tests --collect-only -q` по-прежнему 0.
- **DoD:** нет 33 ERROR из‑за missing binary. CI путь остаётся обязательным. Один commit.
- **Out of scope:** вредоносная page injection MANUAL, GPU.

---

### PR-006 — MCP streamable HTTP: пакет `mcp`

- **Priority:** P0
- **Evidence:** три FAIL, одна причина `ModuleNotFoundError: No module named 'mcp'`:
  - `tests/unit/mcp_client/test_streamable_http.py::TestStreamableHttpConnectionFailure::test_connect_to_nonexistent_server_fails_gracefully`
  - `::TestStreamableHttpTransportMethods::test_stop_after_start_fails_gracefully`
  - `::TestMcpStreamableHttpTransportAsyncContext::test_aenter_raises_on_bad_server`  
  Import: `acta/mcp/streamable_http_transport.py:76` `from mcp.client.streamable_http import streamable_http_client`.  
  `mcp` **нет** в `requirements.txt` / `requirements-base.txt` / `requirements-dev.txt`. mypy тот же модуль (PR-012).
- **Root cause:** код зависит от SDK `mcp`, зависимость не зафиксирована. Fail-closed при отсутствии пакета сейчас = красный тест, не skip.
- **Owned paths:**
  - `requirements-base.txt` или `requirements-dev.txt` (shared — единственный владелец волны)
  - `acta/mcp/streamable_http_transport.py`
  - `tests/unit/mcp_client/test_streamable_http.py`
- **Forbidden paths:** не auto-approve MCP CONFIRM (R8). Не `pyproject.toml` exclude. Не ставить пакет «втихую» без pin.
- **Depends on:** —
- **Implementation steps:**
  1. Добавить официальный пакет `mcp` с совместимым pin в тот requirements-файл, которым пользуется CI (`requirements.txt` → base/dev по принятой схеме репо). Не угадывать yanked version — проверить PyPI/уже используемый API `streamable_http_client`.
  2. Если SDK необязателен в runtime: lazy import + явный `RuntimeError` с сообщением; тесты тогда используют установленный extra `dev`. Для CI extra должен стоять — тесты остаются обязательными.
  3. Не xfail. Не глотать `ModuleNotFoundError` как success.
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/mcp_client/test_streamable_http.py tests/security/test_mcp_fs_r8.py -q
  python -m mypy acta/mcp/streamable_http_transport.py
  ```
  После установки: 3 nodeid passed (connect к :19999 по-прежнему fail-closed).
- **DoD:** зависимость воспроизводима; тесты green без skip.
- **Out of scope:** полный MCP product rewrite.

---

### PR-007 — Listener pairing / status.online

- **Priority:** P0 (красный auth/status на local `/v1`)
- **Evidence:** `tests/unit/server/test_listener.py::test_listener_pairing_and_token_auth_roundtrip` — после Bearer `GET /v1/status` `body['online'] is False`, ожидали `True`. `server/routes/status.py` явно: «No fabricated `online=True`». Listener, видимо, отдаёт observability snapshot в состоянии offline.
- **Root cause:** status provider не считает запущенный listener «online», либо control plane дефолт `online=False` (`DesktopControlPlane` в тесте не обновляет state).
- **Owned paths:**
  - `server/listener.py`
  - `server/routes/status.py` (если нужно прокинуть listening)
  - `observability/status.py` (если отсюда `get_runtime_status`)
  - `tests/unit/server/test_listener.py`
- **Forbidden paths:** не ставить `online=True` константой в sanitize. Не ослаблять pairing/token. `ios/**`.
- **Depends on:** —
- **Implementation steps:**
  1. Прочитать фактический `/v1/status` path в `DesktopControlListener.handle`.
  2. Когда listener `listening` и токен валиден — `online` отражает реальный процесс (listening), не «есть cloud».
  3. Секреты по-прежнему отсутствуют в body (`api_key` not in status) — тест это уже проверяет.
  4. Не ломать `health_check` (без auth).
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/server/test_listener.py tests/unit/server/routes/test_routes_health.py -q
  ```
- **DoD:** pairing roundtrip green; health sanitize green.
- **Out of scope:** iOS pairing hardware.

---

### PR-008 — file_controller delete → trash

- **Priority:** P0 (красный unit; delete должен быть trash-only)
- **Evidence:** `tests/unit/actions/test_file_controller.py::test_delete_with_confirm_uses_trash_not_permanent` — после confirm `target.exists()` всё ещё True. `actions/file_controller.py:141` вызывает `trash(path_raw, roots=roots)`; file не уезжает. `Path.unlink` замокан (permanent запрещён).
- **Root cause:** `trash()` не удаляет файл (send2trash no-op / path deny / hook вызывается только при `result.ok`, а trash не ok). Тест инжектит `trash=trashed.append` как hook **после** успешного trash.
- **Owned paths:**
  - `actions/file_controller.py`
  - `acta/filesystem/operations.py` (`trash` только если баг там; после PR-009)
  - `tests/unit/actions/test_file_controller.py`
- **Forbidden paths:** permanent `unlink` как production delete. Не ослаблять confirm.
- **Depends on:** PR-009 если правите `operations.py`.
- **Implementation steps:**
  1. Проследить `trash()`: send2trash должен сработать на `tmp_path` с переданными roots. Если roots пустые — взять allowlist теста (`_run` уже передаёт).
  2. Если send2trash отсутствует — явная ошибка, не silent keep-file. В `.venv` пакет есть (`requirements-base.txt` `send2trash`).
  3. Hook `hooks.trash` вызывать после реального trash, чтобы тест видел `trashed == [target.resolve()]` и `not target.exists()`.
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/actions/test_file_controller.py -q
  ```
- **DoD:** nodeid passed; unlink/rmtree не вызываются.
- **Out of scope:** e2e file_controller (PR-004).

---

### PR-009 — FS roots: list[str] → Path.resolve

- **Priority:** P0
- **Evidence:** `tests/security/test_adversarial_regression.py::TestPathTraversal::test_traversal_through_symlink` — `AttributeError: 'str' object has no attribute 'resolve'` в `acta/filesystem/security.py:226` (`_safe_relative`). Вызов: `filesystem_operation(..., roots=[str(allowed)])`.
- **Root cause:** `validate_path` нормализует только `str` или `Path`, не `list[str]`. List уходит в `_safe_relative(root)` как str.
- **Owned paths:**
  - `acta/filesystem/security.py`
  - `acta/filesystem/operations.py` (нормализация roots на входе)
  - `tests/security/test_adversarial_regression.py`
- **Forbidden paths:** не allow symlink escape. Не startswith-prefix.
- **Depends on:** —
- **Implementation steps:**
  1. Функция `_coerce_roots(roots) -> tuple[Path, ...]`: list/tuple/str/Path → resolved Paths.
  2. Вызвать в `validate_path` и `filesystem_operation` до любого `.resolve()`.
  3. Symlink `allowed/escape → outside` + read `escape/classified.txt` → `path_denied` (тест уже так assert).
- **Acceptance tests:**
  ```text
  python -m pytest tests/security/test_adversarial_regression.py::TestPathTraversal tests/test_filesystem_security.py tests/security/test_mcp_fs_r8.py -q
  ```
- **DoD:** nodeid passed; FS suite остаётся green.
- **Out of scope:** e2e (PR-004).

---

### PR-010 — ruff check зелёный на текущем include

- **Priority:** P0 (CI job `ruff check .`)
- **Evidence:** 512 errors на include из `pyproject.toml` (`tests/**`, `acta/**`, `providers/**`, `speech/**`, `server/**`, `gateway/**`, `policies/**`, `localization/**`, `config/**`, `sessions/**`, `runtime/jobs.py|metrics.py|commands.py`). Не `actions/**` / `agent/**` / `memory/**` / `or_client.py` — их не включать здесь (PR-025).
- **Root cause:** drift после волн; 419 auto-fixable (F401/I001/…). F821 (13) — реальные undefined names, чинить руками.
- **Owned paths:** файлы **внутри текущего ruff include**, которые агент правит; `pyproject.toml` **не** расширять exclude и не сужать include.
- **Forbidden paths:** `ignore = ["F821"]`, exclude новых пакетов, format всего репо (PR-011).
- **Depends on:** желательно после P0 pytest карт, чтобы не драться в тех же файлах. Если конфликт — эта карта последняя в W5.
- **Implementation steps:**
  1. `ruff check . --statistics` — зафиксировать baseline.
  2. Безопасный `--fix` только F401/I001/W293 в include. Смотреть diff.
  3. F821/F841/E402/F811 — ручной фикс, не удалять логику.
  4. Не трогать `actions/**` `agent/**` `memory/**`.
- **Acceptance tests:**
  ```text
  python -m ruff check .
  ```
  exit 0.
- **DoD:** 0 ruff errors на текущем include.
- **Out of scope:** format (PR-011), mypy (PR-012), staged new packages (PR-025).

---

### PR-011 — ruff format --check

- **Priority:** P0 (CI step)
- **Evidence:** R11: 253 files would reformat.
- **Root cause:** style drift. Не «косметика» для CI.
- **Owned paths:** те же include, что ruff; один владелец волны. Sequential с PR-010 (тот же агент предпочтителен).
- **Forbidden paths:** format `actions/**` `agent/**` `memory/**` `or_client.py` (они вне include — не массово). Не format unowned чужие волны.
- **Depends on:** PR-010 (один агент: check --fix затем format).
- **Implementation steps:**
  1. `ruff format` только на пути из `tool.ruff.include`.
  2. `ruff format --check .` exit 0.
  3. Не рефакторить код «заодно».
- **Acceptance tests:**
  ```text
  python -m ruff format --check .
  python -m ruff check .
  ```
- **DoD:** оба exit 0.
- **Out of scope:** logic changes.

---

### PR-012 — mypy зелёный без расширения ignore

- **Priority:** P0
- **Evidence (этот прогон):**
  - `tests/offline/test_adversarial_network_escape.py:70` — `aiohttp` import-not-found
  - `tests/unit/tooling/test_packaging.py:58` — `yaml` import-untyped (types-PyYAML)
  - `acta/filesystem/operations.py:33` — `send2trash` import-untyped
  - `acta/mcp/streamable_http_transport.py:76` — `mcp.client.streamable_http` import-not-found
  - `providers/openai_compat.py:208` — `openai` import-not-found
  - `speech/stt/engines.py:84` — `faster_whisper` import-untyped
  - `config/onboard.py:617` — `openai` import-not-found
  - `.venv/.../numpy/__init__.pyi:737` — `type` statement vs `python_version = 3.11` в `pyproject.toml` при CPython 3.12
- **Root cause:** stubs/deps + mypy `python_version=3.11` ломает numpy 3.12 stubs. Не «ошибки в логике продукта».
- **Owned paths:**
  - `pyproject.toml` (только mypy overrides **точечно** `ignore_missing_imports` для third-party, **не** `ignore_errors` на `agent.*`/`actions.*`)
  - `requirements-dev.txt` (`types-PyYAML`, `types-Send2Trash` если нужны)
  - затронутые import-сайты (lazy `TYPE_CHECKING`)
- **Forbidden paths:** `[[tool.mypy.overrides]] ignore_errors = true` на новые пакеты. Не выключать Python 3.11 из CI.
- **Depends on:** PR-006 (mcp package снижает import-not-found).
- **Implementation steps:**
  1. `aiohttp` / `openai` / `mcp`: либо dep+stubs, либо существующий паттерн `ignore_missing_imports` в списке `module = [...]` (уже есть google/PIL; добавить недостающие **модули**, не пакеты приложения).
  2. numpy syntax: не поднимать `ignore_errors`. Варианты: `python_version = 3.12` **только если** CI 3.11 mypy остаётся честным; лучше `[[tool.mypy.overrides]] module = "numpy" followup`; или исключить numpy site-packages из проверки (не наш код). Зафиксировать выбранный вариант в commit message. Не врать, что 3.11 проверен, если выставили 3.12-only.
  3. Предпочтение: types packages в dev requirements + точечные module overrides, как уже сделано для `whisper`.
- **Acceptance tests:**
  ```text
  python -m mypy
  ```
  exit 0, 0 errors.
- **DoD:** mypy green; ignore_errors для agent/actions/memory **не расширен**.
- **Out of scope:** типизация всего `agent/**` (PR-025).

---

### PR-020 — TaskQueue → клиент JobEngine

- **Priority:** P1
- **Why it blocks:** RAM queue не переживает crash; duplicate side effects. SLON-023 leftover. `runtime/jobs.py` уже канон.
- **Evidence:** `agent/task_queue.py` — `list[Task]` + daemon thread; docstring JobEngine: TaskQueue «in-RAM adapter». `server/listener.py` / `LEGACY_HANDLERS["agent_task"]` → `get_queue()`.
- **Root cause:** R2 перевёл executor на AgentLoop; persist не делали (R5).
- **Owned paths:**
  - `agent/task_queue.py`
  - `runtime/jobs.py` (тонкий enqueue API, если нет)
  - `acta/bridge/__init__.py` (factory loop + job_engine)
  - `tests/agent/test_task_queue_agent_loop.py`
  - `tests/unit/runtime/test_jobs.py` (дополнить recovery)
- **Forbidden paths:** второй sqlite store. `main.py` в той же волне, что PR-001/002. `ios/**`.
- **Depends on:** PR-001 не обязателен; не делить `runtime/jobs.py` с другим агентом.
- **Implementation steps:**
  1. `TaskQueue.submit` → `JobEngine.enqueue` с `idempotency_key`, type=`agent_task`, payload=goal.
  2. Worker claim/complete/fail через JobEngine. Restart: RUNNING → recover (уже есть в JobEngine).
  3. In-memory list не source of truth. Можно оставить index для совместимости API `get_queue()`.
  4. Cancel → JobEngine CANCELLED, без второго complete.
  5. Не дублировать side effects: terminal states sticky (уже в JobEngine).
- **Acceptance tests:**
  ```text
  python -m pytest tests/agent/test_task_queue_agent_loop.py tests/unit/runtime/test_jobs.py tests/tools/test_legacy_adapters.py -q
  ```
  Новый тест: enqueue → kill-like close → new `JobEngine(path)` не re-exec completed; RUNNING recovered once.
- **DoD:** нет RAM-only production queue. Один commit.
- **Out of scope:** automation cron (PR-024), UI.

---

### PR-021 — Thin UI: только commands/events

- **Priority:** P1
- **Evidence:** R7: import invariant есть; `ui/_ui.py` всё ещё строит `DesktopControlPlane` / `build_runtime_stack` (~1865), импортирует `providers.contracts.AudioRequest` (строки 51, 1783). `ui.py` как файла нет — пакет `ui/`.
- **Root cause:** виджеты остались glue-слоем, не thin clients.
- **Owned paths:**
  - `ui/_ui.py`
  - `ui/onboard_widget.py`
  - `ui/**` остальные виджеты по факту импорта
  - `tests/architecture/test_ui_thin_client.py` (расширить запрет на `acta.bridge.build_runtime_stack`, `providers.contracts` если контракт требует)
  - `runtime/commands.py` (только новые kind, если не хватает)
- **Forbidden paths:** `main.py` в той же волне. Импорт AgentLoop/ToolExecutor/Live в ui — уже запрещён, не возвращать. `ios/**`.
- **Depends on:** PR-001 (voice commands уже есть: `start_voice`/`stop_voice`).
- **Implementation steps:**
  1. Виджеты: только `UiCommand` + event sink. `build_runtime_stack` / plane — в `main.py` / control plane, не в виджете.
  2. `AudioRequest` не из UI; команда `start_voice`.
  3. Расширить architecture test запрещёнными префиксами: `acta.bridge`, `providers.contracts` — **если** это не сломает легитимные type-only imports; тогда `if TYPE_CHECKING` только в tests, не в UI.
  4. Не переписывать визуальный дизайн.
- **Acceptance tests:**
  ```text
  python -m pytest tests/architecture/test_ui_thin_client.py tests/unit/runtime/test_ui_commands.py -q
  ```
- **DoD:** UI не создаёт RuntimeStack/Router. Один commit.
- **Out of scope:** Qt restyle, iOS.

---

### PR-022 — Один memory path: убрать live JSON manager

- **Priority:** P1
- **Evidence:** `main.py:13-18` импортирует `memory.memory_manager` (`format_memory_for_prompt`, `load_memory`, `should_extract_memory`, `extract_memory`). Live write уже SQLite (R4). Callers JSON: `acta/selfimprovement/types.py`, `pipeline.py`. Файл `memory/memory_manager.py` жив.
- **Root cause:** extract gate + fallback + selfimprovement не мигрированы.
- **Owned paths:**
  - `memory/memory_manager.py` (сузить до extract-only или удалить после миграции)
  - `main.py` (после PR-001/002)
  - `acta/selfimprovement/types.py`
  - `acta/selfimprovement/pipeline.py`
  - `tests/unit/memory/test_no_legacy_writes.py`
  - `tests/security/test_memory_trust_boundary.py`
  - `tests/offline/test_adversarial_network_escape.py` (перенаправить импорт extract)
- **Forbidden paths:** второй store. Не коммитить `memory/*.json` данные. Не ослаблять UNTRUSTED prefix / ASSISTANT_UNVERIFIED.
- **Depends on:** PR-001 (main.py), sequential с PR-002.
- **Implementation steps:**
  1. `rg "memory.memory_manager|from memory.memory_manager"` — полный список callers.
  2. Live path: только `acta.memory` (`format_store_for_prompt`, `commit_extracted_facts`). Extract: Router `text_ops` + commit SQLite (уже паттерн R4).
  3. selfimprovement → `acta.memory` API или явный adapter в `acta/selfimprovement`, не JSON file.
  4. Если модуль нужен тестам — оставить тонкий wrapper; иначе удалить и поправить тесты.
  5. Доказать AST/rg: production нет `update_memory` JSON write.
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/memory tests/security/test_memory_trust_boundary.py tests/offline/test_adversarial_network_escape.py -q
  ```
  `rg -n "update_memory" --glob '!tests/**' --glob '!docs/**'` — нет production JSON write.
- **DoD:** один store. Provenance не сломан.
- **Out of scope:** Ghost memory.

---

### PR-023 — or_client.py: удалить или tests-only инвариант

- **Priority:** P1
- **Evidence:** R10: production callers нет; файл + `tests/unit/actions/test_shell_exec_concurrency.py` импортируют модуль. `or_client.py` всё ещё OpenRouter client.
- **Root cause:** тесты держат модуль живым; риск регрессии нового caller.
- **Owned paths:**
  - `or_client.py` (удалить **или** оставить)
  - тесты, которые `import or_client`
  - `tests/architecture/test_or_client_unused.py` (новый инвариант)
- **Forbidden paths:** не возвращать production callers. `requirements*` не чистить вслепую.
- **Depends on:** PR-022 если extract ещё тянет имя.
- **Implementation steps:**
  1. `rg "or_client" --glob '*.py'` — только tests / docs.
  2. Предпочтительно: удалить `or_client.py`, перенести тест логгера на `providers.text_ops`.
  3. Если удаление слишком широко: architecture test — fail на `import or_client` вне `tests/**`.
- **Acceptance tests:**
  ```text
  python -m pytest tests/architecture tests/unit/actions/test_shell_exec_concurrency.py tests/unit/providers/test_text_ops.py -q
  ```
- **DoD:** нет скрытого второго AI client в production.
- **Out of scope:** OpenRouter provider внутри `providers/**` (канон).

---

### PR-024 — Automation fire → JobEngine

- **Priority:** P1
- **Evidence:** `acta/automation/engine.py:_dispatch` / `_run_execution` запускает thread + `_executor(job)` напрямую. Комментарий «Durable one-shot belongs in JobEngine», вызова `JobEngine` нет.
- **Root cause:** R5 inventory, wiring не сделан.
- **Owned paths:**
  - `acta/automation/engine.py`
  - `runtime/jobs.py` (если нужен job type `automation_fire`)
  - `tests/unit/automation/**`
- **Forbidden paths:** не удалять scheduler/cron. Не трогать proactive/workflow_learning (не JobEngine).
- **Depends on:** PR-004b, PR-020 (желательно общий enqueue API).
- **Implementation steps:**
  1. `_dispatch`: `job_engine.enqueue(type="automation_fire", idempotency_key=f"{job.id}:{scheduled_ts}")`.
  2. Исполнение — worker JobEngine, не голый thread как source of truth. Thread можно оставить как адаптер claim().
  3. Restart: не двойной fire (idempotency).
  4. JSON store остаётся для расписаний, не для execution durability.
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/automation tests/unit/runtime/test_jobs.py -q
  ```
  Новый: due job → enqueue → crash before complete → recover once.
- **DoD:** каждый fire — JobEngine job.
- **Out of scope:** DST rewrite (уже есть тесты).

---

### PR-025 — Staged ruff/mypy include agent/actions/memory

- **Priority:** P1
- **Evidence:** `pyproject.toml` exclude `actions/**`, `agent/**`, `or_client.py`, `memory/**`; mypy `ignore_errors` на те же. R10: не включать всё сразу.
- **Root cause:** долг спрятан от gate.
- **Owned paths:** `pyproject.toml` (один владелец), плюс **только тот пакет**, который уже зелёный (`ruff check agent/` exit 0 перед include).
- **Forbidden paths:** включить все три сразу. Расширить ignore_errors.
- **Depends on:** PR-003, PR-020, PR-022, PR-023, PR-026 (модули должны быть чистыми).
- **Implementation steps:**
  1. По одному пакету: починить ruff в `agent/` → добавить в include → commit логически может быть этот, если агент владеет и кодом и pyproject. Иначе: сначала код-карта, потом эта.
  2. mypy: снять `ignore_errors` только с пакета, который `mypy agent` проходит. Не раньше.
  3. `or_client` — только если файл ещё существует.
- **Acceptance tests:**
  ```text
  ruff check agent/   # или actions/ или memory/ — тот, что включили
  python -m ruff check .
  python -m mypy
  ```
- **DoD:** include расширен на 1 пакет за commit, gate зелёный.
- **Out of scope:** coverage omit (не блокер DoD).

---

### PR-026 — Structured logging, correlation_id, убрать production print()

- **Priority:** P1
- **Evidence:** `print(` на hot path: `runtime/lifecycle.py:40-79`, `memory/memory_manager.py`, `agent/error_handler.py`, `agent/executor.py`, `actions/web_search.py`, `actions/dev_agent.py`. SLON-031 leftover.
- **Root cause:** pre-observability.
- **Owned paths:** перечисленные production модули (разбить, если conflict: lifecycle vs PR-001). CLI `__main__.py` / `acta/selfimprovement/demo.py` можно оставить print.
- **Forbidden paths:** `basicConfig` в библиотечных модулях. Секреты в log format.
- **Depends on:** не параллелить `runtime/lifecycle.py` с PR-001.
- **Implementation steps:**
  1. `logging.getLogger(__name__)`; на control-plane события — `correlation_id` / `job_id` из `RuntimeEventBus` если есть.
  2. Заменить print в listed files. Не трогать тесты.
  3. Статический тест или rg: нет `print(` в `runtime/lifecycle.py` `agent/error_handler.py` `agent/executor.py` (после чистки).
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/runtime/test_events.py tests/unit/runtime/test_live_components.py -q
  rg -n "print\\(" runtime/lifecycle.py agent/error_handler.py agent/executor.py
  ```
  rg пустой.
- **DoD:** hot path без print.
- **Out of scope:** массовый ruff на actions (PR-025).

---

### PR-027 — Metrics на реальных call sites

- **Priority:** P1
- **Evidence:** `runtime/metrics.py` catalog есть; `inc()` вызывается только из `tests/unit/runtime/test_metrics.py`. R9 leftover.
- **Root cause:** catalog без instrumentation.
- **Owned paths:**
  - `runtime/metrics.py` (не ломать API)
  - `agent/runtime.py` (после PR-003)
  - `acta/tools/executor.py` — **только если** нужны tool_* counters; иначе stop + CR (executor hardened)
  - `gateway/**` — `gateway_auth_failures` / `gateway_connections`
  - `acta/memory/**` — memory_* 
  - `tests/unit/runtime/test_metrics.py` (assert вызов с call site, не только unit inc)
- **Forbidden paths:** секреты/текст пользователя в labels. Второй metrics lib.
- **Depends on:** PR-003 если правите `agent/runtime.py`.
- **Implementation steps:**
  1. `agent_requests_total` / `agent_loop_turns` / `agent_failures_total` в `AgentLoop.run`.
  2. `provider_*` в provider call (внутри `providers/` или loop).
  3. `tool_*` в executor **или** loop вокруг execute — не дублировать.
  4. Gateway auth fail → `gateway_auth_failures`.
  5. Snapshot без PII.
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/runtime/test_metrics.py tests/unit/agent/test_runtime.py tests/unit/gateway/test_gateway.py -q
  ```
  Тест: один loop.run → counters > 0.
- **DoD:** catalog используется в production path.
- **Out of scope:** Prometheus exporter.

---

### PR-028 — Секреты не в logs/exceptions

- **Priority:** P1
- **Evidence:** health/status sanitize есть. Риск: `logger.error(..., exc)` / `print` / Live errors с api_key. `validate_settings` отвергает secret-like keys (R9).
- **Root cause:** нет полного redaction на exception path.
- **Owned paths:**
  - `server/routes/_common.py` (`sanitize_body`)
  - `config/secrets.py`
  - места, где логируется `_get_api_key` / exception из providers
  - `tests/security/` redaction test (расширить)
- **Forbidden paths:** логировать raw key «для отладки».
- **Depends on:** PR-026 желательно.
- **Implementation steps:**
  1. Единый redact: `sk-`, `AIza`, `Bearer `, openrouter keys.
  2. Применить к listener logs, provider errors, onboard (не в UI plaintext).
  3. Тест: exception с fake key не содержит key в `str(record)`.
- **Acceptance tests:**
  ```text
  python -m pytest tests/unit/config/test_secrets.py tests/unit/server/routes/test_routes_health.py tests/security/test_adversarial_regression.py -q -k "secret or redact or sanitiz"
  ```
- **DoD:** нет ключа в типовых error paths.
- **Out of scope:** GitHub secrets admin.

---

### PR-029 — Bounded queues (если ещё unbounded)

- **Priority:** P1
- **Evidence:** VoiceBridge queues уже тестируются (`tests/unit/speech/voice/test_bounded_queues.py`). Event bus — bounded ring (R5). TaskQueue `_queue: list` без max. MCP output bounded (R8). Shell stdout truncate (R1).
- **Root cause:** TaskQueue/automation exec lists могут расти без bound.
- **Owned paths:** `agent/task_queue.py` (лучше слить с PR-020), `acta/automation/engine.py` history cap если нет.
- **Forbidden paths:** безлимитный replay на диск без политики.
- **Depends on:** PR-020 / PR-024.
- **Implementation steps:**
  1. Если PR-020 перевёл очередь в JobEngine sqlite — bound = DB + max in-flight. Карта может закрыться как «done via PR-020» с доказательством.
  2. Иначе: max queue depth, reject/fail-closed.
- **Acceptance tests:** тесты PR-020 + overflow unit.
- **DoD:** нет unbounded RAM list как production buffer.
- **Out of scope:** event history process-durable (не требуется software DoD).

---

### PR-030 — Lockfile / reproducible deps

- **Priority:** P2
- **Evidence:** `uv.lock` уже есть. R10: lockfiles не hand-edit. Не блокер software DoD, если CI ставит из `requirements*.txt`.
- **Карта:** не кодить, пока интегратор не попросит. Не редактировать lock вручную. Не добавлять vulnerability scanner в CI без отдельного решения (новое workflow dep).
- **Owned paths:** none unless requested.
- **Out of scope:** всё.

---

### PR-031 — Branch protection (не coding)

- **Priority:** P2  
- **Evidence:** `docs/audit/branch-protection-recommendation.md` уже написан. GitHub admin не менять.  
- **Карта:** не задача агента. Одна строка для интегратора: человек включает protection на `main` / `integration/main` и required `CI Release Gate`.

---

### Карты, которые не включать

| Тема | Почему |
| --- | --- |
| Ghost | Запрещено |
| ios/** / MarkRemote / pairing-on-device | iOS deferred; not a gate |
| Publish Desktop API | Stop condition |
| Push / merge integration/main | Запрещено |
| Cross-platform import smoke | Уже 2 passed (R10) |
| Health/readiness с нуля | Уже есть |
| ToolExecutor rewrite | R1 done |
| JobEngine с нуля | R5 done |
| Voice `voice_*` schema | R9 done |

---

## 4. Definition of Done — программа (software)

| # | Пункт | Status | Карта |
| --- | --- | --- | --- |
| 1 | Один AgentLoop reasoner; Live не второй loop | TODO | PR-001 |
| 2 | Provider-neutral voice; Core без Gemini Live import | TODO | PR-001 |
| 3 | local_only/offline/fully_local no-cloud включая Live | TODO | PR-002 |
| 4 | Wave 15 offline multi-turn + budget | TODO | PR-003 |
| 5 | E2E FS / path-traversal production path green | TODO | PR-004, PR-009 |
| 6 | E2E automation API | TODO | PR-004b |
| 7 | E2E server schemas | TODO | PR-004c |
| 8 | Playwright: 0 ERROR без Chromium; CI с Chromium гоняет | TODO | PR-005 |
| 9 | MCP streamable HTTP green | TODO | PR-006 |
| 10 | Listener pairing/status | TODO | PR-007 |
| 11 | Trash-only confirmed delete | TODO | PR-008 |
| 12 | `pytest tests` 0 failed / 0 errors (skip только environment) | TODO | PR-003…008 + PR-005 |
| 13 | `ruff check .` exit 0 | TODO | PR-010 |
| 14 | `ruff format --check .` exit 0 | TODO | PR-011 |
| 15 | `mypy` exit 0 без нового ignore_errors | TODO | PR-012 |
| 16 | `pytest tests --collect-only -q` exit 0 | DONE (R11/повтор) | — |
| 17 | TaskQueue не RAM source of truth | TODO | PR-020 |
| 18 | Thin UI widgets | TODO | PR-021 |
| 19 | Один memory path | TODO | PR-022 |
| 20 | or_client gone or tests-only invariant | TODO | PR-023 |
| 21 | Automation fire через JobEngine | TODO | PR-024 |
| 22 | Staged lint include leftover packages | TODO | PR-025 |
| 23 | Нет production print на hot path | TODO | PR-026 |
| 24 | Metrics на call sites | TODO | PR-027 |
| 25 | Секреты не в logs/exceptions | TODO | PR-028 |
| 26 | Bounded production queues | TODO | PR-029 / PR-020 |
| 27 | Health/readiness без секретов | DONE | R9 `server/routes/status.py` |
| 28 | Cross-platform import smoke | DONE | R10 |
| 29 | Unified ToolExecutor / SafetyPolicy | DONE | R1 |
| 30 | SDK только providers (+ onboard) | DONE | R3 |
| 31 | JobEngine существует | DONE | R5 |
| 32 | Gateway python boundary | DONE | R6 |
| 33 | Voice settings round-trip | DONE | R9 |
| 34 | iOS app / device pairing | N/A | iOS deferred by user; not a gate |
| 35 | Ghost | N/A | не реализовывать |
| 36 | Lockfile hand-edit | N/A | PR-030 не делать |
| 37 | Branch protection admin | N/A | PR-031 docs-only |

Вердикт `PRODUCTION_READY` только когда все TODO software-пункты DONE и полный gate:

```text
python -m pytest tests --collect-only -q
python -m pytest tests
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

все exit 0 (pytest: 0 failed, 0 errors; skipped только environment/hardware).

---

## 5. Suggested agent assignment

Одна волна = один владелец на файл. Не два агента на `main.py` / `test_e2e_chain.py` / `pyproject.toml`.

| Волна | Agent | Карты | Owned paths (кратко) | Порядок |
| --- | --- | --- | --- | --- |
| W1 | A | PR-001 | `main.py`, `runtime/tool_bridge.py`, `runtime/live_session.py`, `providers/gemini/live.py`, `tests/unit/main/**` | Первая |
| W1 | B | PR-003 | `agent/runtime.py`, `tests/integration/test_wave15_offline_agent.py` | Параллельно A |
| W1 | C | PR-009 | `acta/filesystem/security.py`, `acta/filesystem/operations.py`, `tests/security/test_adversarial_regression.py` | Параллельно A |
| W2 | A | PR-002 | `main.py`, `config/schema.py`, `tests/offline/**` | После PR-001 |
| W2 | C | PR-004 | `tests/e2e/test_e2e_chain.py` (FS/path классы), leftover security.py | После PR-009 |
| W2 | D | PR-008 | `actions/file_controller.py` | После PR-009; не operations.py если C ещё не сдал |
| W3 | E | PR-005 | `tests/integration/test_browser/**`, `runtime/browser/**`, `tests/security/test_beta_security_gates.py` | Параллельно |
| W3 | F | PR-006 | `acta/mcp/**`, `requirements-base.txt` или `requirements-dev.txt` | Единственный requirements |
| W3 | G | PR-007 | `server/listener.py`, `server/routes/status.py`, `observability/status.py` | Не `server/schemas.py` |
| W3 | H | PR-004b | `acta/automation/engine.py` | Не e2e file, если C ещё владеет — ждать или H только engine + свой тест |
| W3 | I | PR-004c | `server/schemas.py` | Один владелец schemas |
| W4 | A | PR-020, PR-029 | `agent/task_queue.py`, `runtime/jobs.py` | После W1 |
| W4 | B | PR-021 | `ui/**`, `runtime/commands.py` | После PR-001; не main.py |
| W4 | C | PR-022 | `memory/**`, `acta/selfimprovement/**`, `main.py` только после сдачи A (W2) | После PR-001/002 |
| W4 | D | PR-023 | `or_client.py`, architecture test | После PR-022 если extract ещё держит имя |
| W4 | H | PR-024 | `acta/automation/engine.py`; `runtime/jobs.py` только если A уже сдал PR-020 | После PR-004b + PR-020 |
| W4 | E | PR-026 | `runtime/lifecycle.py` (если A сдал Live), `agent/error_handler.py`, `agent/executor.py` | Не lifecycle пока A в W1 |
| W4 | F | PR-027 | `agent/runtime.py` после B (PR-003), `runtime/metrics.py`, gateway counters | После PR-003 |
| W4 | G | PR-028 | sanitize / secrets log paths | После PR-026 желательно |
| W5 | A | PR-010, PR-011 | текущий ruff include; не сужать exclude | После P0 pytest |
| W5 | A | PR-012 | `pyproject.toml` mypy overrides + `requirements-dev.txt` types | После PR-006 |
| W5 | A | PR-025 | `pyproject.toml` include одного пакета за commit | После чистых agent/actions/memory |

**Первая задача интегратора:** запустить Agent A на **PR-001**. Без одной reasoning plane вердикт не меняется, даже если pytest частично позеленеет.

Правило конфликтов:

- `main.py` — только Agent A до конца W2 (PR-001 затем PR-002). PR-022 ждёт.
- `tests/e2e/test_e2e_chain.py` — Agent C (PR-004). PR-004b/004c не правят этот файл в той же волне.
- `acta/filesystem/operations.py` — C (PR-009), затем D (PR-008) если нужен `trash()`.
- `agent/runtime.py` — B (PR-003), затем F (PR-027).
- `pyproject.toml` / `requirements*.txt` — не в W1–W4 кроме F (requirements для `mcp`). W5 — один владелец.
- `runtime/jobs.py` — A (PR-020), затем H (PR-024) sequential.

---

## 6. False-done ban

Копировать и соблюдать. Нарушение = карта не принята, даже если CI «зелёный».

1. **Disabled / skipped tests ради зелёного.** Запрещены `pytest.mark.skip`, `skipif(True)`, `xfail(strict=False)` на production-path тестах без environment-причины. Playwright skip — только `detect_runtime_availability() != READY`, и только локально; CI ставит Chromium и **обязан** гонять suite.
2. **Swallowed exceptions.** Запрещены `except Exception: pass` / голый `continue` на security, auth, tool, memory, job complete. Event sink isolation (R5) — уже есть; не расширять на executor/policy.
3. **CI scope shrink.** Запрещено сужать `pyproject.toml` `ruff.include` / `mypy.files`, добавлять `exclude`, `ignore_errors = true` на новые пакеты, `continue-on-error`, `|| true`, удалять job `pytest` / `ruff` / `mypy`.
4. **Fake green counts.** Не удалять тесты, не переименовывать nodeid чтобы «пропали» из списка, не skip на Wave 15 / path-traversal / pairing.
5. **Вторая архитектура.** Не создавать второй EventBus, JobEngine, memory store, AgentLoop, Router, ToolExecutor. Не копировать Gemini Live tool-loop «рядом».
6. **Ослабление security.** Не `shell=True`, не prefix `startswith` вместо `resolve+is_relative_to`, не auto-approve MCP CONFIRM, не allowlist `/` или весь `/var`, не `online=True` константа, не отключать pairing/TLS.
7. **Скрытый cloud.** Не fallback на cloud при `local_only` / `offline` / `fully_local`.
8. **Секреты.** Не коммитить `config/api_keys.json`, `memory/*.json` данные, ключи в тестах, ключи в логах.
9. **Mass format / mass fix вне карты.** Не `ruff check --fix .` и не `ruff format .` на весь репо, если это не PR-010/011.
10. **iOS / Ghost / publish.** Не трогать `ios/**`. Не реализовывать Ghost. Не публиковать Desktop API. Не push / merge в `integration/main`.
11. **Изобретённый PASS.** Строка `PASS` только с командой, exit code и counts. Absence of run = `NOT_RUN`.
12. **Executor re-do.** Не переписывать `acta/tools/executor.py` «на всякий случай». R1 закрыт.
13. **Hardware как оправдание software-fail.** Нет Chromium на ноутбуке ≠ право на ERROR (PR-005 skip). Нет Chromium ≠ skip на CI. Нет iPhone ≠ право оставить красный `test_path_traversal_blocked`.
14. **Shared-file race.** Два агента в одной волне на `main.py` / `ui/**` / `providers/contracts.py` / `providers/router.py` / `config/schema.py` / `server/schemas.py` / `pyproject.toml` / `requirements*.txt` — стоп.

---

## 7. Evidence appendix (команды этого ТЗ)

Ветка проверена: `agent/r0-r11-core-hardening` @ `5de598c`. Merge/push не делались.

```text
.venv/bin/python -m pytest tests --tb=no -q --no-header
# 17 failed, 2540 passed, 28 skipped, 33 errors, 78.56s, exit 1
```

17 FAILED и 33 ERROR разнесены по карточкам PR-003…PR-009 и PR-004b/c/005/006/007.

```text
.venv/bin/python -m ruff check . --statistics
# 512 errors, exit 1
.venv/bin/python -m mypy --no-error-summary
# 8 errors listed in PR-012, exit 2
```

`ruff format --check .` в этом прогоне не повторялся; принято число R11: **253 files**. Агент PR-011 обязан перезапустить команду и записать новый count.

Источники: `docs/audit/SLON_PRODUCTION_READINESS_REPORT.md`, `production-remediation-matrix.md`, `runtime-verification-matrix.md`, `wave-R0-report.md` … `wave-R11-report.md`, `AGENTS.md`, `pyproject.toml`.

**Конец ТЗ. Реализацию не начинать без назначения owned_paths интегратором.**
