# ADR 0002: Durable logical session boundary

- Status: Accepted
- Date: 2026-08-20
- Wave: 19

## Context

AgentLoop kept typed messages only for one invocation. Gemini Live connections,
audio playback generations, API conversation IDs and long-term memory each had a
different lifecycle and none was a durable isolated conversation.

## Decision

A logical `Session` is the durable conversation boundary. It owns configured
model policy, workspace/permission scope, ordered transcript and execution runs.
SQLite is the initial store, using transactional ordering, schema migrations,
foreign keys, WAL and validated backups.

Provider connections and audio generations remain ephemeral resources. A
reconnect increments connection generation while preserving session identity.
Turn, run and tool-call IDs remain distinct. Recovery marks active runs and open
streams interrupted and never automatically replays tools, approvals or side
effects. Session transcript is separate from semantic long-term memory.

AgentLoop receives history and a message observer through provider-neutral
contracts; it does not import the Session Store. Gemini Live persists transcript
at semantic turn boundaries off the audio callback path.

## Consequences

- Multiple sessions have isolated history, cancellation and configured models.
- A process restart can resume committed conversation state safely.
- SQLite writes add work at text/turn boundaries, not per PCM frame.
- Provider-native session resumption remains an optional transport optimization,
  not the source of truth.

## Fitness functions

- Workspace-scoped queries cannot read another workspace.
- Transcript sequence allocation is transactional and unique per session.
- Tool call/result correlation survives reload.
- Close is idempotent and revokes active run cancellation authority.
- Crash recovery interrupts uncertain work without handler replay.
- Runtime events keep stable session identity across connection generations.

## Rollback

The store and binding are additive. Composition can omit SessionManager and the
existing stateless AgentLoop/Gemini adapters continue to operate. No legacy
memory or provider database is migrated or destroyed.

