"""Typed non-secret settings schema.

API keys and other secrets must never appear in this schema or in
``settings.json``. Validate caller data and reject wrong types.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

PRIVACY_PROFILES = frozenset({"fully_local", "local_with_tools", "cloud", "hybrid"})
PROVIDER_IDS = frozenset(
    {"gemini", "openai", "openrouter", "local", "ollama", "llama_cpp", "openai_compat"}
)
LOCAL_PROVIDER_IDS = frozenset({"local", "ollama", "llama_cpp"})
NETWORK_MODES = frozenset({"offline", "tools_only", "hybrid"})
ROUTING_MODES = frozenset({"manual", "local_first", "local_only", "cloud_first"})
OS_SYSTEMS = frozenset({"windows", "mac", "linux"})
MODEL_ROLE_KEYS = (
    "chat",
    "planning",
    "code",
    "vision",
    "embeddings",
    "stt",
    "tts",
)

DEFAULT_LANGUAGE = "ru"
DEFAULT_PRIVACY_PROFILE = "hybrid"
DEFAULT_PROVIDER_ID = "gemini"

# Base URL defaults per provider type (for local/OpenAI-compatible endpoints)
DEFAULT_OPENAI_BASE_URL = ""  # uses official OpenAI endpoint
DEFAULT_GEMINI_BASE_URL = ""  # uses official Gemini endpoint
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_LLAMA_CPP_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_OPENAI_COMPAT_BASE_URL = ""
DEFAULT_NETWORK_MODE = "hybrid"
DEFAULT_ROUTING_MODE = "manual"

# Voice pipeline defaults
DEFAULT_VOICE_STT_ENGINE = "faster_whisper"
DEFAULT_VOICE_TTS_ENGINE = "piper"


_SECRET_FIELD_MARKERS = ("api_key", "token", "secret", "password")


class SettingsValidationError(ValueError):
    """Raised when settings data has the wrong type or an invalid value."""


def is_secret_field(name: str) -> bool:
    """Return True if a field name looks like a secret slot."""
    lowered = name.lower()
    return any(marker in lowered for marker in _SECRET_FIELD_MARKERS)


@dataclass(frozen=True)
class ModelRoles:
    """Placeholder model ids assigned to assistant roles."""

    chat: str = ""
    planning: str = ""
    code: str = ""
    vision: str = ""
    embeddings: str = ""
    stt: str = ""
    tts: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class LocalProviderSettings:
    """Connection settings for a local, OpenAI-compatible runtime."""

    enabled: bool = True
    base_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreferredLocalModels:
    """Optional local model identifiers selected for runtime roles."""

    chat: str = ""
    planning: str = ""
    code: str = ""
    utility: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class LocalModelOverride:
    """Explicit capability facts supplied by the user for one local model."""

    tool_calling: bool | None = None
    structured_output: bool | None = None
    vision: bool | None = None
    context_length: int | None = None

    def to_dict(self) -> dict[str, bool | int]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True)
class ProviderBaseURL:
    """Base URL override for a specific provider (OpenAI-compatible endpoints)."""

    base_url: str = ""
    remote_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"base_url": self.base_url, "remote_enabled": self.remote_enabled}


@dataclass(frozen=True)
class LocalModelsSettings:
    """Non-secret configuration for local language-model runtimes."""

    default_provider: str = "ollama"
    ollama: LocalProviderSettings = field(
        default_factory=lambda: LocalProviderSettings(
            base_url=DEFAULT_OLLAMA_BASE_URL
        )
    )
    llama_cpp: LocalProviderSettings = field(
        default_factory=lambda: LocalProviderSettings(
            base_url=DEFAULT_LLAMA_CPP_BASE_URL
        )
    )
    preferred: PreferredLocalModels = field(default_factory=PreferredLocalModels)
    overrides: dict[str, LocalModelOverride] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "ollama": self.ollama.to_dict(),
            "llama_cpp": self.llama_cpp.to_dict(),
            "preferred": self.preferred.to_dict(),
            "overrides": {
                model_id: override.to_dict()
                for model_id, override in self.overrides.items()
            },
        }


@dataclass(frozen=True)
class Settings:
    """Non-secret application settings."""

    privacy_profile: str = DEFAULT_PRIVACY_PROFILE
    provider_id: str = DEFAULT_PROVIDER_ID
    model_id: str = ""  # explicit model selection (empty = auto-resolve)
    language: str = DEFAULT_LANGUAGE
    network_mode: str = DEFAULT_NETWORK_MODE
    routing_mode: str = DEFAULT_ROUTING_MODE
    model_roles: ModelRoles = field(default_factory=ModelRoles)
    local_models: LocalModelsSettings = field(default_factory=LocalModelsSettings)
    provider_settings: dict[str, ProviderBaseURL] = field(default_factory=dict)
    os_system: str | None = None
    camera_index: int | None = None
    voice_stt_engine: str = DEFAULT_VOICE_STT_ENGINE
    voice_tts_engine: str = DEFAULT_VOICE_TTS_ENGINE
    voice_mic_device: str | None = None
    voice_speaker_device: str | None = None


    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "privacy_profile": self.privacy_profile,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "language": self.language,
            "network_mode": self.network_mode,
            "routing_mode": self.routing_mode,
            "model_roles": self.model_roles.to_dict(),
            "local_models": self.local_models.to_dict(),
            "provider_settings": {
                pid: ps.to_dict() for pid, ps in self.provider_settings.items()
            },
        }
        if self.os_system is not None:
            payload["os_system"] = self.os_system
        if self.camera_index is not None:
            payload["camera_index"] = self.camera_index
        if self.voice_stt_engine != DEFAULT_VOICE_STT_ENGINE:
            payload["voice_stt_engine"] = self.voice_stt_engine
        if self.voice_tts_engine != DEFAULT_VOICE_TTS_ENGINE:
            payload["voice_tts_engine"] = self.voice_tts_engine
        if self.voice_mic_device is not None:
            payload["voice_mic_device"] = self.voice_mic_device
        if self.voice_speaker_device is not None:
            payload["voice_speaker_device"] = self.voice_speaker_device
        return payload

def default_settings() -> Settings:
    return Settings()


def validate_settings(data: object) -> Settings:
    """Validate a mapping and return a ``Settings`` instance.

    Unknown required types and invalid enum values are rejected.
    Secret-like field names are rejected so keys cannot land in settings.
    Extra non-secret keys are ignored for forward compatibility.
    """
    if not isinstance(data, Mapping):
        raise SettingsValidationError("settings must be an object")

    for key in data:
        if not isinstance(key, str):
            raise SettingsValidationError("settings keys must be strings")
        if is_secret_field(key):
            raise SettingsValidationError(
                f"settings must not contain secret field {key!r}"
            )

    privacy_profile = _optional_enum(
        data, "privacy_profile", PRIVACY_PROFILES, DEFAULT_PRIVACY_PROFILE
    )
    provider_id = _optional_enum(data, "provider_id", PROVIDER_IDS, DEFAULT_PROVIDER_ID)
    model_id = _optional_str(data, "model_id", "")
    language = _optional_non_empty_str(data, "language", DEFAULT_LANGUAGE)
    network_mode = _optional_enum(
        data, "network_mode", NETWORK_MODES, DEFAULT_NETWORK_MODE
    )
    routing_mode = _optional_enum(
        data, "routing_mode", ROUTING_MODES, DEFAULT_ROUTING_MODE
    )
    model_roles = _validate_model_roles(data.get("model_roles", {}))
    local_models = _validate_local_models(data.get("local_models", {}))
    provider_settings = _validate_provider_settings(data.get("provider_settings"))
    os_system = _optional_os_overlay(data)
    camera_index = _optional_non_negative_int(data, "camera_index")

    return Settings(
        privacy_profile=privacy_profile,
        provider_id=provider_id,
        model_id=model_id,
        language=language,
        network_mode=network_mode,
        routing_mode=routing_mode,
        model_roles=model_roles,
        local_models=local_models,
        provider_settings=provider_settings,
        os_system=os_system,
        camera_index=camera_index,
    )


def _optional_non_negative_int(
    data: Mapping[str, Any], field_name: str
) -> int | None:
    if field_name not in data:
        return None
    value = data[field_name]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SettingsValidationError(f"{field_name} must be a non-negative integer")
    return value


def _optional_enum(
    data: Mapping[str, Any],
    field_name: str,
    allowed: frozenset[str],
    default: str,
) -> str:
    if field_name not in data:
        return default
    value = data[field_name]
    if not isinstance(value, str):
        raise SettingsValidationError(f"{field_name} must be a string")
    if value not in allowed:
        raise SettingsValidationError(f"{field_name} has an unsupported value")
    return value


def _optional_non_empty_str(
    data: Mapping[str, Any], field_name: str, default: str
) -> str:
    if field_name not in data:
        return default
    value = data[field_name]
    if not isinstance(value, str):
        raise SettingsValidationError(f"{field_name} must be a string")
    if not value.strip():
        raise SettingsValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_str(
    data: Mapping[str, Any], field_name: str, default: str
) -> str:
    """Return *field_name* value as a string from *data*, or *default*.

    Unlike ``_optional_non_empty_str``, this helper accepts empty strings
    (useful for optional *model_id* or *base_url* that default to "").
    """
    if field_name not in data:
        return default
    value = data[field_name]
    if value is None:
        return default
    if not isinstance(value, str):
        raise SettingsValidationError(f"{field_name} must be a string")
    return value



def _optional_os_overlay(data: Mapping[str, Any]) -> str | None:
    if "os_system" not in data:
        return None
    value = data["os_system"]
    if value is None:
        return None
    if not isinstance(value, str):
        raise SettingsValidationError("os_system must be a string")
    normalized = value.lower()
    if normalized not in OS_SYSTEMS:
        raise SettingsValidationError("os_system has an unsupported value")
    return normalized


def _validate_model_roles(value: object) -> ModelRoles:
    if value is None:
        return ModelRoles()
    if not isinstance(value, Mapping):
        raise SettingsValidationError("model_roles must be an object")

    kwargs: dict[str, str] = {}
    for key, role_value in value.items():
        if not isinstance(key, str):
            raise SettingsValidationError("model_roles keys must be strings")
        if is_secret_field(key):
            raise SettingsValidationError(
                f"model_roles must not contain secret field {key!r}"
            )
        if key not in MODEL_ROLE_KEYS:
            raise SettingsValidationError(f"model_roles contains unknown role {key!r}")
        if not isinstance(role_value, str):
            raise SettingsValidationError(f"model_roles.{key} must be a string")
        kwargs[key] = role_value
    return ModelRoles(**kwargs)


def _validate_local_models(value: object) -> LocalModelsSettings:
    if value is None:
        return LocalModelsSettings()
    data = _require_mapping(value, "local_models")
    _reject_unknown_or_secret_keys(
        data,
        "local_models",
        {"default_provider", "ollama", "llama_cpp", "preferred", "overrides"},
    )
    default_provider = _optional_enum(
        data, "default_provider", LOCAL_PROVIDER_IDS, "ollama"
    )
    return LocalModelsSettings(
        default_provider=default_provider,
        ollama=_validate_local_provider(
            data.get("ollama", {}), "local_models.ollama", DEFAULT_OLLAMA_BASE_URL
        ),
        llama_cpp=_validate_local_provider(
            data.get("llama_cpp", {}),
            "local_models.llama_cpp",
            DEFAULT_LLAMA_CPP_BASE_URL,
        ),
        preferred=_validate_preferred_models(data.get("preferred", {})),
        overrides=_validate_model_overrides(data.get("overrides", {})),
    )


def _validate_local_provider(
    value: object, field_name: str, default_base_url: str
) -> LocalProviderSettings:
    data = _require_mapping(value, field_name)
    _reject_unknown_or_secret_keys(data, field_name, {"enabled", "base_url"})
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise SettingsValidationError(f"{field_name}.enabled must be a boolean")
    base_url = _optional_non_empty_str(data, "base_url", default_base_url)
    return LocalProviderSettings(enabled=enabled, base_url=base_url)


def _validate_preferred_models(value: object) -> PreferredLocalModels:
    field_name = "local_models.preferred"
    data = _require_mapping(value, field_name)
    roles = {"chat", "planning", "code", "utility"}
    _reject_unknown_or_secret_keys(data, field_name, roles)
    kwargs: dict[str, str] = {}
    for role, model_id in data.items():
        if not isinstance(model_id, str):
            raise SettingsValidationError(f"{field_name}.{role} must be a string")
        kwargs[role] = model_id
    return PreferredLocalModels(**kwargs)


def _validate_model_overrides(value: object) -> dict[str, LocalModelOverride]:
    field_name = "local_models.overrides"
    data = _require_mapping(value, field_name)
    result: dict[str, LocalModelOverride] = {}
    allowed = {"tool_calling", "structured_output", "vision", "context_length"}
    for model_id, raw_override in data.items():
        if not isinstance(model_id, str) or not model_id.strip():
            raise SettingsValidationError(
                f"{field_name} model ids must be non-empty strings"
            )
        if is_secret_field(model_id):
            raise SettingsValidationError(
                f"{field_name} must not contain secret field {model_id!r}"
            )
        override_name = f"{field_name}.{model_id}"
        override = _require_mapping(raw_override, override_name)
        _reject_unknown_or_secret_keys(override, override_name, allowed)
        kwargs: dict[str, bool | int] = {}
        for capability in ("tool_calling", "structured_output", "vision"):
            if capability in override:
                capability_value = override[capability]
                if not isinstance(capability_value, bool):
                    raise SettingsValidationError(
                        f"{override_name}.{capability} must be a boolean"
                    )
                kwargs[capability] = capability_value
        if "context_length" in override:
            context_length = override["context_length"]
            if (
                not isinstance(context_length, int)
                or isinstance(context_length, bool)
                or context_length <= 0
            ):
                raise SettingsValidationError(
                    f"{override_name}.context_length must be a positive integer"
                )
            kwargs["context_length"] = context_length
        result[model_id] = LocalModelOverride(**kwargs)
    return result


def _validate_provider_settings(value: object) -> dict[str, ProviderBaseURL]:
    """Validate provider base_url overrides for local-compatible endpoints."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SettingsValidationError("provider_settings must be an object")
    allowed_providers = PROVIDER_IDS
    result: dict[str, ProviderBaseURL] = {}
    for pid, raw in value.items():
        if not isinstance(pid, str) or pid not in allowed_providers:
            raise SettingsValidationError(
                f"provider_settings contains unknown provider {pid!r}"
            )
        if not isinstance(raw, Mapping):
            raise SettingsValidationError(f"provider_settings.{pid} must be an object")
        _reject_unknown_or_secret_keys(
            raw, f"provider_settings.{pid}", {"base_url", "remote_enabled"}
        )
        base_url = _optional_str(raw, "base_url", "")
        remote = raw.get("remote_enabled", False)
        if not isinstance(remote, bool):
            raise SettingsValidationError(
                f"provider_settings.{pid}.remote_enabled must be a boolean"
            )
        result[pid] = ProviderBaseURL(base_url=base_url, remote_enabled=remote)
    return result


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SettingsValidationError(f"{field_name} must be an object")
    return value


def _reject_unknown_or_secret_keys(
    data: Mapping[object, object], field_name: str, allowed: set[str]
) -> None:
    for key in data:
        if not isinstance(key, str):
            raise SettingsValidationError(f"{field_name} keys must be strings")
        if is_secret_field(key):
            raise SettingsValidationError(
                f"{field_name} must not contain secret field {key!r}"
            )
        if key not in allowed:
            raise SettingsValidationError(
                f"{field_name} contains unknown field {key!r}"
            )
