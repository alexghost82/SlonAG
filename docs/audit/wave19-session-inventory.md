# Wave 19 Session Engine inventory

Audit base: `f6efa84`, branch `integration/main`, clean. Targeted baseline:
289 passed, 0 failed.

## Initial task matrix

| Task | Initial | Missing before Wave 19 |
| --- | --- | --- |
| W19-T01 | Not started | Canonical Session/Run/Transcript identities and model. |
| W19-T02 | Not started | Session persistence, transactions, migrations, WAL and backup. |
| W19-T03 | Not started | Durable text/tool/artifact/media/stream transcript. |
| W19-T04 | Not started | Exact manager lifecycle API. |
| W19-T05 | Partial prerequisite | ModelInfo and AgentLoop existed; no durable binding/history. |
| W19-T06 | Not started | Restart recovery of uncertain work. |
| W19-T07 | Not started | Isolation/persistence/crash/migration/order tests. |

## Distinct concepts

- Logical Session: durable conversation and execution state.
- Turn: one correlated user/provider/tool exchange.
- Run: one owned AgentLoop or realtime execution attempt.
- Provider session: ephemeral adapter/SDK connection.
- Connection generation: monotonic reconnect identity for diagnostics.
- Audio playback generation: stale PCM fence only.
- Tool call ID: provider correlation only.
- Long-term memory: separate semantic subsystem, not transcript history.
- API `conversation_id`: legacy/pass-through compatibility, not yet the Session API.

## Storage and recovery

The SQLite store uses a versioned schema, WAL, foreign keys, busy timeout,
transactional transcript ordering and workspace-scoped queries. Online backup
uses SQLite backup; corrupt sources are preserved and rejected. Startup recovery
marks active runs and streaming entries interrupted and performs no provider or
tool replay.

## Compatibility

`ChatMessage`, legacy tool adapters, AgentExecutor/execute_plan, JarvisLive,
authorize_tool and the generated_code denial sentinel remain unchanged. The
Session Engine wraps canonical AgentLoop and Gemini Live rather than replacing
their transports.
