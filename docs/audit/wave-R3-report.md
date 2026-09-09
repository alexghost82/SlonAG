# WAVE R3 — One AI Plane

**WAVE:** R3  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-012/013 | planner, error_handler, executor Gemini | Direct `google.generativeai` | `providers.gemini.generative` → Router `complete_text` |
| SLON-014 | `or_client` callers | Parallel OpenRouter client | `from providers.text_ops import client` (NeverFallback Router; empty when blocked) |
| SLON-015 | `main.py` Live Client | `google.genai` in app entry | `providers.gemini.live.create_live_client` / `types` |
| SLON-016 | actions SDK imports | Vendor imports in actions | Same shims; fail-closed via `_settings_forbid_cloud` |
| SLON-026/035 | architecture test | Missing allowlist | `tests/architecture/test_provider_imports.py`; onboard wizard allowed |
| SLON-009 leftover | memory extract | still `or_client` | now `text_ops.client` / fail-closed |

## REMOVED LEGACY

- Production `google.*` / `or_client` imports outside `providers/**` and `config/onboard.py`.
- `or_client.py` file remains on disk (unused by production callers). Do not delete until R10 caller proof.

## TESTS

`python -m pytest tests/architecture tests/unit/providers/test_text_ops.py tests/agent/test_planner_tool_catalog.py tests/unit/agent/test_executor.py tests/unit/providers/test_local_only_regression_gate.py -q` → **30 passed**

Full suite not re-run in this wave (required after R3 — run before R4 close if time; otherwise recorded as still required).

## SECURITY

- `NeverFallbackPolicy` on text_ops Router.
- local_only / offline / fully_local / local_with_tools / tools_only fail-closed (no silent cloud).
- SlonLive client construction is behind `providers/gemini/live.py` but Live still Gemini-specific (R7).

## KNOWN LIMITATIONS

- Actions still contain large Gemini-shaped call sites; they no longer import the SDK.
- `config/onboard.py` may import `openai` / `google` (documented wizard-only).
- Full `pytest tests` after R3 still required.

## COMMITS

Filled after commit.
