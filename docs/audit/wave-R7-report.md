# WAVE R7 — UI / Voice / iOS (Python only)

**WAVE:** R7  
**STATUS:** COMPLETE (PARTIAL on Gemini Live transport)  
**DATE:** 2026-09-09  

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-025 | UI owns Core | Widgets could call Core | Typed `runtime/commands.py` (`send_message`, `start_voice`, `stop_voice`, `cancel`, `approve`, `deny`, `select_model`, `change_settings`, `open_session`). `DesktopControlPlane.dispatch`. Architecture test: `ui/` / `ui.py` must not import AgentLoop, ToolExecutor, Router, Gemini Live. |
| SLON-024 leftover | event catalog | Missing UI event kinds | Already on `RuntimeEventKind` from R5: assistant_text, thinking, listening, speaking, tool_*, approval_required, job_progress, error, session_changed. |
| SLON-015/022 | Voice | AgentLoop vs Gemini Live | AgentLoop has **no** Gemini Live import (architecture test). Canonical voice is existing `runtime.canonical_voice.VoiceBridge` (STT→AgentLoop→TTS). SlonLive remains Gemini realtime **transport** only — One AgentLoop is still PARTIAL for live audio. |
| SLON-030 | ios/** | Sibling ownership | **Not edited.** Do not delete. |

## REMOVED LEGACY

None. SlonLive Gemini transport kept by architecture decision until a provider-neutral live socket exists.

## TESTS

| Command | Result |
| --- | --- |
| `python -m pytest tests/architecture/test_ui_thin_client.py tests/unit/runtime/test_ui_commands.py tests/unit/speech/voice/test_voice_bridge.py tests/architecture -q` | **26 passed** |

Full `pytest tests` started after this wave (required after R7).

## SECURITY

- UI cannot import production tool/provider runtimes.
- Unbound voice/stop commands fail closed (`ControlPlaneUnavailable`).

## MIGRATIONS

None.

## KNOWN LIMITATIONS

- SlonUI/JarvisUI still contain large glue; they do not import Core runtimes, but are not fully command-only widgets.
- Gemini Live audio path in `main.py` still reasons over Live tools (documented PARTIAL).
- iOS tree untouched; sibling agent owns it.
- Hardware barge-in / device-switch MANUAL.

## RUNTIME VERIFICATION STILL REQUIRED

- Full suite (this wave).
- Mic barge-in on hardware.
- iOS VoiceBridge notes from sibling agent: none received.

## COMMITS

Recorded after commit.
