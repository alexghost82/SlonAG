"""Headless first-run setup wizard.

Collects privacy profile, provider, credentials, injected catalog, and
role assignments. Safe to import without a display. Secrets are written
only through an injected setter — never into settings JSON.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from config.schema import (
    DEFAULT_LANGUAGE,
    MODEL_ROLE_KEYS,
    PRIVACY_PROFILES,
    PROVIDER_IDS,
    Settings,
    validate_settings,
)
from localization import tr
from providers.capabilities import require_capability, supports
from providers.contracts import ModelInfo
from providers.local.endpoint import is_loopback_url

STEPS: tuple[str, ...] = (
    "privacy",
    "provider",
    "credentials",
    "catalog",
    "roles",
    "test",
    "summary",
)

CLOUD_PROVIDER_IDS = frozenset({"gemini", "openai", "openrouter"})
LOCAL_PROVIDER_IDS = frozenset({"local"})

PROVIDER_SECRET_NAMES: dict[str, str] = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "openrouter": "openrouter_api_key",
}

_NETWORK_BY_PRIVACY: dict[str, str] = {
    "fully_local": "offline",
    "local_with_tools": "tools_only",
    "cloud": "hybrid",
    "hybrid": "hybrid",
}

# Existing catalog keys only. Dedicated wizard strings are a later i18n change.
_TITLE_KEY = "setup.title"
_SUBTITLE_KEY = "setup.subtitle"
_FINISH_KEY = "setup.initialise"
_OS_KEY = "setup.os"
_GEMINI_KEY = "setup.gemini_key"
_OPENROUTER_KEY = "setup.openrouter_key"


class SetupWizardError(ValueError):
    """Invalid wizard input or illegal step transition."""


@dataclass(frozen=True)
class WizardSummary:
    """What stays on-device versus what is sent to a cloud provider."""

    privacy_profile: str
    provider_id: str
    local_items: tuple[str, ...]
    cloud_items: tuple[str, ...]


class SetupWizardState:
    """Headless wizard controller. Tests do not need a display."""

    def __init__(
        self,
        *,
        catalog: Sequence[ModelInfo] | None = None,
        set_secret: Callable[[str, str], None] | None = None,
        test_request: Callable[[], object] | None = None,
        os_system: str | None = None,
    ) -> None:
        self._step_index = 0
        self.privacy_profile: str | None = None
        self.provider_id: str | None = None
        self.local_base_url: str | None = None
        self.os_system = os_system
        self._catalog: list[ModelInfo] = list(catalog or ())
        self._roles: dict[str, str] = {key: "" for key in MODEL_ROLE_KEYS}
        self._set_secret = set_secret
        self._test_request = test_request
        self._secret_stored = False
        self._test_result: object | None = None

    @property
    def steps(self) -> tuple[str, ...]:
        return STEPS

    @property
    def current_step(self) -> str:
        return STEPS[self._step_index]

    @property
    def catalog(self) -> list[ModelInfo]:
        return list(self._catalog)

    @property
    def model_roles(self) -> dict[str, str]:
        return dict(self._roles)

    def title(self) -> str:
        return tr(_TITLE_KEY)

    def subtitle(self) -> str:
        return tr(_SUBTITLE_KEY)

    def finish_label(self) -> str:
        return tr(_FINISH_KEY)

    def os_label(self) -> str:
        return tr(_OS_KEY)

    def credentials_label(self) -> str:
        """Return the closest existing ``tr`` label for the credentials step."""
        if self.provider_id == "openrouter":
            return tr(_OPENROUTER_KEY)
        if self.provider_id in CLOUD_PROVIDER_IDS:
            return tr(_GEMINI_KEY)
        return tr(_SUBTITLE_KEY)

    def allowed_providers(self) -> frozenset[str]:
        return _allowed_providers(self.privacy_profile)

    def models_for_role(self, role: str) -> list[ModelInfo]:
        return [model for model in self._catalog if supports(model, role)]

    def set_privacy_profile(self, value: str) -> None:
        if value not in PRIVACY_PROFILES:
            raise SetupWizardError("privacy_profile has an unsupported value")
        self.privacy_profile = value
        if self.provider_id is not None and self.provider_id not in self.allowed_providers():
            self._clear_provider()

    def set_provider(self, value: str) -> None:
        if value not in PROVIDER_IDS:
            raise SetupWizardError("provider_id has an unsupported value")
        if self.privacy_profile is None:
            raise SetupWizardError("privacy_profile must be chosen first")
        if value not in self.allowed_providers():
            raise SetupWizardError(
                f"provider {value!r} is not allowed for {self.privacy_profile}"
            )
        if value != self.provider_id:
            self._clear_credentials()
        self.provider_id = value

    def set_api_key(self, value: str) -> None:
        if self.provider_id not in PROVIDER_SECRET_NAMES:
            raise SetupWizardError("api key is only valid for a cloud provider")
        if not isinstance(value, str) or not value.strip():
            raise SetupWizardError("api key must be a non-empty string")
        if self._set_secret is None:
            raise SetupWizardError("secret setter is not configured")
        self._set_secret(PROVIDER_SECRET_NAMES[self.provider_id], value)
        self._secret_stored = True

    def set_local_url(self, url: str) -> None:
        if self.provider_id != "local":
            raise SetupWizardError("local URL is only valid for the local provider")
        if not isinstance(url, str) or not url.strip():
            raise SetupWizardError("local runtime URL must be a non-empty string")
        cleaned = url.strip()
        if not is_loopback_url(cleaned):
            raise SetupWizardError("local runtime URL must be a loopback address")
        self.local_base_url = cleaned

    def set_catalog(self, models: Sequence[ModelInfo]) -> None:
        self._catalog = list(models)

    def set_os_system(self, value: str) -> None:
        self.os_system = validate_settings({"os_system": value}).os_system

    def assign_role(self, role: str, model_id: str) -> None:
        if role not in MODEL_ROLE_KEYS:
            raise SetupWizardError(f"unknown role {role!r}")
        if not model_id:
            self._roles[role] = ""
            return
        model = self._model_by_id(model_id)
        if model is None:
            raise SetupWizardError(f"unknown model {model_id!r}")
        if not supports(model, role):
            require_capability(model, role)
        require_capability(model, role)
        self._roles[role] = model_id

    def run_test_request(self) -> object:
        if self._test_request is None:
            self._test_result = None
            return None
        self._test_result = self._test_request()
        return self._test_result

    def can_advance(self) -> bool:
        try:
            self._validate_current()
        except SetupWizardError:
            return False
        return self._step_index < len(STEPS) - 1

    def advance(self) -> str:
        self._validate_current()
        if self._step_index >= len(STEPS) - 1:
            raise SetupWizardError("already at last step")
        self._step_index += 1
        return self.current_step

    def back(self) -> str:
        if self._step_index == 0:
            raise SetupWizardError("already at first step")
        self._step_index -= 1
        return self.current_step

    def summary(self) -> WizardSummary:
        self._require_ready_for_summary()
        local_items: list[str] = ["memory"]
        cloud_items: list[str] = []
        provider_token = f"provider:{self.provider_id}"
        if self._item_is_cloud(None):
            cloud_items.append(provider_token)
        else:
            local_items.append(provider_token)
        for role, model_id in self._roles.items():
            if not model_id:
                continue
            token = f"role:{role}"
            if self._item_is_cloud(self._model_by_id(model_id)):
                cloud_items.append(token)
            else:
                local_items.append(token)
        return WizardSummary(
            privacy_profile=self.privacy_profile or "",
            provider_id=self.provider_id or "",
            local_items=tuple(local_items),
            cloud_items=tuple(cloud_items),
        )

    def to_settings(self) -> Settings:
        self._require_ready_for_summary()
        payload: dict[str, object] = {
            "privacy_profile": self.privacy_profile,
            "provider_id": self.provider_id,
            "language": DEFAULT_LANGUAGE,
            "network_mode": _NETWORK_BY_PRIVACY[self.privacy_profile or ""],
            "model_roles": dict(self._roles),
        }
        if self.os_system is not None:
            payload["os_system"] = self.os_system
        return validate_settings(payload)

    def complete(self) -> Settings:
        if self.current_step != "summary":
            raise SetupWizardError("wizard is not on the summary step")
        return self.to_settings()

    def _validate_current(self) -> None:
        step = self.current_step
        if step == "privacy":
            if self.privacy_profile not in PRIVACY_PROFILES:
                raise SetupWizardError("privacy_profile is required")
            return
        if step == "provider":
            if self.provider_id not in PROVIDER_IDS:
                raise SetupWizardError("provider_id is required")
            if self.provider_id not in self.allowed_providers():
                raise SetupWizardError("provider_id is not allowed")
            return
        if step == "credentials":
            self._validate_credentials()
            return
        if step == "catalog":
            return
        if step == "roles":
            self._validate_roles()
            return
        if step in {"test", "summary"}:
            return
        raise SetupWizardError(f"unknown step {step!r}")

    def _validate_credentials(self) -> None:
        if self.provider_id == "local":
            if not self.local_base_url or not is_loopback_url(self.local_base_url):
                raise SetupWizardError("loopback local runtime URL is required")
            return
        if self.provider_id in PROVIDER_SECRET_NAMES:
            if not self._secret_stored:
                raise SetupWizardError("api key must be stored through the secret setter")
            return
        raise SetupWizardError("provider_id is required")

    def _validate_roles(self) -> None:
        for role, model_id in self._roles.items():
            if not model_id:
                continue
            model = self._model_by_id(model_id)
            if model is None:
                raise SetupWizardError(f"unknown model {model_id!r}")
            require_capability(model, role)

    def _require_ready_for_summary(self) -> None:
        if self.privacy_profile not in PRIVACY_PROFILES:
            raise SetupWizardError("privacy_profile is required")
        if self.provider_id not in PROVIDER_IDS:
            raise SetupWizardError("provider_id is required")
        self._validate_credentials()
        self._validate_roles()

    def _item_is_cloud(self, model: ModelInfo | None) -> bool:
        if self.privacy_profile in {"fully_local", "local_with_tools"}:
            return False
        if model is not None:
            return not model.local
        return self.provider_id in CLOUD_PROVIDER_IDS

    def _model_by_id(self, model_id: str) -> ModelInfo | None:
        for model in self._catalog:
            if model.model_id == model_id:
                return model
        return None

    def _clear_provider(self) -> None:
        self.provider_id = None
        self._clear_credentials()

    def _clear_credentials(self) -> None:
        self.local_base_url = None
        self._secret_stored = False


SetupWizardController = SetupWizardState


def _allowed_providers(privacy_profile: str | None) -> frozenset[str]:
    if privacy_profile in {"fully_local", "local_with_tools"}:
        return LOCAL_PROVIDER_IDS
    if privacy_profile == "cloud":
        return CLOUD_PROVIDER_IDS
    if privacy_profile == "hybrid":
        return frozenset(PROVIDER_IDS)
    return frozenset()
