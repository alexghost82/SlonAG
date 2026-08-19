# FILE_OWNERSHIP — Slon

Base commit for Wave 0: `d5cf4765d983378df626fb8ed4461ad8f95d38ec` (`BASE_W0`).

## Wave 0

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W00-T01 | repo-safety | `.gitignore`, `.gitattributes` | none | everything else | `d5cf4765d983378df626fb8ed4461ad8f95d38ec` |
| W00-T02 | license-inventory | `THIRD_PARTY_LICENSES.md`, `docs/licenses/**` | none | everything else; do not create a root `LICENSE` that claims commercial rights | `d5cf4765d983378df626fb8ed4461ad8f95d38ec` |
| W00-T03 | user-change-boundary | `docs/audit/user-changes.md` | none | application code; OpenClaw secrets, memory, `.venv`, `macos-app/` | `d5cf4765d983378df626fb8ed4461ad8f95d38ec` |

Rules:

- `owned_paths` do not overlap inside a wave.
- Changes outside `owned_paths` are forbidden.
- If a foreign file is required, the agent stops and files a change request.
- Shared files (`main.py`, `ui.py`, `or_client.py`, `requirements.txt`, `config/__init__.py`) have no Wave 0 owner.
- Wave 0 is integrated. Wave 1 ownership applies only after the post-wave integration commit.
- Wave 1 is integrated. Wave 2 ownership starts from the post-wave integration commit.
- Wave 2 is integrated. Wave 3 adapters start from the post-wave integration commit.
- Wave 3 is integrated. Wave 4 router starts from the post-wave integration commit.
- Wave 4 is integrated. Wave 5 runtime/speech starts from the post-wave integration commit.
- Wave 5 is integrated. Wave 6 vision/docs/memory starts from the post-wave integration commit.
- Wave 6 is integrated. Wave 7 tool safety starts from the post-wave integration commit.
- Wave 7 is integrated. Wave 8 NetworkPolicy starts from the post-wave integration commit.
- Wave 8 is integrated. Wave 9 Desktop Control API starts from the post-wave integration commit.
- Wave 9 is integrated. Wave 10 iOS starts from the post-wave integration commit.
- Wave 10 is integrated. Wave 11 integration/beta gates start from the post-wave integration commit.
- Wave 11 is integrated.
- Wave 12 is integrated (BASE_W12 `0be0d2e021d67d69950e01689b76abbecdf08a33`).
- Wave 13 ownership starts from BASE_W13 `851f1559098f4c38c48fff845d3cc4f81e80cfae`.

## Wave 13

Post–Wave 12 follow-up. T01∥T02∥T03 first; then T04→T05 serial; T06 after glue; T07 docs-only deferred notice.

Base commit for Wave 13: `851f1559098f4c38c48fff845d3cc4f81e80cfae` (`BASE_W13`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W13-T01 | piper-auto-download | `speech/tts/download.py`, `speech/tts/__main__.py`, `tests/unit/speech/tts/test_download.py`, `docs/licenses/piper.md` | opt-in consent download | `ui.py`, `main.py`, `server/**`, silent download | `851f1559098f4c38c48fff845d3cc4f81e80cfae` |
| W13-T02 | tls-lan-api | `server/tls.py`, `server/listener.py`, `server/__main__.py`, `tests/unit/server/test_tls.py`, `docs/audit/tls-lan.md` | optional HTTPS listener | weaken auth/bind, `speech/**`, `ui.py`, `main.py` | `851f1559098f4c38c48fff845d3cc4f81e80cfae` |
| W13-T03 | runtime-bridge | `mark/bridge/**`, `tests/unit/bridge/**` | `build_runtime_stack` | `main.py`, `ui.py`, `server/**` | `851f1559098f4c38c48fff845d3cc4f81e80cfae` |
| W13-T04 | main-py-glue | `main.py`, `tests/unit/main/**` or `tests/unit/integration/test_main_glue.py` | uses bridge | `ui.py`, rewrite Gemini Live | after T03 |
| W13-T05 | ui-py-glue | `ui.py`, `tests/unit/ui/**` | uses bridge + TLS API | `main.py`, server impl | after T02+T03 |
| W13-T06 | mypy-cleanup | type fixes in new stack + `docs/audit/mypy-wave13.md`; limited `pyproject.toml` files list only | mypy without weaken | `ignore_errors` global, delete tests | after T01–T05 |
| W13-T07 | deferred-discovery-video | `docs/audit/deferred-bonjour-qr-live-video.md` | none | implementing Bonjour/live video | `851f1559098f4c38c48fff845d3cc4f81e80cfae` |

## Wave 12

Post-beta backlog. T01 and T02 have disjoint owned_paths and ran in parallel.

Base commit for Wave 12: `0be0d2e021d67d69950e01689b76abbecdf08a33` (`BASE_W12`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W12-T01 | piper-tts | `speech/tts/piper.py`, `tests/unit/speech/tts/test_piper.py`, `tests/unit/speech/tts/test_provider.py` (relax Wave 5 anti-piper guard only), optional `docs/licenses/piper.md` | inject into `SpeechSynthesizer` / `tts_local` | `ui.py`, STT, auto-download, GPL default, requirements hard-pin of piper1-gpl, `server/**` | `0be0d2e021d67d69950e01689b76abbecdf08a33` |
| W12-T02 | lan-bind | `server/bind_policy.py` (new), limited `server/app.py`, `tests/unit/server/test_app_bind.py`, `tests/unit/server/test_lan_bind.py`, optional `docs/audit/lan-bind.md` | Desktop Control bind rules | wildcard public bind, APNs/VPN, weaken auth, `speech/**` | `0be0d2e021d67d69950e01689b76abbecdf08a33` |

## Wave 11

Wave 11 is integrated. Single serial verification task. Application code stayed read-only.

Base commit for Wave 11: `02c6b869014d9c17da4f2976f338bc665e55beaa` (`BASE_W11` content parent); specs at `dd4cf8f1f3011391c92d9621256c0d2f2d6ab5ac`.

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W11-T01 | beta-gates | `tests/integration/**`, `tests/security/**`, `tests/offline/test_beta_offline_gates.py`, `docs/audit/beta-gates.md` | beta readiness checklist + gate suites | `ui.py`, app/server/ios trees, existing unit tests, licenses (read-only) | `dd4cf8f1f3011391c92d9621256c0d2f2d6ab5ac` |

## Wave 10

Wave 10 is integrated. `ios/Package.swift` remained integrator-owned. T01∥T02 first; T03–T06 after foundation.

Base commits: scaffold `cc9cfa8` / APIModels fix `b8734e9`; features from `5ae8cd2`.

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W10-T01 | design-system | `ios/MarkRemote/DesignSystem/**`, `ios/MarkRemote/App/**`, `ios/Tests/DesignSystemTests/**` | SwiftUI tokens + app shell | Package.swift, Networking, Features | `b8734e9a9bc215507681aacd4ead17fc5625e50d` |
| W10-T02 | networking | `ios/MarkRemote/{APIModels,Security,Networking}/**`, Networking tests | Desktop `/v1` client + Keychain | Package.swift, DesignSystem, Features | `b8734e9a9bc215507681aacd4ead17fc5625e50d` |
| W10-T03 | feature-pairing-dashboard | `Features/Pairing/**`, `Features/Dashboard/**`, PairingDashboardTests | pairing + dashboard UX | Package.swift, other Features | `5ae8cd2800f8c1090c495a03e44952731ce4f7f9` |
| W10-T04 | feature-conversation-voice | `Features/Conversation/**`, `Features/Voice/**`, ConversationVoiceTests | chat + voice UX | Package.swift, other Features | `5ae8cd2800f8c1090c495a03e44952731ce4f7f9` |
| W10-T05 | feature-tasks-approvals | `Features/Tasks/**`, `Features/Approvals/**`, TasksApprovalsTests | tasks + biometric approvals | Package.swift, other Features | `5ae8cd2800f8c1090c495a03e44952731ce4f7f9` |
| W10-T06 | feature-files-screen-memory-models-settings | Files/Screen/Memory/Models/Settings + tests | computer + settings UX | Package.swift, other Features; no public bind toggle | `5ae8cd2800f8c1090c495a03e44952731ce4f7f9` |

## Wave 9

Wave 9 is integrated. W09-T01 was serial; T02–T04 ran after T01.

Base commit for Wave 9: `22889a283c38a178c08ec22c2230386ce756f41c` (`BASE_W9`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W09-T01 | api-schemas-mock | `server/__init__.py`, `server/schemas.py`, `server/app.py`, schema/bind tests | `/v1` schemas, loopback mock app | pairing, auth, routes | `22889a283c38a178c08ec22c2230386ce756f41c` |
| W09-T02 | pairing | `server/pairing.py`, `tests/unit/server/test_pairing.py` | pairing start/complete/revoke | app, schemas, auth, routes | `9bb2beb05b2aadbe904395b72f3b15aac56025cc` |
| W09-T03 | auth-permissions | `server/auth.py`, `server/permissions.py`, auth/permissions tests | tokens, revoke, rate limit | pairing, app, routes | `9bb2beb05b2aadbe904395b72f3b15aac56025cc` |
| W09-T04 | api-routes | `server/routes/**`, `server/websocket.py`, route/ws tests | handlers + events hub | app, schemas, pairing, auth | `9bb2beb05b2aadbe904395b72f3b15aac56025cc` |

## Wave 8

Wave 8 is integrated. Single serial task.

Base commit for Wave 8: `92c5f8b64ab7f9a58beee83e2e492519d4b3ca0e` (`BASE_W8`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W08-T01 | network-policy | `mark/network/**`, `tests/unit/network/**`, `tests/offline/test_network_offline.py` | `NetworkPolicy`, `NetworkMode` | router, adapters, `ui.py`, safety writes | `92c5f8b64ab7f9a58beee83e2e492519d4b3ca0e` |

## Wave 7

Wave 7 is integrated. W07-T01 was serial; T02–T05 ran after T01.

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W07-T01 | safety-policy-contracts | `mark/safety/**`, `tests/unit/safety/**` | `authorize`, `UnknownToolError`, risk 0–4 | executor, actions, fallback/cost | `7eb6eb9d24982c9c867bec677551bf60c96bb1ea` |
| W07-T02 | executor-no-codegen | `agent/executor.py`, `tests/unit/agent/**` | uses SafetyPolicy | `mark/safety/**`, `actions/**` | `d2e309adf389c71989d57633ea1d85c7e904acd0` |
| W07-T03 | file-controller-safe | `actions/file_controller.py`, `tests/unit/actions/test_file_controller.py` | uses SafetyPolicy | executor, desktop, reminder | `d2e309adf389c71989d57633ea1d85c7e904acd0` |
| W07-T04 | desktop-typed-ops | `actions/desktop.py`, `tests/unit/actions/test_desktop.py` | typed ops only | executor, `or_client.py`, exec sandbox | `d2e309adf389c71989d57633ea1d85c7e904acd0` |
| W07-T05 | reminder-safe | `actions/reminder.py`, `tests/unit/actions/test_reminder.py` | JSON payload, no shell=True | executor, file_controller, desktop | `d2e309adf389c71989d57633ea1d85c7e904acd0` |

## Wave 6

Wave 6 is integrated. T01, T02, and T03 ran in parallel. Legacy `memory/` was not edited.

Base commit for Wave 6: `0b57e39a4e4c503abe97b068a9b0a70645acd02d` (`BASE_W6`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W06-T01 | vision | `mark/vision/**`, `tests/unit/vision/**` | `VisionProvider`, `vision_local` | documents, memory, contracts, requirements | `0b57e39a4e4c503abe97b068a9b0a70645acd02d` |
| W06-T02 | documents | `mark/documents/**`, `tests/unit/documents/**` | ingest + guards | vision, memory, providers, requirements | `0b57e39a4e4c503abe97b068a9b0a70645acd02d` |
| W06-T03 | memory-sqlite | `mark/memory/**`, `tests/unit/memory/**` | propose/commit SQLite | legacy `memory/**`, vision, documents, `or_client.py` | `0b57e39a4e4c503abe97b068a9b0a70645acd02d` |

## Wave 5

Wave 5 is integrated. T01, T02, and T03 ran in parallel. Piper was not implemented.

Base commit for Wave 5: `a1044fc7f3d467cb4451af4d2f1a5b5c6b671874` (`BASE_W5`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W05-T01 | local-runtime-manager | `mark/runtime/**`, `tests/unit/runtime/**` | process/catalog manager | `speech/**`, `providers/**`, `ui.py`, requirements, i18n | `a1044fc7f3d467cb4451af4d2f1a5b5c6b671874` |
| W05-T02 | stt | `speech/stt/**`, `tests/unit/speech/stt/**` | `SpeechToTextProvider`, `stt_local` | `speech/__init__.py`, `speech/tts/**`, runtime, requirements | `a1044fc7f3d467cb4451af4d2f1a5b5c6b671874` |
| W05-T03 | tts | `speech/tts/**`, `tests/unit/speech/tts/**` | `TextToSpeechProvider`, `tts_local` | Piper, `speech/__init__.py`, `speech/stt/**`, runtime, requirements | `a1044fc7f3d467cb4451af4d2f1a5b5c6b671874` |

## Wave 4

Wave 4 is integrated. W04-T01 was serial; T02 and T03 ran after T01.

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W04-T01 | router | `providers/router.py`, `tests/unit/providers/test_router.py` | `FallbackPolicy`, `Router` | adapters, `ui.py`, `policies/**` | `BASE_W4` |
| W04-T02 | roles-fallback-cost | `policies/**`, `tests/unit/policies/**` | implements `FallbackPolicy` | `providers/router.py`, `ui.py` | `e0d972c526193f1b1d381e15cc001c9050cf1148` |
| W04-T03 | setup-wizard-ui | `mark/app/**`, `tests/unit/app/**` | wizard state | `ui.py`, `i18n/**`, `providers/router.py` | `e0d972c526193f1b1d381e15cc001c9050cf1148` |

## Wave 3

Base commit for Wave 3: `8a43140d2f7ff19c59b96323c86ae53afe2e38c0` (`BASE_W3`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W03-T01 | gemini-adapter | `providers/gemini/**`, `tests/unit/providers/gemini/**` | `ChatProvider`, `register("gemini")` | router, other adapters, contracts modules | `8a43140d2f7ff19c59b96323c86ae53afe2e38c0` |
| W03-T02 | openai-adapter | `providers/openai/**`, `tests/unit/providers/openai/**` | `ChatProvider`, `register("openai")` | router, requirements, other adapters | `8a43140d2f7ff19c59b96323c86ae53afe2e38c0` |
| W03-T03 | openrouter-adapter | `providers/openrouter/**`, `tests/unit/providers/openrouter/**` | `ChatProvider`, `register("openrouter")` | `or_client.py`, router, fallback lists | `8a43140d2f7ff19c59b96323c86ae53afe2e38c0` |
| W03-T04 | local-adapters | `providers/local/**`, `tests/unit/providers/local/**` | `ChatProvider`, `register("local"|"ollama"|"llama_cpp")` | router, cloud adapters, model downloads | `8a43140d2f7ff19c59b96323c86ae53afe2e38c0` |

## Wave 2

Base commit for Wave 2: `a3961db5e9047d5bc757af2ffd334b6246e26c4b` (`BASE_W2`).

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W02-T01 | i18n-framework | `localization/**`, `i18n/ru.json`, `i18n/en.json`, `tests/unit/localization/**` | `tr(key, **kwargs)` | `ui.py`, `config/**`, `providers/**` | `a3961db5e9047d5bc757af2ffd334b6246e26c4b` |
| W02-T02 | provider-contracts | `providers/__init__.py`, `providers/contracts.py`, `providers/capabilities.py`, `providers/errors.py`, `providers/registry.py`, `tests/unit/providers/**` | Chat/Vision/STT/TTS protocols, `ModelInfo` | `providers/router.py`, adapters, `or_client.py`, `ui.py` | `a3961db5e9047d5bc757af2ffd334b6246e26c4b` |

## Wave 1

Base commit for Wave 1: `84c9a05f6b9984293a00205c827ddafc54f22a85` (`BASE_W1`).

`tests/**` is split. W01-T03 owns the harness only.

| Task ID | Agent | Owned paths | Shared contracts | Forbidden paths | Base commit |
|---|---|---|---|---|---|
| W01-T01 | config-stack | `config/**`, `tests/unit/config/**` | `get_config`, `get_os`, `is_*` | requirements, pyproject, other test trees | `84c9a05f6b9984293a00205c827ddafc54f22a85` |
| W01-T02 | requirements-split | `requirements-base.txt`, `requirements-macos.txt`, `requirements-windows.txt`, `requirements-linux.txt`, `requirements.txt`, `setup.py`, `tests/unit/requirements/**` | none | `requirements-dev.txt`, `pyproject.toml`, `config/**` | `84c9a05f6b9984293a00205c827ddafc54f22a85` |
| W01-T03 | test-foundation | `pyproject.toml`, `requirements-dev.txt`, `tests/conftest.py`, `tests/__init__.py`, `tests/README.md`, `tests/unit/test_foundation.py`, `.github/workflows/ci.yml` | pytest/ruff commands | sibling test trees, runtime requirements | `84c9a05f6b9984293a00205c827ddafc54f22a85` |
| W01-T04 | game-updater-guard | `actions/game_updater.py`, `tests/unit/actions/test_game_updater.py` | none | other `actions/*`, requirements, config | `84c9a05f6b9984293a00205c827ddafc54f22a85` |
