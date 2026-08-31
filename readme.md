# Slon — AI Assistant Runtime Engine

**Slon** is a cross-platform AI assistant runtime engine with voice interface, desktop control, and a toolbox of automation actions. It aggregates LLM providers (Google Gemini, OpenAI, OpenRouter, local models via Ollama / LlamaCPP), manages tasks through a planner, and provides both a PyQt6 desktop GUI and a headless server API.

## Features

- **Multi-provider** — Gemini, OpenAI, OpenRouter, Ollama, and LlamaCPP through a unified `providers/` interface
- **Voice I/O** — STT (Whisper) and TTS (Piper) for hands-free interaction
- **Desktop control** — window management, screenshots, keyboard/mouse simulation, clipboard (pyautogui, mss, cv2)
- **Actions (actions/)** — web search, weather, browser automation, YouTube, file management, reminders, messaging, code assistance, shell execution
- **Task planner** — `agent/planner.py` + `task_queue` for prioritized async execution
- **Memory** — long-term storage via `memory/memory_manager.py`
- **Sessions** — session manager with transcripts and migrations (`sessions/`)
- **Gateway** — authenticated authorization, approval gates, websockets, and device pairing
- **Live Video** — camera streaming via the server (`server/live_video.py`)
- **Policies** — cost management and fallback strategies (`policies/`)
- **i18n** — Russian/English localization (`i18n/`, `localization/`)
- **Server** — REST + WebSocket API with TLS, QR pairing, and Bonjour discovery

## Architecture

```
main.py                  ← Entry point: initializes UI, agent runtime, and lifecycle
ui/                      ← PyQt6 GUI (SlonUI / JarvisUI)
├── actions/             ← Tool actions (web_search, weather, browser, shell_exec, ...)
├── agent/               ← Planner, executor, error handler, steering, latency
├── config/              ← Settings schema, secrets loader, onboarding
├── computer_control/    ← Platform-specific desktop control (_macos, _linux, _windows)
├── core/prompt.txt      ← System prompt for the assistant
├── gateway/             ← Authenticated gateway: auth, bootstrap, router, websocket, approvals
├── i18n/                ← i18n JSON dictionaries (ru, en)
├── localization/        ← Python i18n translator and locale scanner
├── mark/                ← Runtime bridge, desktop control plane, safety, MCP tools
├── memory/              ← Long-term memory and config manager
├── orchestration/       ← Sub-task orchestration and dependency tracking
├── policies/            ← Cost control, fallback strategies
├── proactive/           ← Proactive scheduling, cooldown, loop detection
├── providers/           ← Provider abstraction (OpenAI-compatible, router, capabilities)
│   ├── gemini/          ← Google Gemini adapter
│   ├── openai/          ← OpenAI adapter
│   ├── openrouter/      ← OpenRouter adapter
│   └── local/           ← Ollama and LlamaCPP adapters
├── runtime/             ← Audio pipeline, lifecycle, benchmark, tool bridge
├── server/              ← HTTP/WS server: TLS, QR, Bonjour, live video, pairing
├── sessions/            ← Session store, transcripts, migrations
├── speech/              ← STT (Whisper) and TTS (Piper) engines
├── tests/               ← Pytest test suite (unit, integration, security, offline)
└── workflow_learning/   ← Confidence tracking and observation store
```

## Supported Platforms

| Platform | Minimum version | Notes |
|----------|----------------|-------|
| macOS    | 12 (Monterey)  | Full feature set; desktop control via macOS Accessibility API |
| Linux    | Ubuntu 20.04+  | X11/Wayland; requires `libx11-dev`, `libxrandr-dev`, `libgtk-3-dev` |
| Windows  | 10             | Full feature set; COM-based window management |

**Python:** 3.11 – 3.12 (exclusive of 3.13)
**RAM:** ≥ 4 GB (8 GB recommended); more required for local models

## Installation

### Prerequisites

- **Python 3.11** or **3.12**
- **git**

### macOS

```bash
# 1. Install Python 3.12 (if not present)
brew install python@3.12

# 2. Clone the repository
git clone https://github.com/alexghost82/SlonAG.git
cd SlonAG/SlonAG-fix-worktrees/25  # adjust path as needed

# 3. Create a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
python setup.py

# 5. (Optional) Verify with tests
python -m pytest tests/unit -q
```

### Ubuntu (Linux)

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip \
    build-essential alsa-utils libasound2-dev \
    portaudio19-dev libx11-dev libxrandr-dev \
    libgtk-3-dev

# 2. Clone the repository
git clone https://github.com/alexghost82/SlonAG.git
cd SlonAG

# 3. Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
python setup.py
```

### Windows

```powershell
# 1. Install Python 3.11+ from python.org (check "Add to PATH")

# 2. Clone the repository
git clone https://github.com/alexghost82/SlonAG.git
cd SlonAG

# 3. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 4. Install dependencies
python setup.py
```

## Configuration

### API Keys

Obtain API keys and add them via the GUI **Settings** panel, or create `config/api_keys.json`:

```json
{
  "gemini_api_key": "YOUR_GEMINI_KEY",
  "openai_api_key": "YOUR_OPENAI_KEY",
  "ollama_api_key": ""
}
```

Secrets files (`config/api_keys.json`, `config/settings.json`, `config/settings.local.json`) are git-ignored.

### Selecting a Provider

In the GUI, open **Settings** and choose a provider — Gemini, OpenAI, OpenRouter, Ollama, or LlamaCPP — along with the specific model. For local models, ensure the corresponding backend is running (e.g., `ollama serve` for Ollama).

### Local Models

- **Ollama:** `ollama pull <model_name>` (e.g., `ollama pull llama3.2`), then select Ollama in settings.
- **LlamaCPP:** requires `llama-cpp-python` compiled for your platform.

## Running

### Desktop GUI (recommended)

```bash
python main.py
```

Launches the PyQt6 application with a chat interface, logs, settings, and voice controls.

### Server (headless / API mode)

```bash
python -m server
```

Starts the HTTP + WebSocket server on the loopback address by default. Supports TLS, QR device pairing, and Bonjour LAN discovery. Desktop control binds are restricted to loopback unless explicitly allowed.

### iOS Remote Client

The `ios/` directory contains a Swift package (`MarkRemote`) and an Xcode project for an iOS remote that communicates with the desktop server via the Desktop Control API.

## Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run the unit test suite
python -m pytest tests/unit -q

# Run full suite (integration + security + offline)
python -m pytest tests/ -q

# Lint with Ruff (scoped to tests/)
ruff check .

# Type-check (scoped in pyproject.toml)
mypy
```

Tests are isolated — they do not require `config/api_keys.json` or network access to run.

## Privacy & Security

- **Local-first:** Desktop control and most processing run on the local machine.
- **API keys are local:** Credentials are stored in `config/api_keys.json` and never leave the machine.
- **Server binds to loopback by default:** LAN access requires explicit opt-in via `allow_non_loopback=True`; public/internet binds are denied.
- **Filesystem security gates:** The `tests/test_filesystem_security.py` suite verifies write/copy/delete operations are scoped to allowed roots.
- **Gateway auth:** All API requests pass through the gateway's authorization context with device-level tokens.
- **TLS enforced** for non-lab deployments.
- **No telemetry:** The runtime does not send usage data externally.

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| `gemini_api_key` missing error | No key in settings or `api_keys.json` | Add key via GUI Settings or `config/api_keys.json` |
| Import error for `playwright` | Browser binaries not installed | Run `python -m playwright install` |
| Audio not working | Missing PortAudio / PyAudio build deps | Install `portaudio19-dev` (Linux) or reinstall `pyaudio` |
| Desktop control fails on Linux | Missing X11/display libraries | Install `libx11-dev`, `libxrandr-dev`, `libgtk-3-dev` |
| Server won't bind | Port already in use | Change the bind port in server settings |

## License

CC BY-NC 4.0 — non-commercial use with attribution. Third-party dependencies are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
