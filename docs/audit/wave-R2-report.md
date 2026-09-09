# WAVE R2 — One Runtime (queued/text)

**WAVE:** R2  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  
**BRANCH:** `agent/r0-r11-core-hardening`

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-010 | `TaskQueue._run_task` | Constructed `AgentExecutor()` | Creates `AgentLoop` via injected factory or `create_queued_agent_loop()` → `RuntimeStack.create_agent_loop()` |
| SLON-011 | `execute_plan` | `AgentExecutor()` | Delegates to AgentLoop (`asyncio.run(loop.run(...))`) |
| SLON-026 | `tests/architecture/` | Missing | AST scan fails on production `AgentExecutor(` |
| SLON-038 | `AgentLoop` | +1 tool batch; infinite provider retry | `tool_call_count += len(tool_calls)`; `max_provider_retries` + backoff |

## REMOVED LEGACY

- Production `AgentExecutor(` constructions: **zero** (`rg AgentExecutor(` over agent/acta/main/server/gateway/sessions/runtime`).
- `AgentExecutor` **class remains** for explicit test imports and unused planner path. Planner files not deleted.

## TESTS

| Command | Result |
| --- | --- |
| `python -m pytest tests/architecture tests/agent/test_task_queue_agent_loop.py tests/unit/agent/test_runtime.py tests/agent/test_executor_registry_dispatch.py tests/unit/agent/test_executor.py tests/integration/test_wave15_offline_agent.py::test_offline_agent_legacy_execute_plan_intact tests/tools/test_legacy_adapters.py tests/unit/bridge/test_runtime_stack.py -q` | **57 passed** |

Pre-existing R0 reds unchanged: `test_offline_agent_multi_turn_tool_execution`, `test_offline_agent_budget_enforcement_turns`.

## SECURITY

Queued `agent_task` no longer plans via Gemini `AgentExecutor`. Fail-closed if Router/stack missing (AgentLoop without a working provider).

## MIGRATIONS

None. Persistent Job Engine **not** built (R5).

## KNOWN LIMITATIONS

- One AgentLoop still **PARTIAL** until R7 (SlonLive / `main.py` Gemini Live).
- `AgentExecutor.execute()` still exists and still uses planner/Gemini if someone calls it (tests only).
- Planner/error_handler SDK imports remain (R3).

## RUNTIME VERIFICATION STILL REQUIRED

Live queue + real provider; SlonLive exception.

## COMMITS

Filled after commit.
