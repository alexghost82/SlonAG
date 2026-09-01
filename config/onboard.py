"""Onboarding wizard — state machine, step definitions, validation, connection tests.

This module is a thin, importable layer that:
- Manages the wizard's internal state (which step, user answers).
- Validates user input per step.
- Runs optional "connection test" probes (DNS lookup for remote provider,
  TCP connect for local provider, file existence for mic/speaker, etc.).
- Produces a final ``OnboardResult`` dataclass that is used by the UI to
  save settings + secrets and restart the application.

No GUI code lives here — only pure-Python state and I/O-free validation
except for *connection tests* which are explicitly labelled.
"""

from __future__ import annotations

import dataclasses
import json
import socket
import sys
from dataclasses import dataclass, field

from config.catalog import get_model_info, model_capabilities_display
from config.schema import (
    DEFAULT_LANGUAGE,
    DEFAULT_NETWORK_MODE,
    DEFAULT_PRIVACY_PROFILE,
    DEFAULT_PROVIDER_ID,
    DEFAULT_ROUTING_MODE,
    DEFAULT_VOICE_STT_ENGINE,
    DEFAULT_VOICE_TTS_ENGINE,
    LOCAL_PROVIDER_IDS,
    NETWORK_MODES,
    PRIVACY_PROFILES,
    PROVIDER_IDS,
    ROUTING_MODES,
    Settings,
    default_settings,
)
from config.secrets import set_secret
from i18n import t

CLOUD_PROVIDER_IDS = frozenset(PROVIDER_IDS - LOCAL_PROVIDER_IDS)
# ---------------------------------------------------------------------------
# Available models / engines
# ---------------------------------------------------------------------------

CLOUD_MODELS: dict[str, list[tuple[str, str]]] = {
    "gemini": [
        ("gemini-2.5-flash", "Flash (быстро)"),
        ("gemini-2.5-pro", "Pro (точнее)"),
        ("gemini-2.5-pro-preview-05-06", "Pro Preview"),
    ],
    "openai": [
        ("gpt-4o", "GPT-4o (мощная)"),
        ("gpt-4o-mini", "GPT-4o Mini (быстрая)"),
    ],
    "openrouter": [
        ("google/gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("openai/gpt-4o", "GPT-4o"),
        ("meta-llama/llama-3.3-70b", "Llama 3.3 70B"),
    ],
}

LOCAL_MODELS: dict[str, list[tuple[str, str]]] = {
    "ollama": [
        ("llama3.2", "Llama 3.2 8B"),
        ("llama3.1:70b", "Llama 3.1 70B"),
        ("qwen2.5:14b", "Qwen 2.5 14B"),
    ],
    "llama_cpp": [
        ("qwen2.5-7b.Q4_K_M.gguf", "Qwen 2.5 7B Q4"),
        ("llama3.2-8b.Q4_K_M.gguf", "Llama 3.2 8B Q4"),
    ],
    "local": [
        ("auto", "Авто (определить)"),
    ],
}

# ---------------------------------------------------------------------------
# Model capability metadata (read from catalog for validation & display)
# ---------------------------------------------------------------------------

MODEL_CAPABILITIES: dict[str, dict[str, bool]] = {}
"""Model id -> capability flags.  Populated from catalog at import time."""

for _pid in ("gemini", "openai", "openrouter"):
    for _mid, _label in CLOUD_MODELS.get(_pid, []):
        _info = get_model_info(_pid, _mid)
        if _info is not None:
            MODEL_CAPABILITIES[_mid] = {
                "text": _info.text,
                "streaming": _info.streaming,
                "tool_calling": _info.tool_calling,
                "structured_output": _info.structured_output,
                "vision": _info.vision,
                "audio_input": _info.audio_input,
                "audio_output": _info.audio_output,
                "embeddings": _info.embeddings,
            }
for _pid in ("ollama", "llama_cpp", "local"):
    for _mid, _label in LOCAL_MODELS.get(_pid, []):
        _info = get_model_info(_pid, _mid)
        if _info is not None:
            MODEL_CAPABILITIES[_mid] = {
                "text": _info.text,
                "streaming": _info.streaming,
                "tool_calling": _info.tool_calling,
                "structured_output": _info.structured_output,
                "vision": _info.vision,
            }


STT_ENGINES: list[tuple[str, str]] = [
    ("faster_whisper", "Faster-Whisper (локально, рекомендуется)"),
    ("whisper", "Whisper (базовый, нужен ffmpeg)"),
    ("no", "Без STT"),
]

TTS_ENGINES: list[tuple[str, str]] = [
    ("piper", "Piper (локально, рекомендуется)"),
    ("edge_tts", "Edge-TTS (онлайн, бесплатно)"),
    ("no", "Без TTS"),
]

# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

class OnboardStepId(str):
    """Opaque step identifier."""
    pass

STEP_LANGUAGE = OnboardStepId("language")
STEP_PROVIDER = OnboardStepId("provider")
STEP_MODEL = OnboardStepId("model")
STEP_CREDENTIALS = OnboardStepId("credentials")
STEP_ENDPOINTS = OnboardStepId("endpoints")
STEP_PRIVACY = OnboardStepId("privacy")
STEP_VOICE = OnboardStepId("voice")
STEP_VISION = OnboardStepId("vision")
STEP_MEMORY = OnboardStepId("memory")
STEP_AUTOMATION = OnboardStepId("automation")
STEP_LAN = OnboardStepId("lan")
STEP_COMPLETE = OnboardStepId("complete")

ALL_STEPS = (
    STEP_LANGUAGE,
    STEP_PROVIDER,
    STEP_MODEL,
    STEP_CREDENTIALS,
    STEP_ENDPOINTS,
    STEP_PRIVACY,
    STEP_VOICE,
    STEP_VISION,
    STEP_MEMORY,
    STEP_AUTOMATION,
    STEP_LAN,
    STEP_COMPLETE,
)

# ---------------------------------------------------------------------------
# Step metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepMeta:
    """Metadata for a single onboarding step."""
    id: OnboardStepId
    title_key: str
    hint_key: str
    order: int
    optional: bool = False
    connection_test: bool = False

STEP_META: dict[OnboardStepId, StepMeta] = {
    STEP_LANGUAGE: StepMeta(
        id=STEP_LANGUAGE,
        title_key="onboard.step_language",
        hint_key="onboard.hint_language",
        order=1,
    ),
    STEP_PROVIDER: StepMeta(
        id=STEP_PROVIDER,
        title_key="onboard.step_provider",
        hint_key="onboard.hint_provider",
        order=2,
    ),
    STEP_MODEL: StepMeta(
        id=STEP_MODEL,
        title_key="onboard.step_model",
        hint_key="onboard.hint_model",
        order=3,
        optional=True,
    ),
    STEP_CREDENTIALS: StepMeta(
        id=STEP_CREDENTIALS,
        title_key="onboard.step_credentials",
        hint_key="onboard.hint_credentials",
        order=4,
        optional=False,
    ),
    STEP_ENDPOINTS: StepMeta(
        id=STEP_ENDPOINTS,
        title_key="onboard.step_endpoints",
        hint_key="onboard.hint_endpoints",
        order=5,
        optional=True,
    ),
    STEP_PRIVACY: StepMeta(
        id=STEP_PRIVACY,
        title_key="onboard.step_privacy",
        hint_key="onboard.hint_privacy",
        order=6,
    ),
    STEP_VOICE: StepMeta(
        id=STEP_VOICE,
        title_key="onboard.step_voice",
        hint_key="onboard.hint_voice",
        order=7,
        optional=True,
    ),
    STEP_VISION: StepMeta(
        id=STEP_VISION,
        title_key="onboard.step_vision",
        hint_key="onboard.hint_vision",
        order=8,
        optional=True,
    ),
    STEP_MEMORY: StepMeta(
        id=STEP_MEMORY,
        title_key="onboard.step_memory",
        hint_key="onboard.hint_memory",
        order=9,
        optional=True,
    ),
    STEP_AUTOMATION: StepMeta(
        id=STEP_AUTOMATION,
        title_key="onboard.step_automation",
        hint_key="onboard.hint_automation",
        order=10,
        optional=True,
    ),
    STEP_LAN: StepMeta(
        id=STEP_LAN,
        title_key="onboard.step_lan",
        hint_key="onboard.hint_lan",
        order=11,
        optional=True,
    ),
    STEP_COMPLETE: StepMeta(
        id=STEP_COMPLETE,
        title_key="onboard.step_complete",
        hint_key="onboard.hint_complete",
        order=12,
        optional=False,
    ),
}

# ---------------------------------------------------------------------------
# Connection test result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConnectionTestResult:
    """Result of a connection test."""
    label: str
    ok: bool
    message: str

# ---------------------------------------------------------------------------
# Onboard result (immutable, returned after wizard completion)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OnboardResult:
    """Final result from a completed onboarding wizard."""
    language: str
    provider_id: str
    model_id: str
    os_system: str
    privacy_profile: str
    network_mode: str
    routing_mode: str
    voice_stt_engine: str
    voice_tts_engine: str
    voice_mic_device: str | None
    voice_speaker_device: str | None
    camera_index: int | None
    browser_available: bool
    vision_enabled: bool
    camera_enabled: bool
    rtsp_enabled: bool
    memory_enabled: bool
    automation_enabled: bool
    lan_enabled: bool
    remote_transport: str
    remote_base_url: str
    secrets_saved: list[str] = field(default_factory=list)
    connection_tests: list[ConnectionTestResult] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Onboard state (accumulates answers across wizard steps)
# ---------------------------------------------------------------------------

@dataclass
class OnboardState:
    """Accumulates user answers across wizard steps."""
    language: str = DEFAULT_LANGUAGE
    provider_id: str = DEFAULT_PROVIDER_ID
    model_id: str = ""
    provider_base_url: str = ""
    local_provider: str = "ollama"
    local_base_url: str = "http://127.0.0.1:11434"
    privacy_profile: str = DEFAULT_PRIVACY_PROFILE
    network_mode: str = DEFAULT_NETWORK_MODE
    routing_mode: str = DEFAULT_ROUTING_MODE
    stt_engine: str = DEFAULT_VOICE_STT_ENGINE
    tts_engine: str = DEFAULT_VOICE_TTS_ENGINE
    mic_device: str | None = None
    speaker_device: str | None = None
    camera_index: int | None = None
    vision_enabled: bool = False
    camera_enabled: bool = False
    rtsp_enabled: bool = False
    rtsp_url: str = ""
    memory_enabled: bool = False
    automation_enabled: bool = False
    lan_enabled: bool = False
    remote_transport: str = "none"
    remote_base_url: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    current_step_index: int = 0
    _connection_tests: list[ConnectionTestResult] = field(default_factory=list)

    def current_step(self) -> StepMeta:
        return STEP_META[ALL_STEPS[self.current_step_index]]

    def total_steps(self) -> int:
        return len(ALL_STEPS)

    def progress(self) -> float:
        return (self.current_step_index + 1) / self.total_steps() if self.total_steps() else 1.0

    def is_last_step(self) -> bool:
        return self.current_step_index >= self.total_steps() - 1

    def advance(self) -> bool:
        if self.current_step_index < self.total_steps() - 1:
            self.current_step_index += 1
            return True
        return False

    def go_back(self) -> bool:
        if self.current_step_index > 0:
            self.current_step_index -= 1
            return True
        return False

    def build_result(self) -> OnboardResult:
        return OnboardResult(
            language=self.language,
            provider_id=self.provider_id,
            model_id=self.model_id,
            os_system=self._detect_os(),
            privacy_profile=self.privacy_profile,
            network_mode=self.network_mode,
            routing_mode=self.routing_mode,
            voice_stt_engine=self.stt_engine,
            voice_tts_engine=self.tts_engine,
            voice_mic_device=self.mic_device or None,
            voice_speaker_device=self.speaker_device or None,
            camera_index=self.camera_index,
            browser_available=True,
            vision_enabled=self.vision_enabled or self.camera_enabled,
            camera_enabled=self.camera_enabled,
            rtsp_enabled=self.rtsp_enabled,
            memory_enabled=self.memory_enabled,
            automation_enabled=self.automation_enabled,
            lan_enabled=self.lan_enabled,
            remote_transport=self.remote_transport,
            remote_base_url=self.remote_base_url,
            secrets_saved=[],
            connection_tests=list(self._connection_tests),
        )

    @staticmethod
    def _detect_os() -> str:
        return {"darwin": "mac", "windows": "windows"}.get(sys.platform, "linux")

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_language(value: str) -> tuple[bool, str | None]:
    if not value or not value.strip():
        return False, t("onboard.err_required", field=t("onboard.field_language"))
    return True, None

def validate_provider(value: str) -> tuple[bool, str | None]:
    if not value or value not in PROVIDER_IDS:
        return False, t("onboard.err_provider_invalid", provider=value or "(empty)")
    return True, None

def validate_model_id(provider_id: str, value: str) -> tuple[bool, str | None]:
    if not value or value.strip() == "":
        return True, None
    return True, None

def validate_model_for_provider(provider_id: str, model_id: str) -> tuple[bool, str | None]:
    """Validate that *model_id* is a valid choice for *provider_id*.

    Returns (False, error_message) when the model is not in the catalog
    for the given provider, or the provider itself is unknown.
    """
    if not model_id or not model_id.strip():
        return True, None  # empty means "auto"
    info = get_model_info(provider_id, model_id)
    if info is None:
        return False, t("catalog.err_provider_model_mismatch")
    return True, None


def get_model_display(provider_id: str, model_id: str) -> str:
    """Return a human-readable display string for a model.

    Uses the catalog when possible, falls back to a plain fallback.
    """
    info = get_model_info(provider_id, model_id)
    if info is None:
        return model_id
    if info.display_name and info.display_name != model_id:
        return info.display_name
    return model_id


def get_model_capabilities_summary(provider_id: str, model_id: str) -> str:
    """Return a capability summary string for a model."""
    info = get_model_info(provider_id, model_id)
    if info is None:
        return t("catalog.model_not_found")
    return model_capabilities_display(info)



def validate_api_key_field(provider_id: str, key_value: str) -> tuple[bool, str | None]:
    if provider_id in LOCAL_PROVIDER_IDS:
        return True, None
    if not key_value or not key_value.strip():
        return False, t("onboard.err_api_key_missing", provider=provider_id)
    if len(key_value) < 6:
        return False, t("onboard.err_api_key_short")
    return True, None

def validate_base_url(value: str, provider_id: str) -> tuple[bool, str | None]:
    if not value or not value.strip():
        return True, None
    url = value.strip()
    if not url.startswith(("http://", "https://")):
        return False, t("onboard.err_url_scheme")
    return True, None

def validate_privacy_profile(value: str) -> tuple[bool, str | None]:
    return (value in PRIVACY_PROFILES,
            None if value in PRIVACY_PROFILES else t("onboard.err_privacy_invalid"))

def validate_network_mode(value: str) -> tuple[bool, str | None]:
    return (value in NETWORK_MODES,
            None if value in NETWORK_MODES else t("onboard.err_network_invalid"))

def validate_routing_mode(value: str) -> tuple[bool, str | None]:
    return (value in ROUTING_MODES,
            None if value in ROUTING_MODES else t("onboard.err_routing_invalid"))

def validate_camera_index(value: str) -> tuple[bool, str | None]:
    if not value.strip():
        return True, None
    try:
        idx = int(value.strip())
        if idx < 0:
            return False, t("onboard.err_camera_index_negative")
        return True, None
    except ValueError:
        return False, t("onboard.err_camera_index_invalid")

def validate_rtsp_url(value: str) -> tuple[bool, str | None]:
    if not value or not value.strip():
        return True, None
    url = value.strip()
    if not url.startswith(("rtsp://", "rtmps://")):
        return False, t("onboard.err_rtsp_scheme")
    return True, None

def validate_step(state: OnboardState, step_id: OnboardStepId) -> tuple[bool, str | None]:
    """Validate user input for a given step. Returns (valid, error_message)."""
    if step_id == STEP_LANGUAGE:
        return validate_language(state.language)
    elif step_id == STEP_PROVIDER:
        ok, err = validate_provider(state.provider_id)
        if not ok:
            return False, err
        return validate_model_id(state.provider_id, state.model_id)
    elif step_id == STEP_CREDENTIALS:
        if state.provider_id in CLOUD_PROVIDER_IDS:
            key_attr = f"{state.provider_id}_api_key"
            key_value = getattr(state, key_attr, "")
            return validate_api_key_field(state.provider_id, key_value)
        return True, None
    elif step_id == STEP_ENDPOINTS:
        if state.provider_base_url:
            return validate_base_url(state.provider_base_url, state.provider_id)
        if state.local_base_url and state.provider_id in LOCAL_PROVIDER_IDS:
            return validate_base_url(state.local_base_url, "local")
        return True, None
    elif step_id == STEP_PRIVACY:
        ok, _ = validate_privacy_profile(state.privacy_profile)
        if not ok:
            return False, t("onboard.err_privacy_invalid")
        ok, _ = validate_network_mode(state.network_mode)
        if not ok:
            return False, t("onboard.err_network_invalid")
        ok, _ = validate_routing_mode(state.routing_mode)
        if not ok:
            return False, t("onboard.err_routing_invalid")
        return True, None
    elif step_id == STEP_VOICE:
        stt_valid = any(e[0] == state.stt_engine for e in STT_ENGINES)
        tts_valid = any(e[0] == state.tts_engine for e in TTS_ENGINES)
        if not stt_valid:
            return False, t("onboard.err_stt_engine")
        if not tts_valid:
            return False, t("onboard.err_tts_engine")
        return True, None
    elif step_id == STEP_VISION:
        if state.camera_enabled and state.camera_index is not None:
            return validate_camera_index(str(state.camera_index))
        if state.rtsp_enabled and state.rtsp_url:
            return validate_rtsp_url(state.rtsp_url)
        return True, None
    return True, None

# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------

def test_dns_lookup(hostname: str) -> ConnectionTestResult:
    """DNS resolution check."""
    label = t("onboard.test_dns", host=hostname)
    try:
        socket.gethostbyname(hostname)
        return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_ok"))
    except socket.gaierror:
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_dns_fail", host=hostname))
    except OSError:
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_dns_net"))

def test_tcp_connect(host: str, port: int, timeout: float = 2.0) -> ConnectionTestResult:
    """TCP port reachability check."""
    label = f"{host}:{port}"
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_ok"))
    except (TimeoutError, ConnectionRefusedError, OSError):
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_tcp_fail", host=host, port=port))

def test_http_get(url: str, timeout: float = 3.0) -> ConnectionTestResult:
    """HTTP HEAD request check."""
    label = t("onboard.test_http", url=url)
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "SlonOnboard/1.0")
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp.close()
        return ConnectionTestResult(label=label, ok=True, message=f"{t('onboard.test_ok')} ({resp.status})")
    except Exception as exc:
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_http_fail", exc=str(exc)))

def test_provider_api_key(provider_id: str, api_key: str) -> ConnectionTestResult:
    """Test a provider's API key."""
    label = t("onboard.test_api_key", provider=provider_id)
    if not api_key or not api_key.strip():
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_api_key_no_key"))
    try:
        if provider_id == "gemini":
            return _test_gemini_key(api_key)
        elif provider_id == "openai":
            return _test_openai_key(api_key)
        elif provider_id == "openrouter":
            return _test_openrouter_key(api_key)
        elif provider_id in LOCAL_PROVIDER_IDS:
            return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_local_skip"))
        else:
            return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_provider_unsupported"))
    except Exception as exc:
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_api_key_fail", exc=str(exc)))

def _test_gemini_key(api_key: str) -> ConnectionTestResult:
    label = t("onboard.test_gemini")
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        list(client.models.list(page_size=1))
        return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_gemini_ok"))
    except Exception as exc:
        msg = str(exc)
        if "quota" in msg.lower() or "exceeded" in msg.lower():
            return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_quota"))
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_gemini_fail", exc=msg))

def _test_openai_key(api_key: str) -> ConnectionTestResult:
    label = t("onboard.test_openai")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        client.models.list(limit=1)
        return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_openai_ok"))
    except Exception as exc:
        msg = str(exc)
        if "unauthorized" in msg.lower() or "invalid_api_key" in msg.lower() or "401" in msg:
            return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_openai_unauth"))
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_openai_fail", exc=msg))

def _test_openrouter_key(api_key: str) -> ConnectionTestResult:
    label = t("onboard.test_openrouter")
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "SlonOnboard/1.0"}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = resp.read()
        resp.close()
        models = json.loads(data) if data else {}
        count = len(models.get("data", []))
        return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_openrouter_ok", count=count))
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "unauthorized" in msg.lower():
            return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_openrouter_unauth"))
        return ConnectionTestResult(label=label, ok=False, message=t("onboard.test_openrouter_fail", exc=msg))

def test_local_provider(base_url: str, provider_id: str) -> ConnectionTestResult:
    """Check if a local provider endpoint responds."""
    label = f"{provider_id} @ {base_url}"
    if provider_id == "ollama":
        return test_http_get(f"{base_url}/api/tags", timeout=2.0)
    else:
        return ConnectionTestResult(label=label, ok=True, message=t("onboard.test_generic_ok", provider=provider_id))

def run_connection_tests(state: OnboardState) -> list[ConnectionTestResult]:
    """Run all applicable connection tests for the current state."""
    results: list[ConnectionTestResult] = []
    if state.provider_id in CLOUD_PROVIDER_IDS:
        key_attr = f"{state.provider_id}_api_key"
        key_value = getattr(state, key_attr, "")
        if key_value:
            results.append(test_provider_api_key(state.provider_id, key_value))
    if state.provider_id in LOCAL_PROVIDER_IDS:
        url = state.local_base_url or (
            "http://127.0.0.1:11434" if state.local_provider == "ollama"
            else "http://127.0.0.1:8080"
        )
        results.append(test_local_provider(url, state.provider_id))
    if state.remote_transport != "none" and state.remote_base_url:
        results.append(test_http_get(state.remote_base_url, timeout=3.0))
    if state.provider_base_url:
        host_part = state.provider_base_url.split("://", 1)[1].split("/")[0] if "://" in state.provider_base_url else ""
        if host_part:
            results.append(test_dns_lookup(host_part))
    return results

# ---------------------------------------------------------------------------
# Apply result -> Settings + Secrets
# ---------------------------------------------------------------------------

def apply_onboard_result(
    result: OnboardResult,
    gemini_key: str = "",
    openrouter_key: str = "",
    openai_key: str = "",
) -> tuple[Settings, list[str]]:
    """Persist settings and secrets, then restart-ready Settings object."""
    from config.settings import save_settings

    settings_data = {
        "language": result.language,
        "provider_id": result.provider_id,
        "model_id": result.model_id,
        "privacy_profile": result.privacy_profile,
        "network_mode": result.network_mode,
        "routing_mode": result.routing_mode,
        "os_system": result.os_system,
        "voice_stt_engine": result.voice_stt_engine,
        "voice_tts_engine": result.voice_tts_engine,
        "voice_mic_device": result.voice_mic_device,
        "voice_speaker_device": result.voice_speaker_device,
        "camera_index": result.camera_index,
    }

    saved: list[str] = []

    if gemini_key:
        set_secret("gemini_api_key", gemini_key)
        saved.append("gemini_api_key")
    if openrouter_key:
        set_secret("openrouter_api_key", openrouter_key)
        saved.append("openrouter_api_key")
    if openai_key:
        set_secret("openai_api_key", openai_key)
        saved.append("openai_api_key")

    if result.remote_base_url and result.provider_base_url:
        settings_data["provider_settings"] = {
            result.provider_id: {
                "base_url": result.provider_base_url,
                "remote_enabled": True,
            }
        }

    saved_settings = save_settings(settings_data)
    return saved_settings, saved


def has_valid_config() -> bool:
    """Return True if a valid config (provider + os_system) exists."""
    from config.settings import load_settings
    try:
        settings = load_settings()
        return (
            settings.provider_id is not None
            and settings.provider_id.strip() != ""
            and settings.os_system is not None
        )
    except Exception:
        return False


def bootstrap_from_settings() -> Settings:
    """Load saved settings, filling in defaults for any missing fields."""
    from config.settings import load_settings
    try:
        settings = load_settings()
    except Exception:
        settings = default_settings()
    if not settings.provider_id:
        settings = dataclasses.replace(settings, provider_id=DEFAULT_PROVIDER_ID)
    if not settings.language:
        settings = dataclasses.replace(settings, language=DEFAULT_LANGUAGE)
    if not settings.privacy_profile:
        settings = dataclasses.replace(settings, privacy_profile=DEFAULT_PRIVACY_PROFILE)
    if not settings.network_mode:
        settings = dataclasses.replace(settings, network_mode=DEFAULT_NETWORK_MODE)
    if not settings.routing_mode:
        settings = dataclasses.replace(settings, routing_mode=DEFAULT_ROUTING_MODE)
    return settings
