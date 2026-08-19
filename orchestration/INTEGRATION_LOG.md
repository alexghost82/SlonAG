# INTEGRATION_LOG — Slon

## Bootstrap

- Date: 2026-08-15
- Source clone: `/Users/slon/SillyTavern/Slon` at `eac6378`
- Integration clone: `/Users/slon/Documents/GitHub/Slon`
- Branch: `integration/main`
- Push remote: disabled (`remote.origin.pushurl=DISABLED`). Policy updated 2026-08-15: **local by default; when push is requested, only `alexghost82`.** Never push to third-party/upstream remotes or other orgs/users. No alexghost82 Slon repo found yet — push stays disabled until user creates/requests it.
- User secrets and OpenClaw working tree: not copied

## Wave 0

- BASE_W0 (worktree start): `91b560db20220723e4eaa37affeabd327e6b2bef`
- Status: accepted and integrated
- Integration commit after Wave 0 task commits: `10ac167dec5d5869e814edc2125a7c2d9ed0e0b5`
- Post-wave log commit will follow this file update

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W00-T01 | `d808cc172153bb242c39564a4b174907ed9ca8ca` | `0c9ba44` | `.gitignore`, `.gitattributes` | `git check-ignore` covers keys, memory, `.venv/`, `models/`, `logs/`, `tmp/`, `.env` |
| W00-T02 | `0422bee450c9a2584c34e3d6c90b9a6da3243c51` | `5ee3a31` | `THIRD_PARTY_LICENSES.md`, `docs/licenses/INVENTORY.md` | CC BY-NC recorded; no commercial-ready claim; 23 requirement lines listed |
| W00-T03 | `9b9231c9e1a28cacbc20c1364404e617dd4e90e9` | `10ac167` | `docs/audit/user-changes.md` | 15 status paths inventoried; secrets redacted; winreg-guard → W01-T04 |

### Rejected or deferred

None.

### Integrator notes

- Cherry-picked one verified commit per task. Branches were not merged wholesale.
- Secret scan of the integration tree found only the pre-existing UI placeholder `sk-or-…` in upstream `ui.py`. No live keys were added.
- OpenClaw and Cursor-workspace working copies were not modified.
- Next base for Wave 1 is the commit after this log update.

## Wave 1

- BASE_W1 (worktree start): `5f9b9551f6771ef0b9a33846abd072458dd4524c`
- Status: accepted and integrated
- Task commits: `602cdfb` (T03), `66efb9b` (T01), `225e12f` (T02), `8d28db0` (T04)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W01-T03 | `76c766c8c07428a73201f917c4741aaebe2ea6db` | `602cdfb` | harness, `pyproject.toml`, CI | foundation tests + ruff scope |
| W01-T01 | `9a5e4d49aed778604893377dda63961c65d0d74f` | `66efb9b` | `config/**`, `tests/unit/config/**` | 27 tests; import without `api_keys.json` |
| W01-T02 | `0e1fce07256b817ea895f94f0207e69440e46a96` | `225e12f` | requirements split, `setup.py` | 13 tests; no `google-generativeai`; no Windows deps in shim |
| W01-T04 | `6bf9731d5263b35f106529ae87f240ea180bb23a` | `8d28db0` | `actions/game_updater.py`, its test | import on macOS; helpers return None |

### Integrator follow-up

- Wrap one E501 line in `tests/unit/config/test_secrets.py` so Wave 1 ruff passes after merge.
- Ignore `config/settings.json` (T01 could not edit `.gitignore`).

### Rejected or deferred

None.

## Wave 2

- BASE_W2 (worktree start): `6ae3c74292fac2ef399420fdd7fde517530c1730`
- Status: accepted and integrated
- Task commits: `bfba11b` (T01), `12ed041` (T02)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W02-T01 | `28d860238889de3731d1ec791b0231ba9e8bb3fb` | `bfba11b` | `localization/**`, `i18n/*.json`, localization tests | 13 tests; default `tr` is Russian; `ui.py` unchanged |
| W02-T02 | `f00d801e8d3e8d643a9c38e7603b09de7070150d` | `12ed041` | provider contracts/registry, provider tests | 36 tests; no router; four mock chat providers |

### Integrator follow-up

- Ruff E501/E731 in three provider test lines so Wave 1 CI lint still passes.

### Rejected or deferred

None. `ui.py` string migration and `providers/router.py` remain later waves.

## Wave 3

- BASE_W3 (worktree start): `c4b4feb3589300071a48de6cb4b537e06b6ebe5c`
- Status: accepted and integrated
- Task commits: `0f8e678` (T01), `28c594e` (T02), `568f75f` (T03), `326a0ec` (T04)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W03-T01 | `9622ccdc49d89752f2d2ad2f3ed95ac82c506593` | `0f8e678` | `providers/gemini/**` | 10 tests; constructor key; mocked google-genai |
| W03-T02 | `1f9621c1ab7f7776bffc9d6e3eafeacf5344385d` | `28c594e` | `providers/openai/**` | 13 tests (1 skip without requests); no SDK |
| W03-T03 | `4aff893a85f0f4636df157447be2e93129ba4ba1` | `568f75f` | `providers/openrouter/**` | 12 tests; 429 does not switch models; no or_client |
| W03-T04 | `102899a18928f12c2a1677c92c283d9775ea379e` | `326a0ec` | `providers/local/**` | 37 tests; loopback default; example.com rejected |

### Integrator follow-up

- Renamed colliding `test_provider.py` / `test_registry.py` modules so pytest can collect the full suite.
- Lazy-import `requests` in OpenRouter client so CI without runtime deps can collect tests.

### Rejected or deferred

None. `providers/router.py` remains Wave 4.

## Wave 4

- Status: accepted and integrated
- T01 base: `30af3a5` → integration `e0d972c`
- T02/T03 base: `17183ff`

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W04-T01 | `eb34038b929b39d6e66f2001005357a941e89f84` | `e0d972c` | `providers/router.py`, `test_router.py` | 15 tests; default never; offline blocks cloud |
| W04-T02 | `51814f18f8ca7fd916e44bb180788814da34c639` | `290134b` | `policies/**` | 33 tests; local→cloud only explicit + confirmation flag |
| W04-T03 | `688eb3b997ce5fe9863c80be204b48b68d14d13c` | `d5e257c` | `mark/app/**` | 20 tests; headless; `ui.py` unchanged |

### Rejected or deferred

Wizard not wired into `ui.py`. Dedicated i18n keys for wizard steps not added.

## Wave 5

- BASE_W5 (worktree start): `a1044fc7f3d467cb4451af4d2f1a5b5c6b671874`
- Status: accepted and integrated
- Task commits: `474c18e` (T01), `f189c4e` (T02), `9c42a2e` (T03)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W05-T01 | `7a251166b6f7f6759a9b55e9df150ace744b9ec4` | `474c18e` | `mark/runtime/**`, `tests/unit/runtime/**` | 20 tests; injected runner; pull needs size+license confirm; no downloads |
| W05-T02 | `157aeb2eef33fa5b681fdc91e3dfed5ceba1cc23` | `f189c4e` | `speech/stt/**`, `tests/unit/speech/stt/**` | 13 tests; default `ru`; echo guard; cancel; VAD; factory `stt_local` |
| W05-T03 | `ad7ec76ff2a21b4afbe2d6bb13da594e63242745` | `9c42a2e` | `speech/tts/**`, `tests/unit/speech/tts/**` | 19 tests; sentence barge-in; `is_speaking`; factory `tts_local`; no Piper |

### Integrator follow-up

- `speech/` is a PEP 420 namespace package; no shared `speech/__init__.py`.
- STT echo-guard hook is `is_assistant_speaking`; TTS exposes `is_speaking`. Not wired into `ui.py`.
- No new pip packages. Engines and runtime runners are injected.

### Rejected or deferred

Piper TTS remains blocked pending a user license decision. Runtime/STT/TTS are not wired into `ui.py` or the live chat path.

## Wave 6

- BASE_W6 (worktree start): `0b57e39a4e4c503abe97b068a9b0a70645acd02d`
- Status: accepted and integrated
- Task commits: `a7a0b14` (T01), `982af93` (T02), `bf77c06` (T03)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W06-T01 | `3871e7a513273399ad1603b1741d96967f490855` | `a7a0b14` | `mark/vision/**`, `tests/unit/vision/**` | 24 tests; temps deleted; OCR untrusted; no cloud by default |
| W06-T02 | `7d4565e11d2611fe1aaa6b9da744f736caf99667` | `982af93` | `mark/documents/**`, `tests/unit/documents/**` | 27 tests; traversal/zip-bomb/size; injection has no tool_call |
| W06-T03 | `2808165ba7bf5e98141c4a416aea912e337635cf` | `bf77c06` | `mark/memory/**`, `tests/unit/memory/**` | 26 tests; propose≠write; secrets rejected; JSON migrate; legacy `memory/` untouched |

### Integrator follow-up

- Renamed colliding `tests/unit/vision/test_factory.py` and `test_provider.py` so pytest can collect the full suite.
- Wrapped three E501 lines in memory tests so Wave 1 CI lint still passes.

### Rejected or deferred

Vision/documents/memory are not wired into `ui.py` or legacy `memory_manager.py`. PDF/DOCX/VLM/embedder remain injected hooks. Piper still deferred.

## Wave 7

- T01 base: `7eb6eb9` → integration `d2e309a`
- T02–T05 base: `49cea21`
- Status: accepted and integrated
- Task commits: `d2e309a` (T01), `92a0040` (T02), `7d44292` (T03), `246342b` (T04), `58aedb8` (T05)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W07-T01 | `66c61d32cca99ebde0fc6ffa3d8159273e323522` | `d2e309a` | `mark/safety/**` | 48 tests; risk from registry; unknown/untrusted high-risk denied |
| W07-T02 | `9376bfa6f5b5a468a199884b2c081d36112cc4de` | `92a0040` | `agent/executor.py` | 14 tests; no codegen; unknown → `UnknownToolError` |
| W07-T03 | `065a2d755f8591ec3f5619de83a498fabd945421` | `7d44292` | `actions/file_controller.py` | 11 tests; allowlist+canonical; trash-only; no confirm → no delete |
| W07-T04 | `6fee767e02e46ce74126dd0c578164bb68b92a9a` | `246342b` | `actions/desktop.py` | 16 tests; exec/eval gone; typed ops only |
| W07-T05 | `eeb5709335f03562da5f1c8b2772b00edfbb1b73` | `58aedb8` | `actions/reminder.py` | 11 tests; JSON payload; no `shell=True`; no generated Python |

### Integrator follow-up

- Renamed `tests/unit/safety/test_policy.py` so it does not collide with memory `test_policy`.
- Wrapped two E501 lines in desktop tests.

### Rejected or deferred

UI confirmer not wired. Planner/`error_handler` may still propose `generated_code`; executor now rejects it. `dev_agent` / `computer_settings` `shell=True` remain outside this wave. NetworkPolicy is Wave 8.

## Wave 8

- BASE_W8 (worktree start): `92c5f8b64ab7f9a58beee83e2e492519d4b3ca0e`
- Status: accepted and integrated
- Task commits: `7c03d12` (T01)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W08-T01 | `8b188af991727a86729e801895319fcbd7f4351f` | `7c03d12` | `mark/network/**`, network unit + offline tests | 26 tests; offline blocks external; loopback OK; cloud denied offline; proxy guard |

### Integrator follow-up

- Wrapped one E501 line in `tests/unit/network/test_network_journal.py`.

### Rejected or deferred

Router/adapters/`ui.py` not yet calling `NetworkPolicy`. Activity journal is API-only until a UI pane binds `activity()` / `recent()`.

## Wave 9

- T01 base: `22889a2` → integration `57a879b`
- T02–T04 base: `9bb2beb`
- Status: accepted and integrated
- Task commits: `57a879b` (T01), `bb2a9a4` (T02), `9104d74` (T03), `c4928e3` (T04)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W09-T01 | `b9358b00cfe3f687db75236d9eba8df5b83157f3` | `57a879b` | `server/schemas.py`, `server/app.py` | 27 tests; loopback default; unauth 401; no API keys in responses |
| W09-T02 | `799cbfda2a31e09fb4215fbb47f27a26d836e4f4` | `bb2a9a4` | `server/pairing.py` | 9 tests; OTP pairing; revoke; secret hashed at rest |
| W09-T03 | `c2abe2a66487d6e892a5877d390485789f0ee478` | `9104d74` | `server/auth.py`, `server/permissions.py` | 25 tests; HMAC tokens; refresh rotate; rate limit; safety flag |
| W09-T04 | `1cc04bba3a4f8950b4afe5434645e4c4fd8dfb29` | `c4928e3` | `server/routes/**`, `server/websocket.py` | 30 tests; auth required; idempotency; no tool exec; no memory/*.json |

### Integrator follow-up

- Wrapped E501 lines in auth/pairing tests after merge.

### Rejected or deferred

Mock `app.py` not yet wired to real pairing/auth/route handlers. No TLS listener, no public bind, no FastAPI. Real WebSocket transport and QR images remain later. iOS client is Wave 10.

## Wave 10

- Scaffold: `cc9cfa8` + APIModels fix `b8734e9`
- T01∥T02 → `44d8f5a` / `6010713`; features base `5ae8cd2`
- Status: accepted and integrated
- Task commits: `44d8f5a` (T01), `6010713` (T02), `4490c90` (T03), `ffc969f` (T04), `c9361cc` (T05), `160c54d` (T06)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W10-T01 | `7e6e1f6569dc88b2650951b072b1ed108c128fa2` | `44d8f5a` | DesignSystem + App | 10 XCTest; Russian shell tabs |
| W10-T02 | `2476a86522461a1657c78c71528a5f17b5ea6bb5` | `6010713` | APIModels/Security/Networking | 15 XCTest; loopback-first client; Keychain mock |
| W10-T03 | `d6e54a57d39b6151190980215e1886c31c8b3fcc` | `4490c90` | Pairing + Dashboard | 13 XCTest |
| W10-T04 | `82905f4b705e2bfefe6c1f369fae034188835078` | `ffc969f` | Conversation + Voice | 13 XCTest |
| W10-T05 | `e89bb4e0964e060e4c1389d3ac3cf93918a47b75` | `c9361cc` | Tasks + Approvals | 10 XCTest; biometric gate risk≥3 |
| W10-T06 | `bff6c4f757880b34938e796c061bf5af7db4b84e` | `160c54d` | Files/Screen/Memory/Models/Settings | 9 XCTest; no public-bind control |

### Integrator follow-up

- Renamed DTO path to `APIModels/` and narrowed `.gitignore` `models/` → `/models/` so iOS `Features/Models` is not ignored.
- iOS tests require `DEVELOPER_DIR` pointing at full Xcode (beta OK); CLT alone lacks XCTest.

### Rejected or deferred

No shipping `.ipa` / App Store project. `MarkRemoteApp` has no `@main` (library-friendly). Bonjour discovery, live video, QR images, and wiring App tabs to every Feature remain later. Wave 11 is integration/beta gates.

## Wave 11

- BASE_W11 content parent: `02c6b869014d9c17da4f2976f338bc665e55beaa`
- Spec commit: `dd4cf8f1f3011391c92d9621256c0d2f2d6ab5ac`
- Status: accepted and integrated
- Task commits: `080c555` (T01; agent `3aa6d60`)

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W11-T01 | `3aa6d60afb0896d8b650caee2e43d8752bcd17b7` | `080c555` | `tests/integration/**`, `tests/security/**`, `tests/offline/test_beta_offline_gates.py`, `docs/audit/beta-gates.md` | 17 new gate tests; full suite 597 passed / 1 skipped; ruff clean; iOS 71 XCTest; secret scan clean outside tests; license CC BY-NC |

### Integrator follow-up

- Updated `docs/audit/beta-gates.md` with exact Wave 11 counts after verification.
- No test-module stem collisions; no new ruff E501 from this wave.
- mypy remains deferred (133 pre-existing errors in tests).

### Rejected or deferred

| Item | Reason |
|---|---|
| mypy clean on `tests/` | Pre-existing debt; not part of beta-gates hardening |
| Piper TTS | Decision closed 2026-08-15; implement in W12-T01 (not Wave 11) |
| Same-LAN Desktop API bind | Decision closed 2026-08-15; implement in W12-T02; default loopback |
| Public internet / VPN / APNs | Privacy / Epic 14; not enabled |
| Commercial readiness claim | Forbidden under CC BY-NC; personal/NC only decided 2026-08-15 |
| Wire stacks into `ui.py` | Outside Wave 11 owned paths |



## User decisions recorded (2026-08-15)

Integrator-only documentation update on `integration/main`. No application code changed in this commit except docs/orchestration.

| # | Topic | Decision |
|---|---|---|
| 1 | License posture | Personal / non-commercial only (CC BY-NC aligned). No commercial-ready claims. |
| 2 | API keys | Keys remain in OpenClaw workspace secret store; no rotation required per user 2026-08-15. Use existing keys for local runs. Never commit keys; never put key material in orchestration docs, INTEGRATION_LOG, or task specs. |
| 3 | Piper TTS | Concrete choice approved. Runtime: injected `SpeechSynthesizer` wrapping local **rhasspy/piper** CLI ([MIT](https://github.com/rhasspy/piper); prefer MIT lineage, not `piper1-gpl`). Voice: **ru_RU-dmitri-medium** ([MIT](https://huggingface.co/rhasspy/piper-voices); dataset CC0). Spec: `orchestration/tasks/W12-T01.md`. Models live under gitignored `/models/` (or documented local path); no auto-download. |
| 4 | Network | iPhone on **same LAN** approved. Not public internet / not APNs product / not VPN product. Desktop Control API may bind for same-network LAN with existing auth/pairing; default remains loopback / default-secure; no "open to internet" claim. Gap vs current loopback-default mock → `W12-T02`. |
| 5 | Git remote | **Updated 2026-08-15:** local by default; when push is requested, only `alexghost82`. Never push to third-party/upstream remotes or any other org/user. Non-alexghost82 remotes: fetch OK, `pushUrl=DISABLED`. No alexghost82 Slon repo found; push remains disabled until user creates/requests repo. |

### Wave 11 deferred table (post-decision)

| Item | Status after 2026-08-15 |
|---|---|
| Piper TTS | Decision closed; implement in W12-T01 |
| Same-LAN bind | Decision closed; implement in W12-T02 |
| Public internet / VPN / APNs | Still deferred (Epic 14) |
| Commercial readiness claim | Forbidden; personal/NC only |
| mypy clean / `ui.py` wiring | Still deferred backlog |

## Wave 12

- BASE_W12 (worktree start): `0be0d2e021d67d69950e01689b76abbecdf08a33`
- Status: accepted and integrated
- Task commits: `0110dd1` (T01; agent `95b1347`), `feb6f53` (T02; agent `9a7a3da`)
- Post-wave log commit follows this file update

### Accepted

| Task | Agent commit | Integration commit | Owned paths | Verification |
|---|---|---|---|---|
| W12-T01 | `95b1347f28015e554d421cf05b8b1fbeaf707b42` | `0110dd1` | `speech/tts/piper.py`, TTS piper tests + provider guard relax, `docs/licenses/piper.md` | `pytest tests/unit/speech/tts` 29 passed; ruff clean; fake runner (no real binary/onnx); voice `ru_RU-dmitri-medium` |
| W12-T02 | `9a7a3dac7228d53e8568d954f97a0142de4db35d` | `feb6f53` | `server/bind_policy.py`, limited `server/app.py`, bind tests, `docs/audit/lan-bind.md` | `pytest tests/unit/server` 113 passed; ruff clean; loopback default; RFC1918 opt-in; wildcards/public denied; auth still 401 |

### Integrator notes

- Owned paths disjoint; T01∥T02 from `0be0d2e`; cherry-picked one commit each (no branch merge).
- CRLF dirt on legacy `main.py` / `ui.py` / `readme.md` left unstaged in agent worktrees.
- Secret scan on owned paths: no live keys.
- Piper: rhasspy/piper MIT CLI via injectable `PiperSpeechSynthesizer`; no auto-download; models under gitignored `/models/`.
- LAN: `validate_bind_host` centralizes policy; mock still does not `listen()`; docs describe iPhone same-Wi‑Fi reachability without public-internet claims.
- Final suite on integration after cherry-picks: **629 passed, 1 skipped**; `ruff check tests speech/tts server` clean.
- OpenClaw and Cursor SillyTavern clones were not modified.

### Rejected or deferred

| Item | Reason |
|---|---|
| Public internet / VPN / APNs | Epic 14; still deferred |
| `ui.py` Piper / Desktop listener wiring | Outside owned paths (closed in Wave 12 follow-up) |
| GPL `piper1-gpl` as project default | Forbidden; MIT rhasspy/piper remains documented default |
| Auto-download of ONNX voices | Forbidden by W12-T01 |

## Wave 12 follow-up — UI Piper + live listen

- Branch / worktree: `agent/w12-followup-ui-listen` → cherry-picked to `integration/main`
- Status: integrated
- Motivation: Wave 12 left Piper injectable and bind policy documented, but `ui.py` was unwired and `DesktopControlApp` remained mock-only (no `socket.listen`).

### Accepted

| Piece | Paths | Verification |
|---|---|---|
| Piper ↔ UI | `speech/tts/local_factory.py`, `speech/tts/playback.py`, `ui.py` (LOCAL TTS toggle), factory tests | Graceful degrade when binary/onnx missing; constructs `PiperSpeechSynthesizer` → `LocalTTSProvider` under `models/piper/` |
| Live listen | `server/listener.py`, `server/__main__.py`, `server/__init__.py`, `docs/audit/lan-bind.md`, listener tests | Real loopback `listen()`; pairing + `/v1/auth/token` + route handlers; bind_policy enforced; mock `DesktopControlApp` unchanged (`listening` False until separate listener starts) |

### Integrator notes

- CLI: `python -m server` (loopback); LAN: `--allow-non-loopback` with a private host.
- UI: **LOCAL TTS** / **DESKTOP API** toggles in the right panel; `JarvisUI.enable_local_tts` / `speak_local` / `start_desktop_api`.
- Full suite after follow-up: **638 passed, 1 skipped**; ruff clean on touched packages.
- No secrets; `models/` not committed; OpenClaw / SillyTavern clones untouched.
- TLS for LAN still out of scope (personal HTTP bring-up only).

## Wave 13 planning — policy updates (2026-08-15)

- BASE_W13: `851f1559098f4c38c48fff845d3cc4f81e80cfae`
- Status: in progress

### Policy change — Piper auto-download

Wave 12 recorded **no auto-download**. User backlog Wave 13 **explicitly wants** Piper model auto-download as an **opt-in** / documented operator helper (`consent=` flag or CLI). Silent download on every process start remains forbidden. CI must stay offline (inject fetcher / skip network). Models remain under gitignored `/models/`; never commit binaries. Binary strategy: prefer brew or build-from-source on Apple Silicon — official mac aarch64 tarball historically broken.

### TLS for LAN

Epic 14 public internet / VPN / APNs still deferred. **TLS for same-LAN / loopback Desktop Control** is in Wave 13 scope (W13-T02): self-signed or mkcert; auth + bind_policy retained.

### Bonjour / QR images / live video

Wave 13 deferred; **Wave 14 implemented** — see `docs/audit/wave14-mypy-stt-discovery.md`
and updated `docs/audit/deferred-bonjour-qr-live-video.md`.

### Git push policy (2026-08-15)

**Decision:** local by default; when push is requested, only `alexghost82`. Never push to third-party/upstream remotes or any other org/user. Verified via GitHub API: alexghost82 has no Slon (or similarly named) repo among listed public repos; no push-capable remote configured. `origin` remains local path with `pushUrl=DISABLED`.


## Wave 13

- BASE_W13: `851f1559098f4c38c48fff845d3cc4f81e80cfae`
- Status: accepted and integrated (glue + TLS + Piper opt-in download + mypy reduction)
- Final HEAD after wave tasks: see `git rev-parse HEAD` on `integration/main`

### Accepted

| Task | Integration notes |
|---|---|
| W13-T01 | Opt-in `python -m speech.tts download --consent`; offline fetcher tests |
| W13-T02 | Optional TLS listener + `docs/audit/tls-lan.md`; plain HTTP rejected when TLS on |
| W13-T03 | `mark.bridge.build_runtime_stack` graceful degrade |
| W13-T04 | `main.py` wires bridge; live Gemini path retained |
| W13-T05 | `ui.py` bridge status + TLS-aware Desktop API; FileDropZone TTS init bugfix |
| W13-T06 | mypy ~144→25 (Py3.12 mypy 1.14.1); see `docs/audit/mypy-wave13.md` |
| W13-T07 | Bonjour / QR images / live video deferred — `docs/audit/deferred-bonjour-qr-live-video.md` |

### Policy notes

- Piper opt-in auto-download approved (no silent download on start).
- TLS for LAN/loopback approved; Epic 14 public internet still deferred.
- Push: local default; when explicitly requested, only account `alexghost82`. Never third-party remotes. No push in this wave.

### Verification

- Targeted + full pytest run recorded in integrator session after cherry-picks.
- No `models/` binaries committed; no secrets committed.


## Wave 14

- Status: accepted (mypy clean + STT mic + Bonjour/QR/live video)
- Docs: `docs/audit/wave14-mypy-stt-discovery.md`
- Suite: 661 passed, 4 skipped; mypy 0 errors (212 files)

| Area | Notes |
|---|---|
| mypy | 25 → 0 on configured files |
| STT mic | `speech/stt/mic.py` + factory; UI LOCAL STT LISTEN |
| Bonjour | `server/bonjour.py`, `--bonjour`, iOS `BonjourBrowser` |
| QR | `server/qr.py` + `qr_png_base64`; iOS `PairingQRCodeView` |
| Live video | `/v1/screen/frame` + `/v1/screen/stream` MJPEG |

