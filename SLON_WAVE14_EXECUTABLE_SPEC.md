# Wave 14 — Unified Tool Runtime + First-Class Local LLM Support

## Slon Agent — Executable Development Specification

**Repository:** `alexghost82/Slon`  
**Scope:** Wave 14  
**Primary objective:** consolidate all Slon tool execution into one provider-agnostic runtime and make local LLMs first-class participants in the same architecture as Gemini, OpenAI and OpenRouter.

---

# 1. Mission

Wave 14 must eliminate duplicated tool definitions and duplicated tool execution paths across Slon.

After this wave:

- there is exactly one canonical `ToolRegistry`;
- every built-in tool has one canonical `ToolSpec`;
- every execution produces a normalized `ToolResult`;
- all safety checks run through one execution pipeline;
- Gemini, OpenAI, OpenRouter, Ollama and llama.cpp receive tool definitions derived from the same registry;
- provider-specific tool calls are normalized into one internal `ToolCall`;
- local models are first-class providers;
- local-only mode never falls back to cloud;
- local-first mode prefers a capable local model to reduce cost;
- existing legacy actions remain usable through adapters;
- existing Slon behavior remains operational during the migration.

This wave is **runtime consolidation**, not a rewrite of all legacy actions and not yet the new multi-turn AgentLoop. The full iterative `model -> tool -> observation -> model` orchestration belongs to Wave 15.

---

# 2. Existing Architecture That Must Be Reused

The implementation must build on existing Slon components rather than introducing parallel frameworks.

Existing provider layer already includes:

- Gemini;
- OpenAI;
- OpenRouter;
- Ollama;
- llama.cpp;
- OpenAI-compatible local runtimes;
- provider registry;
- capability model;
- streaming;
- privacy/network restrictions.

Existing local provider stack:

```text
providers/local/
    __init__.py
    common.py
    endpoint.py
    http.py
    llama_cpp.py
    ollama.py
    openai_compatible.py
```

Existing safety stack:

```text
mark/safety/
```

Existing legacy tool implementations:

```text
actions/
```

Existing execution/planning stack:

```text
agent/planner.py
agent/executor.py
agent/task_queue.py
```

Existing runtime bridge:

```text
mark/runtime/
mark/bridge/
```

Do **not** introduce a second tool framework.

---

# 3. Mandatory Architectural Rules

These rules apply to every agent working on Wave 14.

1. `ToolRegistry` is the only source of truth for tool metadata.
2. Tool schemas must not be duplicated in `main.py`, planner prompts, provider adapters or executors.
3. Provider adapters may transform a canonical schema into provider-specific wire format, but they may not own canonical tool definitions.
4. Local LLM support is mandatory.
5. Local models and cloud models use the same internal `ToolDefinition`, `ToolCall`, `ToolSpec` and `ToolResult` abstractions.
6. Unknown local model capability means unsupported, never assumed supported.
7. Local-only mode must never silently fall back to cloud.
8. Safety runs before tool execution.
9. Model-provided fields such as `confirmed=true`, `risk=READ`, `skip_confirm=true` must never override safety policy.
10. Legacy `actions/*` are wrapped, not rewritten, unless a task explicitly requires otherwise.
11. Existing public APIs should remain compatible unless the task explicitly changes them.
12. No Internet dependency in unit tests.
13. Do not introduce:
   - LangChain;
   - LangGraph;
   - AutoGen;
   - CrewAI;
   - Redis;
   - Celery;
   - RabbitMQ;
   - FastAPI as a replacement framework;
   - another scheduler;
   - another provider registry.
14. No speculative redesign outside the assigned task.
15. Keep files small and responsibility-focused.
16. Add tests for every new behavior.
17. New runtime code should be typed and mypy-friendly.
18. Never claim a tool action succeeded unless execution produced `ToolResult.ok == True`.

---

# 4. Target Runtime Flow

```text
                 ┌──────────────────────┐
                 │   Canonical Tools    │
                 │     ToolRegistry     │
                 └──────────┬───────────┘
                            │
             ┌──────────────┼───────────────┐
             │              │               │
        Gemini Export   OpenAI Export   Ollama/OpenAI
             │              │          Compatible Export
             └──────────────┼───────────────┘
                            │
                     Selected Model
                            │
                        ToolCall
                            │
                            ▼
                 ┌──────────────────────┐
                 │    ToolExecutor      │
                 │ lookup               │
                 │ validate             │
                 │ safety               │
                 │ approval             │
                 │ execute              │
                 │ normalize            │
                 └──────────┬───────────┘
                            │
                       ToolResult
```

---

# 5. Local LLM Policy

Slon must expose four routing modes:

```text
manual
local_first
local_only
cloud_first
```

## `local_first`

Selection order:

```text
required role
    ↓
required capabilities
    ↓
privacy/network constraints
    ↓
available compatible local models?
    ├─ yes -> local model
    └─ no  -> cloud only if allowed
```

## `local_only`

Only local providers may be selected.

Allowed provider IDs include:

```text
local
ollama
llama_cpp
```

If no local model can satisfy the required capabilities, return a clear `CapabilityError`.

Never silently switch to:

```text
gemini
openai
openrouter
```

## `cloud_first`

Use the configured cloud model first, then permitted fallback policy.

## `manual`

Use exactly the configured provider/model.

---

# 6. Required Capability Model

Existing `ModelInfo` must remain the canonical model descriptor.

Capabilities relevant to Wave 14:

```text
text
streaming
structured_output
tool_calling
vision
audio_input
audio_output
embeddings
context_length
local
cost
ram_gb
vram_gb
```

Hard rule:

```text
capability requirements
>
privacy restrictions
>
availability
>
user routing preference
>
cost preference
```

Cost is important, but never more important than correctness or privacy constraints.

---

# 7. Work Breakdown

---

## W14-T01 — Tool Contracts

**Owner:** Agent A  
**Dependencies:** none  
**Parallelizable:** yes

### Create

```text
mark/tools/__init__.py
mark/tools/contracts.py
mark/tools/errors.py
tests/tools/test_contracts.py
```

### Implement `ToolSpec`

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object] | None
    handler: Callable[..., object]

    risk: RiskLevel
    timeout_seconds: float = 30.0

    idempotent: bool = False
    cancellable: bool = False

    capabilities: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()
```

### Implement `ArtifactRef`

```python
@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    path: str | None = None
    uri: str | None = None
    mime_type: str | None = None
```

### Implement `ToolResult`

```python
@dataclass(frozen=True)
class ToolResult:
    ok: bool
    code: str
    message: str = ""
    data: object | None = None

    artifacts: tuple[ArtifactRef, ...] = ()
    warnings: tuple[str, ...] = ()

    started_at: float | None = None
    finished_at: float | None = None

    retryable: bool = False
```

### Validation

`ToolSpec.name` must match:

```regex
^[a-z0-9_.-]+$
```

Reject:

- empty name;
- invalid name;
- timeout <= 0;
- missing/non-callable handler.

### Acceptance tests

- valid ToolSpec;
- invalid names;
- invalid timeout;
- immutable result;
- artifact representation.

### Definition of Done

```bash
pytest tests/tools/test_contracts.py
```

passes.

---

## W14-T02 — ToolRegistry

**Owner:** Agent B  
**Dependencies:** W14-T01

### Create

```text
mark/tools/registry.py
tests/tools/test_registry.py
```

### API

```python
class ToolRegistry:
    def register(self, spec: ToolSpec) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> ToolSpec: ...
    def contains(self, name: str) -> bool: ...
    def list(self) -> tuple[ToolSpec, ...]: ...
    def names(self) -> tuple[str, ...]: ...

    def select(
        self,
        *,
        capabilities: set[str] | None = None,
        scopes: set[str] | None = None,
    ) -> tuple[ToolSpec, ...]: ...
```

### Errors

```text
DuplicateToolError
UnknownToolError
```

### Constraints

Registry must not import:

```text
Gemini
OpenAI
Ollama
llama.cpp
PyQt6
main.py
server UI code
```

### Definition of Done

Tests cover:

- register;
- duplicate;
- lookup;
- unknown lookup;
- unregister;
- deterministic ordering;
- capability filter;
- scope filter.

---

## W14-T03 — Unified ToolExecutor

**Owner:** Agent C  
**Dependencies:** W14-T01, W14-T02

### Create

```text
mark/tools/executor.py
tests/tools/test_executor.py
```

### Constructor

```python
class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        safety_policy: SafetyPolicy,
        confirmer: Callable[..., bool] | None = None,
    ) -> None:
        ...
```

### Execution API

```python
def execute(
    self,
    name: str,
    arguments: Mapping[str, object],
    *,
    source: UntrustedSource,
    intent: str = "",
) -> ToolResult:
    ...
```

### Required execution sequence

```text
lookup ToolSpec
    ↓
validate arguments
    ↓
authorize via safety
    ↓
request confirmation if required
    ↓
execute handler
    ↓
normalize legacy/native result
    ↓
return ToolResult
```

### Mandatory behavior

- denied tool never invokes handler;
- confirmation happens before side effect;
- model cannot lower risk;
- unknown tool produces normalized error;
- handler exceptions are normalized;
- timeout handled centrally;
- transient failures may set `retryable=True`.

### Do not

Do not create a second safety policy system.

---

## W14-T04 — Legacy Action Adapters

**Owner:** Agent D  
**Dependencies:** W14-T01

### Create

```text
mark/tools/legacy/__init__.py
mark/tools/legacy/adapters.py
tests/tools/test_legacy_adapters.py
```

### Wrap existing tools

Initial migration set:

```text
open_app
web_search
browser_control
file_controller
desktop_control
computer_control
computer_settings
screen_process
reminder
weather_report
flight_finder
youtube_video
file_processor
game_updater
send_message
code_helper
dev_agent
agent_task
```

### Rule

Do not rewrite action internals.

Example:

```python
def file_controller_handler(
    args: Mapping[str, object],
) -> ToolResult:
    result = file_controller(parameters=dict(args), player=None)
    return normalize_legacy_result(result)
```

### Add one shared legacy result normalizer

It should convert:

```text
None
string
dict
ToolResult
```

into `ToolResult`.

---

## W14-T05 — Canonical Built-in Tool Registry

**Owner:** Agent E  
**Dependencies:** W14-T02, W14-T04

### Create

```text
mark/tools/builtin.py
tests/tools/test_builtin_registry.py
```

### API

```python
def build_builtin_registry() -> ToolRegistry:
    ...
```

### Requirement

Every built-in tool is registered exactly once here or through clearly separated registration modules imported from here.

No canonical schema may remain in planner/executor/main.

---

## W14-T06 — Provider Tool Schema Exporters

**Owner:** Agent F  
**Dependencies:** W14-T01, W14-T02

### Create

```text
mark/tools/exporters/__init__.py
mark/tools/exporters/openai.py
mark/tools/exporters/gemini.py
tests/tools/test_exporters.py
```

### OpenAI exporter

```python
def export_openai_tools(
    specs: Sequence[ToolSpec],
) -> list[dict[str, object]]:
    ...
```

Output shape:

```json
{
  "type": "function",
  "function": {
    "name": "file_controller",
    "description": "...",
    "parameters": {}
  }
}
```

### Gemini exporter

Implement provider-specific conversion from the same `ToolSpec`.

### Forbidden

Do not add:

```text
ToolSpec.openai_schema
ToolSpec.gemini_schema
ToolSpec.ollama_schema
```

---

## W14-T07 — Provider-Agnostic Tool Calling Contracts

**Owner:** Agent G  
**Dependencies:** W14-T01

### Modify

```text
providers/contracts.py
```

### Add

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, object]
```

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, object]
```

### Extend `ChatRequest`

Add:

```python
tools: Sequence[ToolDefinition] = ()
tool_choice: str | None = None
```

### Extend `ChatResponse`

Add:

```python
tool_calls: tuple[ToolCall, ...] = ()
```

### Extend `ChatEvent`

Support event types:

```text
delta
tool_call
done
```

Add:

```python
tool_call: ToolCall | None = None
```

### Backward compatibility

Existing callers that only use text must continue to work without modification.

---

## W14-T08 — Ollama Tool Calling

**Owner:** Agent H  
**Dependencies:** W14-T07

### Modify

```text
providers/local/common.py
providers/local/ollama.py
tests/providers/local/test_ollama_tools.py
```

### Request behavior

If `request.tools` is non-empty, include Ollama-native tool schema.

Conceptual wire format:

```json
{
  "model": "...",
  "messages": [],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "...",
        "description": "...",
        "parameters": {}
      }
    }
  ]
}
```

### Response behavior

Parse:

```text
message.tool_calls
```

into canonical `ToolCall`.

### Streaming

Support tool calls in stream only if protocol response exposes them reliably.

If model/runtime does not support streamed tool calls, use explicit non-stream path rather than faking support.

---

## W14-T09 — llama.cpp / OpenAI-Compatible Tool Calling

**Owner:** Agent I  
**Dependencies:** W14-T07

### Modify

```text
providers/local/common.py
providers/local/openai_compatible.py
providers/local/llama_cpp.py
tests/providers/local/test_openai_compatible_tools.py
```

### Support request fields

```text
tools
tool_choice
```

### Support response fields

Non-stream:

```text
choices[].message.tool_calls
```

Stream:

```text
choices[].delta.tool_calls
```

### Critical constraint

Do not infer model tool capability merely from API protocol support.

---

## W14-T10 — Local Model Capability Discovery

**Owner:** Agent J  
**Dependencies:** W14-T08, W14-T09

### Create

```text
providers/local/capabilities.py
tests/providers/local/test_capabilities.py
```

### Data model

```python
@dataclass(frozen=True)
class LocalModelCapabilities:
    text: bool = True
    streaming: bool = True
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    context_length: int = 0
```

### Resolver

```python
def resolve_local_capabilities(
    provider_id: str,
    model_id: str,
    runtime_metadata: Mapping[str, object] | None,
    overrides: Mapping[str, object] | None = None,
) -> LocalModelCapabilities:
    ...
```

### Resolution priority

```text
runtime-reported metadata
    ↓
explicit user configuration
    ↓
known model overrides
    ↓
conservative defaults
```

Unknown:

```text
tool_calling = False
vision = False
structured_output = False
```

Never optimistic defaulting.

---

## W14-T11 — Local Model Configuration

**Owner:** Agent K  
**Dependencies:** W14-T10

### Extend existing config schema

Conceptual configuration:

```yaml
local_models:
  default_provider: ollama

  ollama:
    enabled: true
    base_url: http://127.0.0.1:11434

  llama_cpp:
    enabled: true
    base_url: http://127.0.0.1:8080

  preferred:
    chat: ""
    planning: ""
    code: ""
    utility: ""

  overrides:
    my-model:
      tool_calling: true
      structured_output: true
      context_length: 32768
```

### Requirements

- fully offline startup supported;
- loopback defaults preserved;
- no forced cloud discovery;
- invalid override rejected early.

---

## W14-T12 — Routing Policy

**Owner:** Agent L  
**Dependencies:** W14-T10, W14-T11

### Extend provider routing

Modes:

```text
manual
local_first
local_only
cloud_first
```

### Local-first selection

Filter by hard constraints first:

```text
provider available
model available
privacy allowed
network allowed
role supported
required capabilities supported
```

Then apply preference.

### Local-only guarantee

If no local model satisfies the required capabilities:

```text
raise CapabilityError
```

No cloud provider is invoked.

### Tests

Must explicitly prove that `offline` and `fully_local` never escape to cloud.

---

## W14-T13 — Cost-Aware Model Scoring

**Owner:** Agent M  
**Dependencies:** W14-T12

### Create or extend routing policy scorer

Conceptual API:

```python
def score_model(
    model: ModelInfo,
    *,
    required_capabilities: frozenset[str],
    prefer_local: bool,
    privacy_profile: str,
    availability: bool,
) -> float:
    ...
```

### Ordering

Hard constraints are not scores.

First eliminate invalid models.

Only then score:

```text
local preference
estimated cost
latency hint
user role preference
```

### Goal

Prefer local models for cost reduction when they are technically appropriate.

---

## W14-T14 — Tool Capability Gate

**Owner:** Agent N  
**Dependencies:** W14-T07

### Modify

```text
providers/capabilities.py
tests/providers/test_capabilities.py
```

### Add generalized capability check

```python
def require_capabilities(
    model: ModelInfo,
    required: Collection[str],
) -> None:
    ...
```

### Required behavior

Ordinary text chat:

```text
requires: text
```

Agent turn exposing tools:

```text
requires: text + tool_calling
```

A model with:

```text
text=True
tool_calling=False
```

may chat, but must not receive tool definitions.

---

## W14-T15 — Planner Tool Catalog Consolidation

**Owner:** Agent O  
**Dependencies:** W14-T05

### Modify

```text
agent/planner.py
tests/agent/test_planner_tool_catalog.py
```

### Remove

Hard-coded canonical tool parameter catalog from `PLANNER_PROMPT`.

### Temporary compatibility helper

```python
def render_planner_tool_catalog(
    registry: ToolRegistry,
) -> str:
    ...
```

### Scope boundary

Do not redesign planner loop here.

Wave 15 replaces the execution model.

---

## W14-T16 — Executor Dispatch Consolidation

**Owner:** Agent P  
**Dependencies:** W14-T03, W14-T05

### Modify

```text
agent/executor.py
tests/agent/test_executor_registry_dispatch.py
```

### Remove

Manual `_dispatch_tool()` chain.

### Replace with

```python
self.tool_executor.execute(...)
```

### Requirement

Existing `AgentExecutor.execute()` remains operational.

This is a compatibility migration, not the Wave 15 orchestration rewrite.

---

## W14-T17 — `main.py` ToolRegistry Integration

**Owner:** Agent Q  
**Dependencies:** W14-T05, W14-T06, W14-T08, W14-T09

### Modify

```text
main.py
```

### Startup

Build once:

```python
registry = build_builtin_registry()
```

### Provider preparation

Use exporter according to active provider.

Conceptually:

```python
tool_definitions = export_tools(
    provider_id,
    registry.list(),
)
```

### Remove

Independent canonical tool declarations from `main.py`.

### Preserve

Current live session behavior unless changes are required for registry integration.

Do not implement the full Wave 15 AgentLoop here.

---

## W14-T18 — Cross-Provider Tool Calling Contract Tests

**Owner:** Agent R  
**Dependencies:** W14-T06 through W14-T14

### Create

```text
tests/providers/test_tool_calling_contract.py
```

### Verify same logical operation across

```text
Gemini
OpenAI
OpenRouter
Ollama
llama.cpp
```

using mocked transports/adapters.

### Contract

```text
ToolSpec
→ ToolDefinition
→ provider wire format
→ provider response
→ canonical ToolCall
```

Internal result must be provider-independent.

---

## W14-T19 — Fully Offline Local Integration Test

**Owner:** Agent S  
**Dependencies:** W14-T03, W14-T05, W14-T08/W14-T09, W14-T12

### Create

```text
tests/integration/test_local_agent_offline.py
```

### Scenario

```text
network_mode = offline
routing_mode = local_only
provider = ollama
model.tool_calling = true
```

User intent conceptually:

```text
"покажи файлы на рабочем столе"
```

Expected plumbing:

```text
local model request
→ canonical ToolCall
→ ToolExecutor
→ safety
→ legacy file_controller adapter
→ ToolResult
```

No real network access.

Mock local runtime transport.

---

## W14-T20 — Local-Only Regression Gate

**Owner:** Agent T  
**Dependencies:** all routing/provider tasks

### Tests must prove

With:

```text
privacy_profile = fully_local
```

or:

```text
network_mode = offline
```

Slon never invokes:

```text
Gemini
OpenAI
OpenRouter
```

even if:

- Ollama is unavailable;
- llama.cpp is unavailable;
- model is missing;
- tool calling capability is missing.

Expected outcome is a local/offline error, not cloud fallback.

---

# 8. Dependency Graph

```text
                         W14-T01
                     ┌──────┴──────┐
                  W14-T02        W14-T07
              ┌────┼────┐       ┌───┼────┐
           W14-T03 T04 T06    T08  T09  T14
              │     │            \   /
              │    T05            T10
              │     │              │
             T16   T15            T11
                   │                │
                   └───────┬────────┘
                           T12
                            │
                           T13
                            │
                           T17
                        ┌────┴────┐
                       T18       T19
                        └────┬────┘
                            T20
```

---

# 9. Integration Order

Recommended branch integration order:

```text
1. T01
2. T02 + T07
3. T03 + T04 + T06 + T14
4. T05 + T08 + T09
5. T10 + T15 + T16
6. T11
7. T12
8. T13
9. T17
10. T18 + T19
11. T20
```

Agents may work in parallel where paths do not conflict, but merge order should preserve dependency order.

---

# 10. Global Definition of Done

Wave 14 is complete only when all of the following are true:

- [ ] One canonical `ToolRegistry` exists.
- [ ] Every built-in tool has one canonical `ToolSpec`.
- [ ] Tool schemas are not independently maintained in `main.py`.
- [ ] Tool schemas are not independently maintained in `agent/planner.py`.
- [ ] `agent/executor.py` does not manually dispatch each tool via a long `if tool == ...` chain.
- [ ] Every tool execution passes through `ToolExecutor`.
- [ ] Safety authorization runs before every side effect.
- [ ] Dangerous operations still require existing approval rules.
- [ ] All tool results are represented as `ToolResult`.
- [ ] Existing legacy action implementations continue working via adapters.
- [ ] Gemini tool definitions are exported from canonical `ToolSpec`.
- [ ] OpenAI tool definitions are exported from canonical `ToolSpec`.
- [ ] OpenRouter uses the same provider-agnostic tool contracts.
- [ ] Ollama supports canonical tool definitions and canonical tool call parsing.
- [ ] llama.cpp/OpenAI-compatible local runtimes support canonical tool definitions and tool call parsing.
- [ ] Local model capability detection is conservative.
- [ ] Models without `tool_calling=True` never receive tools.
- [ ] `local_first` prefers an appropriate local model.
- [ ] `local_only` cannot fall back to cloud.
- [ ] `offline` cannot fall back to cloud.
- [ ] `fully_local` cannot fall back to cloud.
- [ ] Existing text-only model usage remains compatible.
- [ ] Existing provider streaming tests remain green.
- [ ] Existing safety tests remain green.
- [ ] Existing `agent_task` continues to work.
- [ ] All new tests run without Internet access.
- [ ] Full project test suite passes or any pre-existing failures are explicitly documented and proven unrelated.

---

# 11. Prohibited Outcomes

Reject the Wave if any of the following occurs:

- second tool registry introduced;
- separate local-only tool architecture introduced;
- local models use different tool semantics from cloud models;
- cloud fallback happens under `local_only`;
- planner continues to own canonical tool schemas;
- `main.py` continues to own canonical tool schemas;
- executor still owns canonical dispatch mapping;
- safety checks can be bypassed by model arguments;
- local tool capability is assumed from server API alone;
- legacy action behavior is broken without an explicit migration;
- new framework dependencies replace existing runtime architecture;
- tests require Internet access;
- tool execution success is inferred from human text instead of structured result.

---

# 12. Test Commands

Each agent runs targeted tests first.

Then integration agent runs at minimum:

```bash
pytest tests/tools
pytest tests/providers
pytest tests/agent
pytest tests/integration/test_local_agent_offline.py
```

Then full suite:

```bash
pytest
```

If project uses Ruff:

```bash
ruff check mark/tools providers agent tests
```

If mypy coverage exists for touched modules:

```bash
mypy mark/tools providers
```

Do not weaken lint/type configuration to make new code pass.

---

# 13. Shared Coding-Agent System Prompt

Use this prompt before every task-specific prompt.

```text
You are working on the repository alexghost82/Slon.

You are implementing one task from Wave 14: Unified Tool Runtime + First-Class Local LLM Support.

NON-NEGOTIABLE RULES:

1. Read the existing implementation before modifying it.
2. Reuse existing mark.safety, providers, actions, config and tests.
3. Do not redesign unrelated architecture.
4. Do not introduce LangChain, LangGraph, AutoGen, CrewAI, Redis, Celery, RabbitMQ, or another tool/provider framework.
5. Local LLM support is first-class. Ollama, llama.cpp and OpenAI-compatible local runtimes must use the same internal contracts as cloud models.
6. Never assume a local model supports tool calling merely because its HTTP server supports a tools field.
7. Unknown model capability means unsupported.
8. Preserve fully_local/offline privacy behavior.
9. local_only must never silently invoke Gemini, OpenAI or OpenRouter.
10. Safety authorization must occur before side effects.
11. Model arguments must never override risk/approval policy.
12. Preserve public APIs unless this task explicitly changes them.
13. Add or update tests for every behavior you change.
14. Unit tests must not depend on Internet access.
15. Do not hide failures by weakening tests, typing, linting or validation.
16. Keep the implementation minimal and focused on this task.
17. If you discover an unrelated defect, document it but do not broaden scope unless required to complete this task.
18. Before finishing, run the most relevant targeted tests.
19. Report:
    - files changed;
    - behavior added;
    - tests run;
    - known limitations;
    - any compatibility concern.

Do not commit secrets.
Do not modify unrelated user files.
Do not push to any third-party repository.
```

---

# 14. Agent Prompts

## Agent A — W14-T01

```text
Implement W14-T01: Tool Contracts.

Read existing mark/safety types and repository conventions first.

Create:
- mark/tools/__init__.py
- mark/tools/contracts.py
- mark/tools/errors.py
- tests/tools/test_contracts.py

Implement immutable ToolSpec, ArtifactRef and ToolResult contracts exactly as defined in the Wave 14 specification.

ToolSpec validation:
- name must match ^[a-z0-9_.-]+$
- name must not be empty
- timeout_seconds must be > 0
- handler must be callable

Do not implement registry or executor in this task.
Do not add provider-specific fields to ToolSpec.

Run:
pytest tests/tools/test_contracts.py

Return files changed, test results and any design decision.
```

## Agent B — W14-T02

```text
Implement W14-T02: ToolRegistry.

Prerequisite: W14-T01 contracts are present.

Create:
- mark/tools/registry.py
- tests/tools/test_registry.py

Implement:
- register
- unregister
- get
- contains
- list
- names
- select(capabilities=..., scopes=...)

Add DuplicateToolError and UnknownToolError using existing tool error conventions.

Registry must be provider-agnostic and must not import UI, main.py, server or provider SDKs.

Ensure deterministic ordering.

Run:
pytest tests/tools/test_registry.py
```

## Agent C — W14-T03

```text
Implement W14-T03: Unified ToolExecutor.

Read existing:
- mark/safety
- agent/executor.py
- mark/tools contracts/registry

Create:
- mark/tools/executor.py
- tests/tools/test_executor.py

Execution order must be:
lookup -> validate -> authorize -> approval -> handler -> normalize -> ToolResult.

Denied or unconfirmed tools must never execute their handler.

Do not create a new safety engine. Reuse existing mark.safety authorization and validation behavior.

Normalize known execution failures into ToolResult.
Do not leak raw exception objects as the external contract.

Implement central timeout behavior where practical without redesigning action internals.

Run:
pytest tests/tools/test_executor.py
```

## Agent D — W14-T04

```text
Implement W14-T04: Legacy Action Adapters.

Read existing actions/* signatures before writing wrappers.

Create:
- mark/tools/legacy/__init__.py
- mark/tools/legacy/adapters.py
- tests/tools/test_legacy_adapters.py

Wrap the existing action implementations without rewriting them.

Initial tools:
open_app, web_search, browser_control, file_controller, desktop_control,
computer_control, computer_settings, screen_process, reminder,
weather_report, flight_finder, youtube_video, file_processor,
game_updater, send_message, code_helper, dev_agent, agent_task.

Create one shared legacy result normalizer supporting:
- None
- str
- dict
- ToolResult

Do not change semantics of the underlying actions unless required for adapter compatibility.

Run targeted adapter tests.
```

## Agent E — W14-T05

```text
Implement W14-T05: Canonical Built-in Registry.

Create:
- mark/tools/builtin.py
- tests/tools/test_builtin_registry.py

Use ToolRegistry, ToolSpec and legacy adapters.

Register all built-in tools in one canonical place.

Reuse risk levels and validation knowledge from mark/safety/registry.py.
Do not weaken existing safety.

Do not modify planner or main.py in this task.

Test:
- expected tools exist
- no duplicates
- schemas are present
- handlers are callable
- risk metadata is preserved
```

## Agent F — W14-T06

```text
Implement W14-T06: Provider Tool Schema Exporters.

Create:
- mark/tools/exporters/__init__.py
- mark/tools/exporters/openai.py
- mark/tools/exporters/gemini.py
- tests/tools/test_exporters.py

Export provider wire schemas from canonical ToolSpec.

Do not put provider-specific schema fields inside ToolSpec.

OpenAI format:
type=function/function{name,description,parameters}

Gemini exporter must match the provider API conventions already used by this repository.

Do not call external APIs.

Run exporter tests.
```

## Agent G — W14-T07

```text
Implement W14-T07: Provider-Agnostic Tool Calling Contracts.

Read providers/contracts.py and all provider adapters that instantiate ChatRequest, ChatResponse and ChatEvent.

Modify providers/contracts.py to add:
- ToolDefinition
- ToolCall
- ChatRequest.tools
- ChatRequest.tool_choice
- ChatResponse.tool_calls
- ChatEvent tool_call support

Maintain backward compatibility for text-only callers.

Update only tests/callers necessary for contract compatibility.
Do not implement provider wire parsing in this task.

Run provider contract tests and existing provider unit tests.
```

## Agent H — W14-T08

```text
Implement W14-T08: Ollama Tool Calling.

Read:
- providers/local/common.py
- providers/local/ollama.py
- provider contracts
- existing local provider tests

Add Ollama tool request serialization from canonical ToolDefinition.

Parse Ollama message.tool_calls into canonical ToolCall.

Handle streaming tool calls only if the protocol output can be parsed reliably.
If streaming tool calls are unsupported for the tested path, explicitly fall back to a non-stream request for tool-enabled turns rather than pretending support.

Do not assume every Ollama model supports tools.
Capability enforcement belongs to the capability layer.

Use mocked transport tests only.
No real Ollama server is required for CI.
```

## Agent I — W14-T09

```text
Implement W14-T09: llama.cpp / OpenAI-Compatible Tool Calling.

Read:
- providers/local/common.py
- providers/local/openai_compatible.py
- providers/local/llama_cpp.py

Support:
- tools
- tool_choice
- choices[].message.tool_calls
- choices[].delta.tool_calls where applicable

Normalize every parsed call to provider-agnostic ToolCall.

Do not mark all llama.cpp models tool-capable.
Protocol support is not model capability.

Use mocked transports.
Run targeted local provider tests.
```

## Agent J — W14-T10

```text
Implement W14-T10: Local Model Capability Discovery.

Create:
- providers/local/capabilities.py
- tests/providers/local/test_capabilities.py

Implement LocalModelCapabilities and a conservative resolver.

Resolution precedence:
1. runtime metadata
2. explicit user overrides
3. known model overrides
4. conservative defaults

Unknown tool_calling, structured_output and vision must default to False.

Integrate only enough with local ModelInfo creation to expose correct capability fields.

No web lookup and no remote model registry dependency.
```

## Agent K — W14-T11

```text
Implement W14-T11: Local Model Configuration.

Inspect the existing config schema before modifying it.

Extend configuration to support:
- local default provider
- Ollama enabled/base_url
- llama.cpp enabled/base_url
- preferred local model by role
- explicit model capability overrides

Preserve loopback defaults.
Preserve offline startup.
Validate malformed overrides.

Do not introduce a new configuration framework.
Add tests to the existing config test structure.
```

## Agent L — W14-T12

```text
Implement W14-T12: Routing Policy.

Read providers/router.py, config model-role settings and privacy/network restrictions.

Add routing modes:
- manual
- local_first
- local_only
- cloud_first

Implement hard capability filtering before provider preference.

local_only must never invoke a cloud provider.
offline and fully_local restrictions must remain absolute.

local_first should choose a compatible and available local model before cloud.

If no compatible local model exists under local_only, raise a clear CapabilityError.

Add regression tests for cloud escape prevention.
```

## Agent M — W14-T13

```text
Implement W14-T13: Cost-Aware Model Scoring.

Build on existing ModelInfo and routing policy.

Do not build a billing platform.

After hard filtering, score valid models using:
- local preference
- estimated cost
- availability/latency hints if already available
- role preference

Correctness, capability and privacy are hard constraints and must not be traded for lower cost.

Add deterministic unit tests.
```

## Agent N — W14-T14

```text
Implement W14-T14: Tool Capability Gate.

Modify providers/capabilities.py.

Add generalized required-capability validation.

Ordinary chat requires text.
A request that exposes tools requires text + tool_calling.

Models without tool_calling must not receive tool definitions.

Keep existing role checks compatible.

Add tests proving:
- text-only model can chat
- text-only model cannot execute an agent turn exposing tools
- tool-capable model passes
```

## Agent O — W14-T15

```text
Implement W14-T15: Planner Tool Catalog Consolidation.

Read agent/planner.py carefully.

Remove the hard-coded canonical parameter catalog from PLANNER_PROMPT.

Generate planner-visible tool information from ToolRegistry through a temporary compatibility renderer.

Do not redesign create_plan/replan execution model in this task.
That belongs to Wave 15.

Ensure existing planner behavior remains functional.

Use mocked LLM behavior in tests.
```

## Agent P — W14-T16

```text
Implement W14-T16: Executor Dispatch Consolidation.

Read agent/executor.py and the new ToolExecutor.

Remove the long manual _dispatch_tool branching.

Route tool execution through the canonical ToolExecutor.

Preserve:
- AgentExecutor.execute public behavior
- retry/replan behavior for now
- cancellation behavior
- existing task_queue compatibility

Do not implement Wave 15 AgentLoop.

Add tests proving a legacy plan step reaches the new registry/executor path.
```

## Agent Q — W14-T17

```text
Implement W14-T17: main.py ToolRegistry Integration.

Read main.py fully before editing it.

Build the canonical built-in ToolRegistry once during runtime setup.

Replace independent tool declarations in main.py with exported definitions derived from the registry.

Use provider-specific exporter only at the boundary.

Preserve current Gemini Live behavior unless registry integration requires a narrowly-scoped compatibility change.

Do not implement the full new AgentLoop.

Run relevant main/runtime smoke tests.
```

## Agent R — W14-T18

```text
Implement W14-T18: Cross-Provider Tool Calling Contract Tests.

Create tests/providers/test_tool_calling_contract.py.

Using mocks/fake transports, verify one logical tool definition and tool call roundtrip across:
- Gemini
- OpenAI
- OpenRouter
- Ollama
- llama.cpp/OpenAI-compatible

The internal ToolDefinition and ToolCall shapes must be provider-independent.

Do not use real external APIs.
```

## Agent S — W14-T19

```text
Implement W14-T19: Fully Offline Local Integration Test.

Create tests/integration/test_local_agent_offline.py.

Simulate:
- network_mode=offline
- routing_mode=local_only
- local provider Ollama or llama.cpp
- model with explicit tool_calling=True
- local mocked provider transport

Exercise:
local model request -> canonical ToolCall -> ToolExecutor -> safety -> legacy action adapter -> ToolResult

No Internet.
No real local LLM process required.

Prove that the entire plumbing can execute offline.
```

## Agent T — W14-T20

```text
Implement W14-T20: Local-Only Regression Gate.

Add tests proving cloud providers are never called when:
- routing_mode=local_only
- network_mode=offline
- privacy_profile=fully_local

Cover failures:
- local provider offline
- local model missing
- tool calling unsupported
- local model health check fails

Expected result:
local/capability/provider error.

Forbidden result:
silent Gemini/OpenAI/OpenRouter fallback.
```

---

# 15. Integration Agent Prompt

Use after all task branches are implemented.

```text
You are the Wave 14 Integration Agent for repository alexghost82/Slon.

Your job is not to redesign Wave 14. Your job is to integrate and audit all completed Wave 14 tasks.

Read the Wave 14 specification first.

Audit for these invariants:

1. Exactly one canonical ToolRegistry.
2. Exactly one canonical ToolSpec per built-in tool.
3. No independent canonical tool schema remains in main.py.
4. No independent canonical tool schema remains in agent/planner.py.
5. agent/executor.py no longer manually owns tool dispatch.
6. All execution goes through ToolExecutor.
7. Safety authorization occurs before side effects.
8. Model-provided risk/approval fields cannot bypass policy.
9. ToolResult is the canonical execution result.
10. Gemini/OpenAI/OpenRouter/Ollama/llama.cpp normalize to the same internal tool contracts.
11. Local capability detection is conservative.
12. local_only cannot invoke cloud.
13. offline cannot invoke cloud.
14. fully_local cannot invoke cloud.
15. Existing text chat and legacy agent_task behavior remain functional.
16. Unit tests do not require Internet.

Resolve merge-level inconsistencies only.
Do not start Wave 15 features.

Run:
pytest tests/tools
pytest tests/providers
pytest tests/agent
pytest tests/integration/test_local_agent_offline.py
pytest

Run relevant lint/type checks without weakening configuration.

Produce a final report:
- integrated files
- conflicts resolved
- tests run
- failures
- pre-existing failures
- architecture invariant audit
- explicit PASS/FAIL decision for Wave 14
```

---

# 16. Review Agent Prompt

Run independently after integration.

```text
You are an independent architecture and security reviewer.

Review Wave 14 implementation in alexghost82/Slon.

Do not modify code on the first pass.

Look specifically for:
- duplicated tool metadata
- safety bypasses
- execution-before-approval bugs
- provider-specific abstractions leaking into ToolSpec
- cloud fallback in local_only/offline/fully_local
- optimistic local capability detection
- broken legacy actions
- unbounded timeouts
- raw exceptions exposed as execution contracts
- tests that secretly require Internet
- behavior claimed as successful without ToolResult.ok
- tool schemas diverging between providers
- circular imports between tools/providers/safety/main
- public API regressions

Classify findings:
BLOCKER
HIGH
MEDIUM
LOW

For every finding provide:
- file
- symbol/line range
- concrete failure mode
- minimal recommended fix

Then state whether Wave 14 is safe to accept.
```

---

# 17. Suggested Git Branch Naming

```text
wave14/t01-tool-contracts
wave14/t02-tool-registry
wave14/t03-tool-executor
wave14/t04-legacy-adapters
wave14/t05-builtin-registry
wave14/t06-tool-exporters
wave14/t07-provider-tool-contracts
wave14/t08-ollama-tools
wave14/t09-llamacpp-tools
wave14/t10-local-capabilities
wave14/t11-local-config
wave14/t12-routing-policy
wave14/t13-cost-routing
wave14/t14-capability-gate
wave14/t15-planner-registry
wave14/t16-executor-registry
wave14/t17-main-registry
wave14/t18-provider-contract-tests
wave14/t19-offline-integration
wave14/t20-local-only-gate
```

---

# 18. Completion Report Template

Every coding agent returns:

```markdown
## Task
W14-Txx — Name

## Files changed
- ...

## Implemented
- ...

## Tests
- `pytest ...` — PASS/FAIL

## Compatibility
- ...

## Known limitations
- ...

## Out-of-scope issues discovered
- ...

## Ready for integration
YES / NO
```

---

# 19. Final Wave Acceptance Record

The integration agent should fill this in.

```markdown
# Wave 14 Acceptance

Date:
Integration commit:

## Core
- [ ] Tool contracts
- [ ] Tool registry
- [ ] Tool executor
- [ ] Legacy adapters
- [ ] Built-in registry

## Providers
- [ ] Gemini exporter
- [ ] OpenAI exporter
- [ ] OpenRouter compatibility
- [ ] Ollama tools
- [ ] llama.cpp tools
- [ ] Local capability discovery

## Routing
- [ ] manual
- [ ] local_first
- [ ] local_only
- [ ] cloud_first
- [ ] cost-aware scoring
- [ ] no cloud escape

## Migration
- [ ] planner schema duplication removed
- [ ] executor dispatch duplication removed
- [ ] main.py schema duplication removed

## Verification
- [ ] tools tests
- [ ] provider tests
- [ ] agent tests
- [ ] offline local integration
- [ ] full pytest
- [ ] lint
- [ ] type checks

## Final decision

PASS / FAIL

## Blocking issues

None / list here
```

---

# 20. Next Wave Boundary

Wave 14 stops after canonical tool runtime and local/provider tool compatibility are proven.

Wave 15 will implement:

```text
model
→ tool_call
→ safety
→ execute
→ ToolResult
→ observation
→ model
→ ...
```

including:

- iterative AgentLoop;
- multi-tool turns;
- observation chaining;
- cancellation;
- loop detection;
- optional planner strategy;
- local/cloud model-agnostic orchestration.

Do not pull Wave 15 work into Wave 14 unless strictly necessary to prove the Wave 14 contracts.
