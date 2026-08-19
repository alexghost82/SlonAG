# MASTER_ROADMAP — Slon

Источник требований: `CODE_AGENT_IMPLEMENTATION_PLAN.md`.
Интеграционная ветка: `integration/main`.
Интеграционный клон: `/Users/slon/Documents/GitHub/Slon`.

## Initiative

Модернизация Slon: русский desktop-клиент, выбор Gemini / OpenAI / OpenRouter / local, безопасные инструменты, локальные STT/TTS/vision/memory, Desktop Control API и iOS remote.

## Epics

| Epic | Name | First wave |
|---|---|---|
| 0 | Legal and boundary | Wave 0 |
| 1 | Repo safety, config, test foundation | Wave 0–1 |
| 2 | Localization | Wave 2 |
| 3 | Provider contracts and adapters | Wave 2–3 |
| 4 | Routing, roles, settings UI | Wave 4 |
| 5 | Local runtime | Wave 5 |
| 6 | Speech | Wave 5 |
| 7 | Vision and documents | Wave 6 |
| 8 | Memory | Wave 6 |
| 9 | Typed tools and approvals | Wave 7 |
| 10 | NetworkPolicy | Wave 8 |
| 11 | Desktop Control API | Wave 9 |
| 12 | iOS remote | Wave 10 |
| 13 | Integration, security, packaging | Wave 11 |
| 14 | Remote access / APNs | deferred, not in first MVP |

## Waves

### Wave 0 — safety, licenses, user-change boundary

Parallel group A:

- W00-T01 repo-safety
- W00-T02 license-inventory
- W00-T03 user-change-boundary

### Wave 1 — config, dependencies, tests

Depends on Wave 0.

Parallel group A:

- W01-T01 config-stack
- W01-T02 requirements-split
- W01-T03 test-foundation
- W01-T04 game-updater-guard

### Wave 2 — contracts

Depends on Wave 1.

Parallel group A:

- W02-T01 i18n-framework
- W02-T02 provider-contracts

### Wave 3 — provider adapters

Depends on W02-T02.

Parallel group A:

- W03-T01 gemini-adapter
- W03-T02 openai-adapter
- W03-T03 openrouter-adapter
- W03-T04 local-adapters

### Wave 4 — routing and settings

Depends on Wave 3.

Serial then parallel:

- W04-T01 router
- then W04-T02 roles-fallback-cost || W04-T03 setup-wizard-ui

### Wave 5 — local runtime and speech

Depends on Wave 4.

Parallel group A:

- W05-T01 local-runtime-manager
- W05-T02 stt
- W05-T03 tts

Piper TTS decision recorded 2026-08-15; implementation is Wave 12 (`W12-T01`).

### Wave 6 — vision, documents, memory

Depends on Wave 4.

Parallel group A:

- W06-T01 vision
- W06-T02 documents
- W06-T03 memory-sqlite

### Wave 7 — tool safety

Depends on Waves 5 and 6.

Serial then parallel:

- W07-T01 safety-policy-contracts
- then W07-T02 executor-no-codegen || W07-T03 file-controller-safe || W07-T04 desktop-typed-ops || W07-T05 reminder-safe

### Wave 8 — NetworkPolicy

Depends on Wave 7.

- W08-T01 network-policy

### Wave 9 — Desktop Control API

Depends on Wave 8.

Serial then parallel:

- W09-T01 api-schemas-mock
- then pairing/auth and route modules in separate files

### Wave 10 — iOS

Depends on Wave 9.

Serial then parallel:

- W10-T01 design-system
- W10-T02 networking
- then feature modules in `ios/MarkRemote/Features/<Name>/`

### Wave 11 — integration and beta gates

Depends on Waves 8 and 10.

Serial:

- W11-T01 beta-gates — integration/security/offline smoke suites, secret scan + license audit checklist, full pytest/ruff/iOS verification

## Current status

- Wave 0: accepted and integrated.
- Wave 1: accepted and integrated.
- Wave 2: accepted and integrated.
- Wave 3: accepted and integrated.
- Wave 4: accepted and integrated.
- Wave 5: accepted and integrated; Piper deferred to Wave 12 after 2026-08-15 decision.
- Wave 6: accepted and integrated.
- Wave 7: accepted and integrated.
- Wave 8: accepted and integrated.
- Wave 9: accepted and integrated.
- Wave 10: accepted and integrated.
- Wave 11: accepted and integrated (beta gates; mypy debt deferred).
- Wave 12: accepted and integrated (Piper TTS + same-LAN bind policy).
- Wave 12 follow-up: Piper wired into `ui.py`; live Desktop Control `listen()` via `server.listener` / `python -m server`.
- Wave 13: in progress — main/ui glue, TLS LAN, Piper opt-in download, mypy; Bonjour/QR images/live video deferred (W13-T07).
- Epic 14 (remote access / APNs / VPN product / public internet): deferred, not in first MVP.

### Wave 12 — backlog (post beta gates) → integrated

Depends on Wave 5 TTS contracts + user decisions 2026-08-15. Integrated on `integration/main`.

- W12-T01 piper-tts — **done** — injectable Piper engine + `ru_RU-dmitri-medium` (MIT); models under `/models/` (gitignored); Wave 12 had no auto-download (superseded by W13-T01 opt-in)
- W12-T02 lan-bind — **done** — same-LAN Desktop Control API bind policy (not public internet); default remains loopback; auth/pairing required
- Follow-up — **done** — `ui.py` LOCAL TTS (Piper) + DESKTOP API toggle; `DesktopControlListener` real bind/listen; CLI `python -m server`

### Wave 13 — main/ui glue, TLS, Piper opt-in download, mypy

Depends on Wave 12 follow-up (`851f155`). Personal/NC; Epic 14 still deferred (except TLS for LAN).

Parallel group A (disjoint owned_paths):

- W13-T01 piper-auto-download — opt-in CLI/`consent=` download for `ru_RU-dmitri-medium`; offline CI
- W13-T02 tls-lan-api — optional TLS for Desktop Control listener; bind_policy + auth kept
- W13-T03 runtime-bridge — `mark/bridge` assembles router/memory/safety/network/speech with degrade

Then serial:

- W13-T04 main-py-glue — wire bridge into `main.py`; keep live Gemini path
- W13-T05 ui-py-glue — fuller UI glue (status, TLS-aware API, STT/TTS notes)
- W13-T06 mypy-cleanup — reduce debt without weakening mypy config
- W13-T07 deferred-discovery-video — Bonjour / QR images / live video **deferred** (plan §18.3/§18.9; Wave 10 already text QR + on-demand screen)

## User decisions (recorded 2026-08-15)

All previously open items below are **decided**. None remain open for MVP scope.

1. **License posture**: personal / non-commercial only (CC BY-NC aligned). No commercial-ready claims.
2. **API keys**: User reports keys never leaked; **do not rotate**; **use existing keys** from the OpenClaw working copy when running locally. Keys remain in OpenClaw workspace secret store; no rotation required per user 2026-08-15. Never commit keys; never put key material in orchestration docs, INTEGRATION_LOG, or task specs.
3. **Piper TTS**: Approved concrete choice — see W12-T01. Runtime: injected `SpeechSynthesizer` wrapping local **rhasspy/piper** CLI (MIT). Voice: **ru_RU-dmitri-medium** (MIT; dataset CC0). Spec under `orchestration/tasks/W12-T01.md`.
4. **Network**: iPhone on **same LAN** is approved. Not full public internet / not APNs product / not VPN product. Desktop Control API may bind for same-network LAN access with existing auth/pairing; still default-secure (loopback default); no "open to internet" claim. Implementation gap vs loopback-only defaults → `W12-T02`.
5. **Git remote / push policy (updated 2026-08-15):** **local by default; when push is requested, only `alexghost82`.** Never push to third-party/upstream remotes or any other org/user. `remote.origin.pushurl` stays `DISABLED` for non-`alexghost82` remotes (fetch-only OK). No `alexghost82/Slon` (or equivalent) repo found on GitHub as of this decision — do not create a public repo without asking; push target = `alexghost82` when the user creates/requests the repo.
6. **Piper auto-download (Wave 13 policy change)**: Opt-in / documented operator download helper is **approved**. Silent download on every start remains forbidden. CI tests must pass offline (mock/skip network). Models stay gitignored under `/models/`.
7. **TLS on LAN API**: Approved for personal same-LAN / loopback Desktop Control (self-signed or mkcert). Not a public-internet product.

## User decisions still open

None for the MVP decisions list above. Remaining deferred product work: Epic 14 APNs/VPN/public internet.
