"""Catalog contract: matching keys and placeholders across ru/en."""

from __future__ import annotations

from localization.translator import load_catalog, placeholders_in

REQUIRED_KEYS = frozenset(
    {
        "status.ready",
        "status.listening",
        "status.thinking",
        "status.speaking",
        "status.processing",
        "status.muted",
        "setup.title",
        "setup.subtitle",
        "setup.gemini_key",
        "setup.openrouter_key",
        "setup.os",
        "setup.initialise",
        "window.title",
        "input.placeholder",
        "file.drop_hint",
        "file.none_loaded",
        "mic.active",
        "mic.muted",
        "dialog.confirm_delete",
        "error.unknown_tool",
    }
)


def test_ru_and_en_key_sets_are_identical() -> None:
    ru = load_catalog("ru")
    en = load_catalog("en")
    assert set(ru) == set(en)
    assert REQUIRED_KEYS <= set(ru)


def test_placeholders_match_in_both_locales() -> None:
    ru = load_catalog("ru")
    en = load_catalog("en")
    for key in ru:
        assert placeholders_in(ru[key]) == placeholders_in(en[key]), key
    assert placeholders_in(ru["dialog.confirm_delete"]) == frozenset({"name"})


def test_catalogs_contain_no_secret_like_values() -> None:
    markers = ("api_key=", "sk-", "AIza", "token=", "password")
    for locale in ("ru", "en"):
        for key, value in load_catalog(locale).items():
            lowered = value.lower()
            assert "sk-or-" not in lowered
            for marker in markers:
                assert marker.lower() not in lowered, f"{locale}:{key}"
