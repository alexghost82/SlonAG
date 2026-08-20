# Wave 16 runtime inventory

Baseline: `03cd117` on `integration/main`.

This inventory records production and compatibility paths used to complete
W16-T01. The canonical definitions are `ToolSpec` objects returned by
`mark.tools.builtin.build_builtin_registry()`.

## Active paths

| Concern | Runtime path |
|---|---|
| Gemini Live declarations | `SlonLive.tool_registry` → `export_gemini_tools()` → `LiveConnectConfig.tools` |
| Gemini Live dispatch | `receive_live_session()` → `SlonLive._execute_tool()` → `LiveToolBridge` → `ToolExecutor` → `SafetyPolicy` |
| Provider-neutral loop | `AgentLoop` → injected `ToolExecutor` → canonical `ToolResult`/`Observation` |
| Queued legacy goals | `TaskQueue` → `AgentExecutor` → `ToolExecutor` |
| Planner catalog | `render_planner_tool_catalog()` over an injected or builtin `ToolRegistry` |
| Secrets | `config.secrets.get_secret()` / `set_secret()`; OS store with controlled file fallback |

Gemini Live is a native bidirectional transport boundary. Its function-call
and function-response conversion remains in `main.py`/`runtime/live_session.py`,
while authorization and execution are canonical. The current `ChatProvider`
contract does not model bidirectional audio sessions; changing that contract is
Wave 17 work, not a Wave 16 compatibility deletion.

## Compatibility paths

| Component | Classification | Removal condition |
|---|---|---|
| `mark.tools.legacy.adapters` | Required | Keep until all `actions/*` handlers have native canonical signatures. |
| `AgentExecutor` / `execute_plan` | Required by `TaskQueue` | Replace only after queued goals use `AgentLoop` through an explicit migration. |
| `AgentLoop` default executor construction | Compatibility fallback | Remove after every caller injects the composition-owned executor. |
| `JarvisLive = SlonLive` | Naming compatibility | Remove only after external/package callers no longer import `JarvisLive`. |
| `mark.bridge.authorize_tool` | Fail-closed compatibility facade | Remove after downstream callers migrate to `ToolExecutor`; no production caller exists in this repository. |
| Safety-only `generated_code` | Denied sentinel, not a declared tool | Keep denial tests while legacy error recovery can still return the sentinel. |

## Provider adapter boundaries

Direct external provider calls are confined to provider adapters, except for
Gemini Live connection setup in `SlonLive.run()`. OpenAI-compatible and local
providers receive canonical `ChatRequest` values through `Router`. Native
multi-turn provider serialization and streaming tool-call parity belong to
Wave 17.

## Removed duplication

- `main.py` contains no hand-written tool schema or per-tool dispatcher.
- Live declarations and Live execution now use the same injected registry.
- UI and `main.py` reuse one `RuntimeStack` instead of constructing two stacks.
- `RuntimeStack` owns the canonical registry, executor, safety policy, router,
  and the factory that creates `AgentLoop` with those dependencies.
- Production code does not read or write `config/api_keys.json` directly.

## Rollback

Each Wave 16 commit is independently revertible. The compatibility adapters
remain available, so rollback does not require restoring manual schemas,
direct action dispatch, or direct secret-file access.
