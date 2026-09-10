# Live / voice contract (PR-001)

**Clone:** SlonAG  
**Date:** 2026-09-09  
**Status:** binding for desktop software gate

## Ownership

| Plane | Owner | Allowed to do | Forbidden |
| --- | --- | --- | --- |
| Reasoning | `AgentLoop` via `RuntimeStack.create_agent_loop()` | tools, memory extract/commit, session persist | import Gemini Live / `google.genai` |
| Desktop audio I/O | `runtime.canonical_voice.VoiceBridge` | STT → AgentLoop → TTS, barge-in | own tool loop, own memory writer |
| Optional Live transport | `providers.gemini.live.create_live_client` | socket / audio frames only | tool loop, memory writer, second executor |

## Rules

1. **One reasoner.** Tools, memory, and session writes go through `AgentLoop` / the stack `ToolExecutor`. `SlonLive` is lifecycle + optional transport, not a second AgentLoop.
2. **One desktop audio path.** Mic/speaker on desktop start `VoiceBridge`. Gemini Live must not replace AgentLoop for audio Gemini models.
3. **LiveToolBridge** is a thin forwarder onto the stack `ToolExecutor` (same pipeline AgentLoop uses). It must not own a parallel production executor when the stack already has one.
4. **Core isolation.** `agent/runtime.py` must not import `providers.gemini.live` or `google.genai`.
5. **SDK isolation.** `from google import genai` stays inside `providers/gemini/live.py` only.
6. **Memory.** Live/voice may call `format_store_for_prompt` / `commit_extracted_facts` on the stack store. No JSON memory writer on this path.

## Out of scope

iOS voice, hardware barge-in MANUAL, Ghost, UI widget rewrite (PR-021), offline/local_only socket fail-closed (PR-002).
