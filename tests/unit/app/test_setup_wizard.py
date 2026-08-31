"""Headless setup-wizard tests. Collection must not need a display."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.schema import DEFAULT_LANGUAGE, MODEL_ROLE_KEYS, Settings
from localization.translator import load_catalog, set_locale, tr
from acta.app import STEPS, SetupWizardController, SetupWizardError, SetupWizardState
from providers.contracts import ModelInfo
from providers.errors import CapabilityError

WIZARD_SOURCE = (
    Path(__file__).resolve().parents[3] / "mark" / "app" / "setup_wizard.py"
)
APP_INIT_SOURCE = Path(__file__).resolve().parents[3] / "mark" / "app" / "__init__.py"
SENTINEL_KEY = "dummy-not-a-live-key-XYZ-4242"
LOOPBACK_URL = "http://127.0.0.1:11434"


def _model(
    model_id: str,
    *,
    provider_id: str = "gemini",
    local: bool = False,
    text: bool = False,
    vision: bool = False,
    embeddings: bool = False,
    audio_input: bool = False,
    audio_output: bool = False,
) -> ModelInfo:
    return ModelInfo(
        provider_id=provider_id,
        model_id=model_id,
        display_name=model_id,
        text=text,
        vision=vision,
        embeddings=embeddings,
        audio_input=audio_input,
        audio_output=audio_output,
        local=local,
        source="test",
        license="test",
    )


def _cloud_catalog() -> list[ModelInfo]:
    return [
        _model("cloud-chat", text=True),
        _model("cloud-vision", vision=True),
        _model("cloud-embed", embeddings=True),
    ]


def _local_catalog() -> list[ModelInfo]:
    return [
        _model("local-chat", provider_id="local", local=True, text=True),
        _model("local-vision", provider_id="local", local=True, vision=True),
    ]


def _mixed_catalog() -> list[ModelInfo]:
    return _cloud_catalog() + _local_catalog()


def _walk_to(
    wizard: SetupWizardState,
    step: str,
    *,
    privacy: str = "cloud",
    provider: str = "gemini",
    api_key: str = SENTINEL_KEY,
    local_url: str = LOOPBACK_URL,
    roles: dict[str, str] | None = None,
) -> SetupWizardState:
    while wizard.current_step != step:
        current = wizard.current_step
        if current == "privacy":
            wizard.set_privacy_profile(privacy)
        elif current == "provider":
            wizard.set_provider(provider)
        elif current == "credentials":
            if provider == "local":
                wizard.set_local_url(local_url)
            else:
                wizard.set_api_key(api_key)
        elif current == "roles" and roles:
            for role, model_id in roles.items():
                wizard.assign_role(role, model_id)
        elif current == "test":
            wizard.run_test_request()
        wizard.advance()
    return wizard


def test_controller_alias_is_headless_state() -> None:
    assert SetupWizardController is SetupWizardState


def test_wizard_sources_do_not_import_qt() -> None:
    for path in (WIZARD_SOURCE, APP_INIT_SOURCE):
        source = path.read_text(encoding="utf-8")
        lowered = source.lower()
        assert "pyqt" not in lowered
        assert "pyside" not in lowered
        assert "qtwidgets" not in lowered


def test_step_order_starts_at_privacy() -> None:
    wizard = SetupWizardState()
    assert wizard.steps == STEPS
    assert wizard.current_step == "privacy"
    assert STEPS == (
        "privacy",
        "provider",
        "credentials",
        "catalog",
        "roles",
        "test",
        "summary",
    )


def test_cannot_advance_before_privacy_is_valid() -> None:
    wizard = SetupWizardState()
    with pytest.raises(SetupWizardError, match="privacy_profile"):
        wizard.advance()
    with pytest.raises(SetupWizardError, match="unsupported"):
        wizard.set_privacy_profile("unknown-profile")
    assert wizard.current_step == "privacy"


def test_advance_follows_step_order() -> None:
    stored: dict[str, str] = {}
    wizard = SetupWizardState(catalog=_cloud_catalog(), set_secret=stored.__setitem__)
    wizard.set_privacy_profile("cloud")
    assert wizard.advance() == "provider"
    wizard.set_provider("gemini")
    assert wizard.advance() == "credentials"
    wizard.set_api_key(SENTINEL_KEY)
    assert wizard.advance() == "catalog"
    assert wizard.advance() == "roles"
    wizard.assign_role("chat", "cloud-chat")
    assert wizard.advance() == "test"
    assert wizard.advance() == "summary"
    with pytest.raises(SetupWizardError, match="last step"):
        wizard.advance()
    assert wizard.back() == "test"
    assert wizard.current_step == "test"


def test_fully_local_rejects_cloud_provider() -> None:
    wizard = SetupWizardState(catalog=_local_catalog())
    wizard.set_privacy_profile("fully_local")
    with pytest.raises(SetupWizardError, match="not allowed"):
        wizard.set_provider("gemini")
    wizard.set_provider("local")
    assert wizard.provider_id == "local"


def test_cloud_profile_rejects_local_provider() -> None:
    wizard = SetupWizardState(catalog=_cloud_catalog(), set_secret=lambda *_: None)
    wizard.set_privacy_profile("cloud")
    with pytest.raises(SetupWizardError, match="not allowed"):
        wizard.set_provider("local")


def test_unsupported_role_is_rejected() -> None:
    wizard = SetupWizardState(catalog=_cloud_catalog(), set_secret=lambda *_: None)
    _walk_to(wizard, "roles")
    with pytest.raises(CapabilityError) as exc_info:
        wizard.assign_role("vision", "cloud-chat")
    assert exc_info.value.role == "vision"
    assert exc_info.value.model_id == "cloud-chat"
    assert wizard.model_roles["vision"] == ""


def test_supported_role_is_accepted() -> None:
    wizard = SetupWizardState(catalog=_cloud_catalog(), set_secret=lambda *_: None)
    _walk_to(wizard, "roles")
    wizard.assign_role("chat", "cloud-chat")
    wizard.assign_role("vision", "cloud-vision")
    assert wizard.model_roles["chat"] == "cloud-chat"
    assert [model.model_id for model in wizard.models_for_role("embeddings")] == [
        "cloud-embed"
    ]


def test_non_loopback_local_url_is_rejected() -> None:
    wizard = SetupWizardState(catalog=_local_catalog())
    wizard.set_privacy_profile("fully_local")
    wizard.advance()
    wizard.set_provider("local")
    wizard.advance()
    for url in (
        "http://example.com/v1",
        "https://example.com",
        "http://8.8.8.8:8080",
        "http://192.168.1.10",
    ):
        with pytest.raises(SetupWizardError, match="loopback"):
            wizard.set_local_url(url)
    assert wizard.local_base_url is None
    with pytest.raises(SetupWizardError, match="loopback"):
        wizard.advance()


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1:11434",
        "http://localhost:8080/v1",
        "http://[::1]:8080",
    ),
)
def test_loopback_local_url_is_accepted(url: str) -> None:
    wizard = SetupWizardState(catalog=_local_catalog())
    wizard.set_privacy_profile("local_with_tools")
    wizard.advance()
    wizard.set_provider("local")
    wizard.advance()
    wizard.set_local_url(url)
    assert wizard.local_base_url == url
    assert wizard.advance() == "catalog"


def test_summary_distinguishes_local_from_cloud() -> None:
    stored: dict[str, str] = {}
    cloud = SetupWizardState(catalog=_cloud_catalog(), set_secret=stored.__setitem__)
    _walk_to(cloud, "summary", roles={"chat": "cloud-chat", "vision": "cloud-vision"})
    cloud_summary = cloud.summary()
    assert cloud_summary.privacy_profile == "cloud"
    assert "provider:gemini" in cloud_summary.cloud_items
    assert "role:chat" in cloud_summary.cloud_items
    assert "role:vision" in cloud_summary.cloud_items
    assert "memory" in cloud_summary.local_items
    assert "role:chat" not in cloud_summary.local_items

    local = SetupWizardState(catalog=_local_catalog())
    _walk_to(
        local,
        "summary",
        privacy="fully_local",
        provider="local",
        roles={"chat": "local-chat"},
    )
    local_summary = local.summary()
    assert local_summary.cloud_items == ()
    assert "provider:local" in local_summary.local_items
    assert "role:chat" in local_summary.local_items
    assert "memory" in local_summary.local_items

    hybrid = SetupWizardState(catalog=_mixed_catalog(), set_secret=stored.__setitem__)
    _walk_to(
        hybrid,
        "summary",
        privacy="hybrid",
        provider="gemini",
        roles={"chat": "cloud-chat", "vision": "local-vision"},
    )
    hybrid_summary = hybrid.summary()
    assert "role:chat" in hybrid_summary.cloud_items
    assert "role:vision" in hybrid_summary.local_items


def test_secrets_go_through_injected_setter_not_settings() -> None:
    stored: dict[str, str] = {}
    wizard = SetupWizardState(catalog=_cloud_catalog(), set_secret=stored.__setitem__)
    _walk_to(wizard, "summary", provider="openai", roles={"chat": "cloud-chat"})
    settings = wizard.complete()
    assert stored == {"openai_api_key": SENTINEL_KEY}
    payload = settings.to_dict()
    assert SENTINEL_KEY not in str(payload)
    assert "api_key" not in str(payload).lower()
    assert wizard._secret_stored is True
    assert not hasattr(wizard, "api_key")
    assert "api_key" not in vars(wizard)
    assert not (Path("config") / "api_keys.json").exists() or SENTINEL_KEY not in (
        Path("config") / "api_keys.json"
    ).read_text(encoding="utf-8")


def test_missing_secret_setter_rejects_key() -> None:
    wizard = SetupWizardState(catalog=_cloud_catalog())
    wizard.set_privacy_profile("cloud")
    wizard.advance()
    wizard.set_provider("gemini")
    wizard.advance()
    with pytest.raises(SetupWizardError, match="secret setter"):
        wizard.set_api_key(SENTINEL_KEY)
    assert wizard.can_advance() is False


def test_settings_are_validated_and_stay_russian() -> None:
    stored: dict[str, str] = {}
    wizard = SetupWizardState(
        catalog=_cloud_catalog(),
        set_secret=stored.__setitem__,
        os_system="mac",
    )
    _walk_to(wizard, "summary", roles={"chat": "cloud-chat"})
    settings = wizard.to_settings()
    assert isinstance(settings, Settings)
    assert settings.language == DEFAULT_LANGUAGE == "ru"
    assert settings.privacy_profile == "cloud"
    assert settings.provider_id == "gemini"
    assert settings.network_mode == "hybrid"
    assert settings.model_roles.chat == "cloud-chat"
    assert settings.os_system == "mac"
    for key in MODEL_ROLE_KEYS:
        assert hasattr(settings.model_roles, key)


def test_labels_use_existing_tr_keys_in_russian() -> None:
    wizard = SetupWizardState()
    ru = load_catalog("ru")
    assert wizard.title() == ru["setup.title"] == tr("setup.title")
    assert wizard.subtitle() == ru["setup.subtitle"]
    assert wizard.finish_label() == ru["setup.initialise"]
    assert wizard.os_label() == ru["setup.os"]
    wizard.set_privacy_profile("cloud")
    wizard.set_provider("gemini")
    assert wizard.credentials_label() == ru["setup.gemini_key"]
    wizard.set_provider("openrouter")
    assert wizard.credentials_label() == ru["setup.openrouter_key"]
    set_locale("en")
    assert wizard.title() == load_catalog("en")["setup.title"]
    assert wizard.title() != ru["setup.title"]


def test_optional_test_hook_is_injected() -> None:
    calls: list[str] = []
    stored: dict[str, str] = {}

    def _ping() -> str:
        calls.append("ping")
        return "ok"

    wizard = SetupWizardState(
        catalog=_cloud_catalog(),
        set_secret=stored.__setitem__,
        test_request=_ping,
    )
    _walk_to(wizard, "test")
    assert wizard.run_test_request() == "ok"
    assert calls == ["ping"]
    assert wizard.advance() == "summary"

    skipped = SetupWizardState(catalog=_cloud_catalog(), set_secret=stored.__setitem__)
    _walk_to(skipped, "test")
    assert skipped.run_test_request() is None
    assert skipped.advance() == "summary"


def test_catalog_is_injected_not_fetched() -> None:
    catalog = _cloud_catalog()
    wizard = SetupWizardState(catalog=catalog, set_secret=lambda *_: None)
    _walk_to(wizard, "catalog")
    assert [model.model_id for model in wizard.catalog] == [
        "cloud-chat",
        "cloud-vision",
        "cloud-embed",
    ]
    replacement = [_model("injected-only", text=True)]
    wizard.set_catalog(replacement)
    assert [model.model_id for model in wizard.catalog] == ["injected-only"]
    wizard.advance()
    with pytest.raises(SetupWizardError, match="unknown model"):
        wizard.assign_role("chat", "cloud-chat")
