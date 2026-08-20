# SLON — Master Technical Development Specification
## Post-Wave 15 Roadmap to OpenClaw-Class Feature Parity (iOS-Only External Access)

**Repository:** `alexghost82/Slon`  
**Baseline:** post-Wave 15 (`AgentLoop` over the Wave 14 unified tool/provider foundation)  
**Document purpose:** executable development specification for continuing Slon until it reaches OpenClaw-class platform capability, while deliberately excluding all messaging/channel integrations.  
**External interaction policy:** the **only remote user-facing connection surface is the Slon iOS application**. No Telegram, WhatsApp, Discord, Slack, Signal, Teams, WebChat, SMS, Matrix, or other channel subsystem is to be implemented.

---

# 0. Non-Negotiable Product Rules

1. Slon remains a personal AI platform, not a multi-channel bot framework.
2. The only remote client is the first-party **Slon iOS app**.
3. The desktop/local Slon runtime may retain its local desktop UI, CLI, and service processes.
4. The iOS app connects to a Slon Gateway using an authenticated encrypted protocol.
5. No generic `ChannelAdapter`, `ChannelRegistry`, or third-party messaging transport layer shall be created.
6. All future remote interaction primitives must be modeled as:
   - `Gateway`
   - `Session`
   - `Agent`
   - `Node`
   - `iOS Client`
7. Wave 14 canonical tool/runtime abstractions remain the source of truth.
8. Wave 15 `AgentLoop` remains the single iterative orchestration model.
9. No new parallel agent framework may be introduced beside the existing `agent/*`, `providers/*`, `mark/tools/*`, and `mark/safety/*` stack.
10. New platform features must be added incrementally with compatibility layers, tests, migration gates, and rollback paths.
11. Local-only mode must never silently route to cloud.
12. Security policy always overrides model preference and agent autonomy.
13. Any side-effecting tool must have explicit idempotency/retry semantics.
14. Any long-running execution must be resumable or explicitly non-resumable.
15. Every feature must be observable, testable, cancellable where technically possible, and recoverable after process restart.

---

# 1. Confirmed Baseline

Wave 14 established:
- canonical `ToolRegistry`;
- immutable `ToolSpec`, `ArtifactRef`, `ToolResult`;
- unified `ToolExecutor`;
- safety enforcement;
- provider-neutral tool exporters;
- local/cloud model routing;
- local-only/local-first/cloud-first/manual modes.

Wave 15 establishes:
- `AgentLoop`;
- `Observation`;
- `LoopBudget`;
- `LoopDetector`;
- steering and interruption;
- iterative `model -> tool -> observation -> model` execution;
- common loop for local and cloud providers.

The post-Wave 15 program must build upward from these contracts rather than replacing them.

---

# 2. Target Platform Architecture

```text
                         ┌───────────────────────────┐
                         │       SLON iOS APP        │
                         │ chat / voice / camera     │
                         │ screen / files / location │
                         │ approvals / control       │
                         └─────────────┬─────────────┘
                                       │
                             TLS WebSocket / HTTPS
                                       │
                         ┌─────────────▼─────────────┐
                         │       SLON GATEWAY        │
                         │ auth / pairing / routing  │
                         │ sessions / events / jobs  │
                         └─────────────┬─────────────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  │                    │                    │
            ┌─────▼─────┐       ┌─────▼─────┐       ┌─────▼─────┐
            │ Sessions  │       │  Agents   │       │   Nodes   │
            └─────┬─────┘       └─────┬─────┘       └─────┬─────┘
                  │                    │                    │
                  └──────────────┬─────┴──────────────┬────┘
                                 │                    │
                           ┌─────▼─────┐        ┌─────▼─────┐
                           │ AgentLoop │        │ Event Bus │
                           └─────┬─────┘        └─────┬─────┘
                                 │                    │
                   ┌─────────────┼──────────────┐     │
                   │             │              │     │
             ┌─────▼────┐  ┌────▼─────┐  ┌────▼────▼───┐
             │  Skills  │  │  Memory  │  │ Automation  │
             └─────┬────┘  └────┬─────┘  └─────────────┘
                   │             │
             ┌─────▼─────────────▼─────┐
             │      Tool Runtime       │
             │ Registry / Executor     │
             │ Search / Code Mode      │
             └───────────┬─────────────┘
                         │
              ┌──────────▼───────────┐
              │ Safety / Permissions │
              │ Sandbox / Approvals  │
              └──────────┬───────────┘
                         │
      ┌──────────────────┼───────────────────────────┐
      │                  │                           │
┌─────▼─────┐      ┌─────▼─────┐              ┌──────▼──────┐
│ Browser   │      │ Local OS  │              │ MCP/Plugins │
│ Runtime   │      │ Files/Exec│              │ Integrations│
└───────────┘      └───────────┘              └─────────────┘

                         MODEL ROUTER
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
       Cloud               Local             Compatible
 Gemini/OpenAI/...   Ollama/llama.cpp/   LM Studio/vLLM/
                     MLX/Apple models      OpenAI-compatible
```

---

# 3. Global Development Method

Every Wave must use the same execution model.

## 3.1 Lead Orchestrator responsibilities

The lead agent:
- reads `AGENTS.md`;
- resolves current commit and branch;
- creates task dependency graph;
- creates isolated worktrees;
- assigns owned paths;
- prevents conflicting file ownership;
- integrates completed task branches;
- runs integration tests;
- performs acceptance audit;
- produces a single Wave completion report.

## 3.2 Sub-agent contract

Every implementation sub-agent must:
1. work only in its assigned worktree;
2. change only `owned_paths`;
3. not merge/rebase/cherry-pick other agents;
4. not modify shared central contracts unless explicitly assigned;
5. run task-specific tests;
6. perform `git diff` review;
7. verify no secrets/generated files are committed;
8. produce one logical commit;
9. return:
   - commit SHA;
   - files changed;
   - tests executed;
   - test results;
   - remaining limitations;
   - integration notes.

## 3.3 Required gates per Wave

Every Wave requires:
- baseline test run;
- unit tests;
- integration tests;
- offline tests where applicable;
- security tests where applicable;
- migration compatibility test;
- cancellation test for long-running code;
- deterministic failure behavior;
- documentation update;
- final acceptance audit.

---

# 4. Shared File Ownership Rules

These paths are considered central/shared and may have only one owner within a Wave unless tasks are strictly sequential:

```text
main.py
agent/runtime.py
agent/observation.py
agent/executor.py
providers/contracts.py
providers/router.py
providers/routing.py
mark/tools/contracts.py
mark/tools/registry.py
mark/tools/executor.py
mark/safety/*
config/schema.py
config/secrets.py
ui.py
ios/**/App/*
pyproject.toml
requirements*.txt
```

---

# 5. Master Wave Roadmap

| Wave | Name | Core Result |
|---|---|---|
| 16 | Unified Runtime Completion | Legacy `main.py` execution removed; one canonical runtime |
| 17 | Native Provider Protocol | True provider-native tool-call/result transport |
| 18 | Realtime & Latency Engine | Low-latency voice/runtime with cancellation and telemetry |
| 19 | Session Engine | Persistent isolated sessions and transcripts |
| 20 | Slon Gateway | Always-on authenticated control plane |
| 21 | iOS Remote Client | First-class and only remote interaction surface |
| 22 | Plugin Runtime | Installable runtime extensions |
| 23 | Skills System | Dynamic instruction/capability packages |
| 24 | MCP Runtime | MCP client/server integration |
| 25 | Automation & Event Bus | Cron, heartbeat, triggers, jobs, internal events |
| 26 | Memory 2.0 | Working/session/episodic/semantic memory |
| 27 | Browser Runtime | Managed browser profiles and deterministic automation |
| 28 | Sandbox & Permissions | Constrained execution and approval system |
| 29 | Node Runtime | Device capability abstraction, with iOS as only remote node |
| 30 | Multi-Agent / Subagents / Swarm | Isolated specialist agents and concurrent orchestration |
| 31 | Unified Media Platform | Image/audio/video/document generation and processing |
| 32 | iOS Control Center | Administration, diagnostics, approvals, sessions, models |
| 33 | Local CLI & Operations | Local-only operational CLI |
| 34 | Tool Search / Code Mode / Goals / Workflows | Large-scale capability orchestration |
| 35 | Production Hardening | Recovery, updates, migrations, backups, diagnostics, release gates |

---

# WAVE 16 — Unified Runtime Completion

## Objective
Finish the Wave 14/15 migration and eliminate duplicate runtime execution paths.

## Target
```text
Gemini Live / Local Voice / Text
            ↓
        AgentLoop
            ↓
       ToolRegistry
            ↓
       ToolExecutor
            ↓
       SafetyPolicy
            ↓
       ToolResult
```

## Tasks

### W16-T01 — Runtime Inventory and Duplication Audit
**Agent:** A — Runtime Auditor  
**Owned paths:** documentation only  
**Deliverables:**
- map all tool declarations;
- map all dispatch paths;
- map all direct API-key reads;
- map all direct provider invocations;
- map all direct `actions/*` imports.

### W16-T02 — Gemini Tool Export Migration
**Agent:** B — Tool Export Engineer  
**Dependencies:** T01  
**Owned paths:**
- `main.py`
- `mark/tools/exporters/gemini.py`
- related tests

**Work:**
- replace manual `TOOL_DECLARATIONS`;
- generate Gemini function declarations from `ToolRegistry`;
- add schema parity tests.

### W16-T03 — Main Runtime Tool Dispatch Migration
**Agent:** C — Runtime Integration Engineer  
**Dependencies:** T02  
**Owned paths:**
- `main.py`
- runtime bridge module created for this purpose

**Work:**
- remove manual `if/elif` tool dispatcher;
- route all tool execution through canonical `ToolExecutor`;
- preserve UI callbacks and legacy `speak` adapters.

### W16-T04 — Secret Access Consolidation
**Agent:** D — Secrets Engineer  
**Owned paths:**
- `config/secrets.py`
- runtime modules that read API key files
- secret tests

**Work:**
- replace direct JSON reads with canonical secret resolver;
- retain migration-compatible fallback;
- guarantee no secret values are logged.

### W16-T05 — Runtime Composition Root
**Agent:** E — Architecture Engineer  
**Dependencies:** T02-T04  
**Owned paths:**
- `main.py`
- new runtime composition module

**Work:**
- turn `main.py` into composition/bootstrap layer;
- centralize construction of provider registry, tool registry, safety, AgentLoop, memory, audio, UI.

### W16-T06 — Wave Acceptance
**Agent:** QA-16  
**Dependencies:** all
**Required tests:**
- tool registry export;
- all legacy actions callable through ToolExecutor;
- Gemini Live regression;
- local provider regression;
- local-only no-cloud gate;
- no duplicate canonical tool schema.

## Definition of Done
- no manual canonical tool list remains in `main.py`;
- no independent tool dispatcher remains in `main.py`;
- all API key access passes through secret service;
- all runtime tool execution uses `ToolExecutor`;
- existing voice functionality remains operational.

---

# WAVE 17 — Native Provider Protocol

## Objective
Make AgentLoop truly provider-neutral while preserving native provider semantics.

## Tasks

### W17-T01 — Canonical Conversation Contracts
**Agent:** A — Contracts Engineer  
**Owned paths:** `providers/contracts.py`

Add message structures for:
- `UserMessage`;
- `AssistantMessage`;
- `AssistantToolCallMessage`;
- `ToolResultMessage`;
- `SystemMessage`;
- streaming deltas.

Required fields:
```text
tool_call_id
tool_name
arguments
result
error
artifacts
```

### W17-T02 — Gemini Adapter
**Agent:** B — Gemini Engineer  
**Dependencies:** T01  
Implement native `function_call` and `function_response`.

### W17-T03 — OpenAI-Compatible Adapter
**Agent:** C — OpenAI Protocol Engineer  
**Dependencies:** T01  
Implement native assistant `tool_calls` and `role=tool`.

### W17-T04 — Ollama/llama.cpp/LM Studio Adapter
**Agent:** D — Local Provider Engineer  
**Dependencies:** T01  
Implement capability-aware tool calling and explicit unsupported behavior.

### W17-T05 — Real ModelInfo Wiring
**Agent:** E — Router Engineer  
**Dependencies:** T01-T04  
Remove synthetic/default `ModelInfo`; pass selected model metadata into every request.

### W17-T06 — Provider Interface Cleanup
**Agent:** F — API Engineer  
Remove exception-driven signature detection such as `except TypeError -> call alternate signature`.
Introduce a single provider protocol.

### W17-T07 — Correlation Tests
**Agent:** QA-17  
Test:
- one tool call;
- many tool calls;
- duplicate IDs rejected;
- tool error;
- malformed arguments;
- provider mismatch;
- local model without tool support;
- tool_call_id preserved end-to-end.

## DoD
No provider result is represented as fake user text when native tool-result semantics exist.

---

# WAVE 18 — Realtime & Latency Engine

## Objective
Make Slon feel immediate during voice interaction and long-running tasks.

## Tasks

### W18-T01 — Latency Event Model
**Agent:** A — Observability Engineer
Add monotonic timestamps:
- input activity start/end;
- provider dispatch;
- provider first token/event;
- tool call arrival;
- tool start/end;
- observation return;
- first audio frame;
- turn complete.

### W18-T02 — Provider Timeout/Cancellation
**Agent:** B — Async Runtime Engineer
Use real async timeout/cancellation boundaries.

### W18-T03 — Audio Pipeline Backpressure
**Agent:** C — Audio Engineer
Implement:
- bounded queues;
- oldest-frame drop policy;
- interruption;
- echo suppression state;
- graceful stream reset.

### W18-T04 — Parallel-Safe Tool Calls
**Agent:** D — Tool Runtime Engineer
Extend ToolSpec metadata:
```text
read_only
idempotent
parallel_safe
side_effect_class
```
Only parallelize calls that are declared safe and independent.

### W18-T05 — Streaming Event Bus to UI
**Agent:** E — UI Runtime Engineer
Expose:
- listening;
- thinking;
- tool execution;
- speaking;
- progress;
- cancellation.

### W18-T06 — Performance Benchmark Suite
**Agent:** QA-18
Measure p50/p95 for:
- local text turn;
- cloud text turn;
- voice round trip;
- tool call;
- multi-tool turn.

---

# WAVE 19 — Session Engine

## Objective
Introduce durable isolated conversations and execution state.

## Required model

```python
Session:
    id
    created_at
    updated_at
    title
    agent_id
    model_policy
    workspace_id
    status
    transcript
    context_state
    memory_scope
    permissions_profile
    active_runs
```

## Tasks

### W19-T01 — Session Contracts
**Agent:** A — Data Contracts Engineer

### W19-T02 — Session Store
**Agent:** B — Persistence Engineer
Preferred initial store: SQLite.
Requirements:
- transactions;
- schema migrations;
- WAL mode where appropriate;
- corruption-safe backup.

### W19-T03 — Transcript Store
**Agent:** C — Conversation Engineer
Support:
- text;
- tool calls;
- tool results;
- artifacts;
- media references;
- streaming state.

### W19-T04 — Session Manager
**Agent:** D — Runtime Engineer
APIs:
```text
create
get
list
search
resume
close
archive
delete
append_event
```

### W19-T05 — Session-Agent Binding
**Agent:** E — Agent Runtime Engineer

### W19-T06 — Session Recovery
**Agent:** F — Recovery Engineer
Recover interrupted sessions after restart.

### W19-T07 — Tests
**Agent:** QA-19
Test isolation, persistence, crash restart, migrations, transcript ordering.

---

# WAVE 20 — Slon Gateway

## Objective
Create the central always-on control plane.

## Important
This Gateway is **not a channel gateway**.
It exists only for:
- iOS connectivity;
- sessions;
- agents;
- nodes;
- events;
- jobs;
- approvals;
- media;
- administration.

## Protocol
Preferred:
- TLS WebSocket for realtime duplex events;
- HTTPS for uploads/downloads/large artifacts;
- optional LAN discovery;
- optional Tailscale/tailnet compatibility.

## Tasks

### W20-T01 — Gateway Contracts
**Agent:** A — Protocol Architect

Define envelope:
```json
{
  "id": "...",
  "type": "...",
  "timestamp": "...",
  "session_id": "...",
  "request_id": "...",
  "payload": {}
}
```

### W20-T02 — Authentication and Pairing
**Agent:** B — Security Engineer
Implement:
- device identity;
- one-time pairing code;
- public-key pinning;
- rotating access tokens;
- revocation;
- trusted-device list.

### W20-T03 — WebSocket Runtime
**Agent:** C — Gateway Engineer
Implement:
- connection lifecycle;
- ping/pong;
- reconnect;
- replay cursor;
- event sequence IDs;
- backpressure.

### W20-T04 — Gateway Routing
**Agent:** D — Router Engineer
Routes:
```text
session.*
agent.*
node.*
automation.*
approval.*
media.*
system.*
```

### W20-T05 — Artifact Transfer API
**Agent:** E — File Transport Engineer
Signed short-lived transfers with size/type limits.

### W20-T06 — Gateway Persistence
**Agent:** F — State Engineer
Track device sessions, cursors, pending approvals, jobs.

### W20-T07 — Security Tests
**Agent:** QA-20
Replay, expired tokens, revoked device, malformed frames, oversized payloads, reconnect.

---

# WAVE 21 — Slon iOS Remote Client

## Objective
Make the iOS app the only remote user interface and remote node.

## Required capabilities

### Conversation
- text chat;
- realtime voice;
- transcript;
- streaming responses;
- tool progress;
- cancellation;
- follow-up guidance.

### Device capability exposure
- camera capture;
- photo selection;
- screen snapshot/recording where iOS permits;
- microphone;
- location;
- clipboard where permitted;
- files/document picker;
- notifications;
- optional health summaries only if explicitly enabled.

### Administration
- agent selection;
- model policy;
- session list;
- active jobs;
- approvals;
- node status;
- diagnostics.

## Tasks

### W21-T01 — iOS Gateway Client
**Agent:** A — Swift Networking Engineer

### W21-T02 — Pairing UX
**Agent:** B — iOS Security UX Engineer

### W21-T03 — Chat/Session UI
**Agent:** C — SwiftUI Engineer

### W21-T04 — Voice/Talk Mode
**Agent:** D — Audio/Realtime Engineer

### W21-T05 — Camera/Screen/Location Node
**Agent:** E — iOS Device Engineer

### W21-T06 — Offline Session Cache
**Agent:** F — iOS Persistence Engineer
Read-only cache of recent transcripts and pending UI state.

### W21-T07 — Push Notification Integration
**Agent:** G — Notification Engineer
Notifications are an iOS app transport, not a general messaging channel.

### W21-T08 — iOS Integration QA
**Agent:** QA-21

## DoD
No external messaging platform is required for any Slon remote workflow.

---

# WAVE 22 — Plugin Runtime

## Objective
Allow Slon to gain capabilities without modifying core code.

## Plugin model

```text
plugin.yaml
plugin.py
tools/
skills/
providers/
mcp/
hooks/
migrations/
tests/
```

## Manifest
Fields:
```text
id
name
version
api_version
entrypoint
permissions
capabilities
dependencies
platforms
config_schema
```

## Tasks
- T01 plugin contracts;
- T02 discovery/loader;
- T03 lifecycle install/enable/disable/uninstall;
- T04 permissions;
- T05 dependency resolution;
- T06 isolated plugin config;
- T07 plugin migrations;
- T08 signed/trusted plugin policy;
- T09 tests and sample plugin.

## Agents
A Contracts, B Loader, C Lifecycle, D Security, E Config, F QA.

## DoD
Core Slon does not need modification to install a well-formed new tool/plugin package.

---

# WAVE 23 — Skills System

## Objective
Add reusable instruction/procedure packages distinct from tools.

## Skill responsibilities
A Skill defines:
- when it should be used;
- procedure;
- constraints;
- expected tool usage;
- validation steps;
- references/templates.

## Files
```text
skills/<id>/SKILL.md
skills/<id>/skill.yaml
skills/<id>/templates/*
```

## Runtime
```text
SkillRegistry
SkillIndex
SkillResolver
SkillLoader
SkillContextInjector
```

## Tasks
- T01 contracts;
- T02 local discovery;
- T03 semantic resolver;
- T04 dependency/capability filter;
- T05 context budgeter;
- T06 per-agent skill policy;
- T07 iOS skill visibility/control;
- T08 tests.

## Important
Do not inject every Skill into every prompt. Resolve dynamically.

---

# WAVE 24 — MCP Runtime

## Objective
Support Model Context Protocol as an integration boundary.

## Components
```text
MCPClient
MCPServerManager
MCPToolAdapter
MCPResourceAdapter
MCPPromptAdapter
MCPAuth
MCPPermissionBridge
```

## Tasks
- stdio transport;
- HTTP/SSE/streamable transport as supported by selected MCP spec;
- server discovery/config;
- tool schema conversion into ToolRegistry;
- resource retrieval;
- prompt retrieval;
- authentication;
- timeout/reconnect;
- sandbox/security;
- server health monitoring;
- tests with offline mock MCP server.

## DoD
An MCP tool appears to AgentLoop exactly like a canonical Slon ToolSpec after policy filtering.

---

# WAVE 25 — Automation & Event Bus

## Objective
Add durable scheduled and event-driven execution.

## EventBus

Event examples:
```text
gateway.started
gateway.stopped
device.connected
device.disconnected
session.created
session.updated
agent.started
agent.completed
agent.failed
tool.started
tool.completed
tool.failed
automation.triggered
file.changed
provider.unavailable
approval.requested
approval.resolved
```

## Automation types
```text
one-shot
cron
interval
condition-watch
event-trigger
heartbeat
```

## Job model
```text
Job
Run
Trigger
Schedule
RetryPolicy
ExecutionPolicy
Result
```

## Tasks
- event contracts;
- in-process bus;
- durable event journal where needed;
- scheduler;
- cron parser;
- condition watcher;
- job store;
- retry/backoff;
- cancellation;
- iOS notifications/control;
- history;
- tests.

## Safety
Automations inherit explicit permission profiles. Scheduled execution must never silently gain elevated permissions.

---

# WAVE 26 — Memory 2.0

## Objective
Replace simple fact storage with layered memory.

## Layers
1. Working memory
2. Session memory
3. Episodic memory
4. Semantic memory
5. User profile/preferences
6. Project memory
7. Agent-specific memory

## Core APIs
```text
memory.store
memory.search
memory.get
memory.update
memory.forget
memory.consolidate
memory.export
memory.purge
```

## Components
- canonical MemoryRecord;
- metadata and provenance;
- embeddings interface;
- local embedding provider;
- vector index;
- lexical index;
- hybrid ranking;
- deduplication;
- consolidation;
- expiration;
- privacy classification;
- user-controlled deletion.

## Subagents
A Contracts, B Store, C Retrieval, D Embeddings, E Consolidation, F Privacy, G Migration, QA.

## Critical rule
Agent-generated guesses must never be stored as user facts without provenance/confidence policy.

---

# WAVE 27 — Managed Browser Runtime

## Objective
Move beyond desktop clicking into a dedicated deterministic browser service.

## Features
- isolated profiles;
- tab lifecycle;
- navigation;
- DOM access;
- accessibility tree;
- screenshots;
- PDF capture;
- downloads/uploads;
- cookies/storage;
- JavaScript execution policy;
- network wait conditions;
- click/type/select/drag;
- selector + semantic element targeting;
- browser session persistence;
- optional sandboxed browser instance.

## Tasks
- BrowserService;
- browser process manager;
- profile manager;
- deterministic element model;
- tool adapter;
- artifact handling;
- download quarantine;
- browser permissions;
- tests.

## Security
No unrestricted arbitrary JS in high-risk contexts without explicit policy.

---

# WAVE 28 — Sandbox & Permissions

## Objective
Constrain autonomous execution.

## Permission model

Profiles:
```text
minimal
read_only
standard
coding
automation
admin
```

Capabilities:
```text
filesystem.read
filesystem.write
filesystem.delete
process.exec
network.outbound
browser.control
device.camera
device.location
device.screen
secrets.read:<name>
automation.create
agent.spawn
plugin.install
mcp.connect
system.shutdown
```

## Execution classes
- host;
- sandbox;
- elevated.

## Tasks
- permission contracts;
- policy resolver;
- scope inheritance;
- filesystem scope;
- process scope;
- network scope;
- sandbox backend;
- approval requests;
- iOS approval UI;
- audit log;
- security test suite.

## DoD
Every tool invocation has an explainable effective permission decision.

---

# WAVE 29 — Node Runtime

## Objective
Create generic device capability execution without introducing generic messaging channels.

## Node model
A Node is a paired device exposing capabilities.

For this product plan, remote Node implementation is only:
- Slon iOS app.

Local host node may represent the desktop machine.

## Capabilities
```text
camera.capture
screen.snapshot
screen.record
location.get
microphone.stream
notification.show
files.pick
clipboard.read/write
device.info
```

## Components
```text
NodeRegistry
NodeCapability
NodeInvoke
NodeResult
NodeHeartbeat
NodeLease
```

## Tasks
- node contracts;
- iOS node adapter;
- host node adapter;
- invocation protocol;
- capability negotiation;
- heartbeat;
- stale-node handling;
- permission integration;
- tests.

---

# WAVE 30 — Multi-Agent / Subagents / Swarm

## Objective
Allow AgentLoop instances to collaborate safely.

## Agent definition
```text
AgentProfile:
    id
    role
    instructions
    model_policy
    tool_policy
    skill_policy
    permission_profile
    workspace
    memory_scope
    max_budget
```

## Core APIs
```text
agents.list
agents.spawn
agents.send
agents.status
agents.cancel
agents.wait
agents.yield
agents.result
```

## Required agent types
Not hard-coded implementations, but initial profiles:
- general;
- coding;
- research;
- browser;
- system;
- vision;
- automation.

## Swarm
Support:
- parallel independent tasks;
- fan-out/fan-in;
- reviewer agent;
- quorum/consensus optional;
- lead orchestrator;
- budget aggregation.

## Isolation
Each subagent gets:
- own session;
- own context;
- own budget;
- explicit tools;
- explicit workspace;
- explicit permissions.

## Tasks
A Contracts, B Spawn Runtime, C Messaging, D Swarm, E Budgeting, F Workspace Isolation, G Safety, QA.

---

# WAVE 31 — Unified Media Platform

## Objective
Create one media abstraction for all model and tool flows.

## Media types
```text
image
audio
video
document
generated_image
generated_video
generated_audio
```

## MediaObject
```text
id
mime_type
size
sha256
storage_ref
created_at
source
metadata
privacy_class
```

## Features
- upload/download;
- thumbnail;
- transcription;
- TTS;
- image analysis;
- image generation;
- video analysis;
- video generation where provider available;
- audio generation where provider available;
- document extraction;
- streaming playback;
- iOS presentation.

## Tasks
media contracts, storage, processing pipeline, provider adapters, lifecycle cleanup, iOS viewer/player, tests.

---

# WAVE 32 — iOS Control Center

## Objective
Replace the need for a browser Control UI with the first-party iOS app.

## Screens
1. Home / Slon status
2. Chat
3. Voice
4. Sessions
5. Agents
6. Active runs
7. Automations
8. Models/providers
9. Tools
10. Skills
11. Plugins
12. MCP servers
13. Memory
14. Nodes
15. Permissions
16. Pending approvals
17. Usage/latency
18. Logs/diagnostics
19. Backups
20. Settings

## Rule
No WebChat and no remotely exposed web administration UI are required for product parity. Remote administration is iOS-only.

## Tasks
split by SwiftUI feature modules, plus Gateway API expansion and UI integration testing.

---

# WAVE 33 — Local CLI & Operations

## Objective
Provide local administrator/diagnostic control without becoming another remote channel.

## CLI examples
```bash
slon status
slon doctor
slon gateway start
slon gateway stop
slon gateway restart
slon sessions list
slon agents list
slon models list
slon tools list
slon skills list
slon plugins list
slon mcp list
slon automation list
slon nodes list
slon logs
slon backup
slon restore
slon security audit
```

## Restrictions
CLI binds locally and is an operator surface, not a remote conversation channel.

## Tasks
CLI framework, command registry, diagnostics, structured output, completion, tests.

---

# WAVE 34 — Tool Search, Code Mode, Goals and Workflows

## Objective
Scale Slon from tens to hundreds/thousands of capabilities without giant prompts.

## 34.1 Tool Search
Instead of exposing every tool schema:
```text
query → capability index → selected tool subset → model
```

Components:
- ToolIndex;
- lexical/semantic retrieval;
- permission-aware filtering;
- provider capability filtering;
- ranking.

## 34.2 Code Mode
Allow an agent to compose multiple safe tools in a compact deterministic program.

Requirements:
- restricted runtime;
- no direct host access;
- callable approved tool facade only;
- budget;
- timeout;
- output/result capture.

## 34.3 Goals
Persistent:
```text
Goal
Plan
Milestone
Task
Progress
Status
```

APIs:
```text
goal.create
goal.get
goal.update
goal.pause
goal.resume
goal.complete
```

## 34.4 Workflows
Reusable deterministic flows:
```text
trigger
inputs
steps
conditions
parallel branches
approvals
outputs
```

## 34.5 Agent Task Suggestions
Agent may propose follow-up work that requires iOS confirmation before a new managed task starts.

## Subagents
A Tool Search, B Code Mode, C Goals, D Workflow Engine, E Approval UX, QA.

---

# WAVE 35 — Production Hardening

## Objective
Make Slon safe to operate continuously.

## 35.1 Process Supervision
- service lifecycle;
- crash restart;
- watchdog;
- graceful shutdown;
- startup health checks.

## 35.2 Persistent Recovery
Recover:
- sessions;
- running jobs;
- interrupted automations;
- pending approvals;
- Gateway cursors;
- agent state where resumable.

## 35.3 Backup/Restore
Backup:
- config;
- sessions;
- memory;
- skills;
- plugins;
- automation definitions;
- database;
- pairing metadata (encrypted).

Exclude:
- transient caches;
- model binaries unless explicitly selected.

## 35.4 Update System
- version manifest;
- signed release artifacts;
- staged update;
- migration preflight;
- rollback;
- release channels.

## 35.5 Database Migrations
Every persistent schema change requires forward migration and backup gate.

## 35.6 Diagnostics
`slon doctor` plus iOS Diagnostics:
- provider connectivity;
- model availability;
- microphone;
- audio output;
- Gateway;
- iOS pairing;
- database integrity;
- plugin health;
- MCP health;
- sandbox health;
- browser runtime;
- automation scheduler.

## 35.7 Security Audit
Automated checks:
- exposed ports;
- weak tokens;
- stale devices;
- excessive tool permissions;
- secrets in files/logs;
- unsafe plugin permissions;
- sandbox disabled where required;
- debug configuration in production.

## 35.8 Performance Regression Gates
Track:
- startup;
- memory;
- idle CPU;
- voice latency;
- first token;
- tool latency;
- database latency;
- Gateway RTT;
- iOS reconnect time.

## 35.9 Packaging
Platform-specific desktop packaging must preserve:
- secret store integration;
- local model configuration;
- audio dependencies;
- sandbox/browser dependencies.

---

# 6. Cross-Wave Sub-Agent Roles

The orchestrator should reuse these logical specialties, but each actual task still gets an isolated agent/worktree.

| Role | Responsibilities |
|---|---|
| Runtime Architect | AgentLoop, composition, lifecycle |
| Tool Runtime Engineer | ToolRegistry, ToolExecutor, schemas |
| Provider Engineer | Gemini/OpenAI/local model adapters |
| Async/Realtime Engineer | streaming, cancellation, backpressure |
| Gateway Engineer | WebSocket/HTTPS control plane |
| iOS Networking Engineer | pairing, reconnect, protocol |
| SwiftUI Engineer | iOS client surfaces |
| Security Engineer | permissions, sandbox, pairing, secrets |
| Persistence Engineer | SQLite, migrations, recovery |
| Memory Engineer | indexing, retrieval, consolidation |
| Plugin Engineer | loading/lifecycle/extensions |
| Skills Engineer | skill discovery/resolution |
| MCP Engineer | MCP transports/adapters |
| Browser Engineer | managed browser runtime |
| Automation Engineer | scheduler/events/jobs |
| Multi-Agent Engineer | subagents/swarm |
| Media Engineer | media storage/processing |
| Observability Engineer | metrics/tracing/diagnostics |
| QA Agent | acceptance/regression/security tests |
| Integration Lead | merge ordering and final audit |

---

# 7. Recommended Parallelization

## Stage A — Finish core
Sequential dependency:
```text
16 → 17 → 18
```

## Stage B — Platform control plane
After 18:
```text
19 Session Engine
       ↓
20 Gateway
       ↓
21 iOS Client
```

## Stage C — Extensibility
Can partially parallelize after 20:
```text
22 Plugins
23 Skills
24 MCP
25 Automation/EventBus
```

Constraints:
- Skills may depend on Plugin contracts if plugin-provided skills are supported.
- MCP tool adapters depend on canonical ToolRegistry.
- Automation depends on Sessions + Gateway persistence.

## Stage D — Intelligence and execution
After core platform:
```text
26 Memory
27 Browser
28 Sandbox
29 Nodes
```
Sandbox must be integrated before autonomous multi-agent execution.

## Stage E — Autonomy
```text
30 Multi-Agent
31 Media
32 iOS Control Center
33 CLI
34 Tool Search/Code Mode/Goals/Workflows
```

## Stage F — Production
```text
35
```

---

# 8. Hard Dependency Graph

```text
W14 Tool Runtime
      ↓
W15 AgentLoop
      ↓
W16 Unified Runtime
      ↓
W17 Provider Protocol
      ↓
W18 Realtime
      ↓
W19 Sessions
      ↓
W20 Gateway
      ↓
W21 iOS Client
      ├───────────────┐
      ↓               ↓
W22 Plugins        W25 Automation
      ↓               ↓
W23 Skills          W26 Memory
      ↓               │
W24 MCP              │
      └──────┬────────┘
             ↓
         W28 Sandbox
        ↙     ↓      ↘
   W27 Browser W29 Nodes W30 Multi-Agent
        \       |       /
         \      |      /
          └─────┼─────┘
                ↓
            W31 Media
                ↓
            W32 iOS Control
                ↓
            W33 CLI/Ops
                ↓
            W34 Advanced Orchestration
                ↓
            W35 Production
```

---

# 9. Global Test Matrix

Every release candidate must cover:

## Runtime
- multi-turn;
- tool error;
- timeout;
- cancellation;
- loop detection;
- provider failover;
- local-only isolation.

## Sessions
- isolation;
- resume;
- archive;
- crash recovery.

## Gateway
- auth;
- pairing;
- reconnect;
- sequence replay;
- token rotation;
- revocation.

## iOS
- offline cache;
- reconnect;
- voice interruption;
- media upload;
- camera permission denied;
- location permission denied;
- push notification;
- approval flow.

## Plugins
- install;
- invalid manifest;
- permission denial;
- migration failure;
- rollback.

## Skills
- discovery;
- ranking;
- context limit;
- incompatible capability.

## MCP
- disconnected server;
- malformed schema;
- tool timeout;
- auth failure.

## Automation
- DST/timezone;
- missed run;
- duplicate prevention;
- restart recovery;
- condition watch.

## Memory
- provenance;
- duplicate facts;
- deletion;
- cross-session retrieval;
- privacy filtering.

## Browser
- navigation;
- element targeting;
- download;
- sandbox;
- crash recovery.

## Security
- path traversal;
- command injection;
- prompt injection through tool content;
- secret exfiltration policy;
- revoked iOS device;
- replay attack;
- privilege escalation.

## Multi-agent
- workspace isolation;
- permission isolation;
- budget aggregation;
- cancellation propagation;
- swarm partial failure.

---

# 10. Migration Strategy

Never migrate all legacy systems simultaneously.

For each subsystem:

```text
legacy path
   ↓
compatibility adapter
   ↓
new canonical path
   ↓
shadow/dual-read test if appropriate
   ↓
feature gate
   ↓
new default
   ↓
legacy removal
```

Each removal requires:
- no live caller remains;
- regression test exists;
- rollback point exists.

---

# 11. Observability Standard

All major operations should expose structured events.

Minimum fields:
```text
timestamp
event_type
session_id
agent_id
run_id
tool_call_id
provider_id
model_id
duration_ms
status
error_code
```

Never log:
- API keys;
- passwords;
- auth tokens;
- full secret-bearing arguments;
- raw private documents unless debug mode is explicitly enabled.

Metrics:
```text
agent_turn_latency_ms
provider_first_token_ms
tool_latency_ms
voice_roundtrip_ms
gateway_rtt_ms
ios_reconnect_ms
job_success_rate
provider_error_rate
tool_error_rate
memory_retrieval_ms
browser_action_ms
```

---

# 12. Security Architecture

Trust boundaries:

```text
iOS App
   │ authenticated encrypted boundary
Gateway
   │ policy boundary
Agent Runtime
   │ capability boundary
ToolExecutor
   │ sandbox/elevation boundary
Host OS / Browser / Plugins / MCP
```

Principles:
- deny by default for high-risk capabilities;
- explicit scopes;
- short-lived approvals;
- audit trail;
- device revocation;
- per-agent permissions;
- per-session permissions where necessary;
- no model-provided field can lower risk;
- plugin/MCP content is untrusted input;
- remote iOS requests are authenticated user input, but tool outputs remain potentially untrusted.

---

# 13. iOS-Only Remote Access Rule

The following are explicitly **OUT OF SCOPE**:

```text
Telegram
WhatsApp
Discord
Slack
Signal
Teams
Matrix
SMS
iMessage bot integration
Google Chat
WebChat
IRC
LINE
Twitch
generic ChannelAdapter
generic ChannelRegistry
```

The following are allowed:
- local desktop UI;
- local CLI;
- Slon Gateway;
- Slon iOS app;
- iOS push notifications;
- local web components strictly internal to managed browser/runtime if not exposed as a conversational/user-access channel.

All remote user operations must pass through:
```text
Slon iOS App → Slon Gateway
```

---

# 14. Final Platform Definition of Done

Slon reaches the target state when all of the following are true:

- [ ] one canonical AgentLoop runtime;
- [ ] one canonical ToolRegistry/ToolExecutor;
- [ ] provider-native tool calling;
- [ ] real ModelInfo and capability routing;
- [ ] local/cloud model parity;
- [ ] session persistence;
- [ ] always-on Gateway;
- [ ] secure iOS pairing;
- [ ] iOS chat/voice/camera/screen/location/files;
- [ ] iOS approvals and administration;
- [ ] plugin runtime;
- [ ] skills runtime;
- [ ] MCP runtime;
- [ ] durable automation;
- [ ] event bus;
- [ ] layered memory;
- [ ] managed browser runtime;
- [ ] sandbox and scoped permissions;
- [ ] node capability runtime;
- [ ] subagents and swarm;
- [ ] unified media;
- [ ] Tool Search;
- [ ] Code Mode;
- [ ] persistent goals/plans;
- [ ] reusable workflows;
- [ ] local CLI/doctor;
- [ ] backup/restore;
- [ ] signed update/rollback;
- [ ] crash recovery;
- [ ] security audit;
- [ ] performance regression gates;
- [ ] no third-party messaging channels;
- [ ] iOS app is the only remote user-facing connection surface.

---

# 15. Master Orchestrator Prompt Template

Use this for every future Wave:

```text
You are the Lead Orchestrator for Slon Wave <N>.

Repository:
alexghost82/Slon

First read:
- AGENTS.md
- all previous Wave specifications
- current branch/commit
- the current implementation of every module touched by this Wave

Do not assume the specification is newer than the code.
Inspect first. If a requested feature already exists, validate it and move to the next missing requirement.

Your responsibilities:
1. Run baseline tests.
2. Build a dependency graph.
3. Split work into isolated implementation sub-agents.
4. Assign non-overlapping owned_paths.
5. Give each sub-agent explicit acceptance tests.
6. Integrate only completed logical commits.
7. Run Wave integration tests.
8. Run security/offline tests where relevant.
9. Audit the final implementation against every Definition of Done item.
10. Produce a final report.

Hard rules:
- Do not rewrite working systems unnecessarily.
- Do not create a parallel framework.
- Preserve ToolRegistry, ToolExecutor, SafetyPolicy, AgentLoop and provider routing as canonical foundations.
- Do not implement third-party messaging channels.
- The only remote user-facing transport is Slon iOS App ↔ Slon Gateway.
- Never commit secrets.
- Never hide failing tests.
- Never claim success without executing the relevant tests.
- Do not push/merge to main unless explicitly authorized.
```

---

# 16. Recommended Immediate Next Action

Do not start Wave 20+ yet.

Finish in order:

```text
Wave 15 acceptance
→ Wave 16 Unified Runtime
→ Wave 17 Native Provider Protocol
→ Wave 18 Realtime/Latency
→ Wave 19 Sessions
→ Wave 20 Gateway
→ Wave 21 iOS Remote Client
```

Only after Wave 21 should Slon begin large extensibility/autonomy work such as Plugins, Skills, MCP, Automation, Memory 2.0 and Multi-Agent.

This order prevents building a large platform on top of the remaining legacy execution path in `main.py`.
