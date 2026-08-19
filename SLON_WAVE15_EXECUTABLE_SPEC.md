# Wave 15 — Iterative Multi-Turn Agent Loop Runtime

## Slon Agent — Executable Development Specification

**Repository:** `alexghost82/Slon`  
**Scope:** Wave 15  
**Primary objective:** Implement the first-class `AgentLoop` runtime for multi-turn `model -> tool -> observation -> model` iterative orchestration across all cloud and local model providers.

---

# 1. Architecture Baseline (Post Wave 14)

Wave 14 established:
- Canonical `ToolRegistry` ([registry.py](file:///Users/alexandr.bogdanov/Documents/GitHub/Slon/mark/tools/registry.py))
- Immutable `ToolSpec`, `ArtifactRef`, `ToolResult` ([contracts.py](file:///Users/alexandr.bogdanov/Documents/GitHub/Slon/mark/tools/contracts.py))
- Unified `ToolExecutor` with safety enforcement ([executor.py](file:///Users/alexandr.bogdanov/Documents/GitHub/Slon/mark/tools/executor.py))
- First-class local model tool exporters and adapters ([exporters/](file:///Users/alexandr.bogdanov/Documents/GitHub/Slon/mark/tools/exporters/))
- Routing modes (`manual`, `local_first`, `local_only`, `cloud_first`) and cost-aware routing ([routing.py](file:///Users/alexandr.bogdanov/Documents/GitHub/Slon/providers/routing.py))

Wave 15 builds the core multi-turn **`AgentLoop`** engine on top of this foundation.

---

# 2. Target Architecture

```text
User Request / Steering
         │
         ▼
  ┌──────────────┐
  │ AgentContext │
  └──────┬───────┘
         │
         ▼
 ┌───────────────┐
 │   Model Turn  │◄─────────────────────────────┐
 └──────┬────────┘                              │
        │                                       │
     ToolCall                                   │
        │                                       │
 ┌──────┴────────┐                              │
 │ Capability &  │                              │
 │ Safety Gate   │                              │
 └──────┬────────┘                              │
        │                                       │
 ┌──────┴────────┐                              │
 │  ToolExecutor │                              │
 └──────┬────────┘                              │
        │                                       │
    ToolResult                                  │
        │                                       │
 ┌──────┴────────┐                              │
 │  Observation  │                              │
 └──────┬────────┘                              │
        │                                       │
 ┌──────┴────────┐                              │
 │ Loop Detector │───(Continue within budget)───┘
 └──────┬────────┘
        │
   (Final Answer / Budget Exceeded)
        │
        ▼
   Final Answer
```

---

# 3. Exact Modules & Contracts to Create

### 3.1 `agent/observation.py`
- `Observation`: Structured result wrapper returned to the model (`tool_call_id`, `tool_name`, `ok`, `content`, `artifacts`, `error`).
- `ObservationKind`: Enum (`SUCCESS`, `TOOL_ERROR`, `SAFETY_DENIAL`, `TIMEOUT`, `SYSTEM`).

### 3.2 `agent/runtime.py`
- `LoopBudget`: Maximum tool calls (default 15), maximum turns (default 10), timeout seconds (default 120s).
- `LoopDetector`: Detects identical repeated calls (N>=3), alternating A/B loops, and zero-progress loops.
- `AgentLoop`: Core iterative loop supporting `run(user_goal)` with streaming events, cancellation token, user steering inputs, and voice interruption handling.

### 3.3 `agent/steering.py`
- `SteeringSignal`: User interruption or guidance injected during loop execution.

---

# 4. Global Definition of Done for Wave 15

Wave 15 is complete only when all of the following are true:
1. `AgentLoop` executes multi-turn tool-observation cycles asynchronously.
2. Local models (Ollama, llama.cpp) and cloud models (Gemini, OpenAI, OpenRouter) use the exact same loop.
3. Tool errors are returned to the model as observations for self-correction instead of crashing the loop.
4. Loop detector prevents runaway loops (repeated calls, A/B oscillating calls, no progress).
5. Voice interruption and user steering signals interrupt execution cleanly.
6. 100% of existing tests + new Wave 15 test suite pass cleanly offline.

---

# 5. Master Orchestrator Prompt for Wave 15

```text
You are the Wave 15 Lead Orchestrator for Slon.
Your mission is to implement Wave 15: Iterative Multi-Turn Agent Loop Runtime based on SLON_WAVE15_EXECUTABLE_SPEC.md.
Execute task by task in isolated sub-agents, verify all test suites, and audit for 100% compliance.
```
