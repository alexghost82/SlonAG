"""Translator behaviour: Russian default, interpolation, missing keys."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from localization import tr
from localization.translator import (
    DEFAULT_LOCALE,
    MissingTranslationError,
    load_catalog,
    reset_locale,
    set_locale,
)


@pytest.fixture(autouse=True)
def _restore_default_locale() -> Generator[None, None, None]:
    reset_locale()
    yield
    reset_locale()


def test_default_locale_is_russian() -> None:
    assert DEFAULT_LOCALE == "ru"
    assert tr("status.ready") == load_catalog("ru")["status.ready"]
    assert tr("status.ready") != load_catalog("en")["status.ready"]


def test_confirm_delete_interpolates_name() -> None:
    result = tr("dialog.confirm_delete", name="x")
    assert "x" in result
    assert "{name}" not in result
    assert result == load_catalog("ru")["dialog.confirm_delete"].format(name="x")


def test_missing_key_is_detectable() -> None:
    with pytest.raises(MissingTranslationError, match="does.not.exist") as exc_info:
        tr("does.not.exist")
    assert exc_info.value.key == "does.not.exist"
    assert exc_info.value.locale == "ru"


def test_set_locale_switches_catalog_without_english_fallback() -> None:
    set_locale("en")
    assert tr("status.ready") == load_catalog("en")["status.ready"]
    with pytest.raises(MissingTranslationError, match="locale 'en'"):
        tr("does.not.exist")
