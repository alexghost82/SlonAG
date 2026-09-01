"""Catalog-backed translator with a Russian default locale.

``tr`` does not import application settings. Callers that later read
``config`` language can switch locale via ``set_locale``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from string import Formatter
from typing import Any

DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = ("ru", "en")

_I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"
_FORMATTER = Formatter()

_current_locale = DEFAULT_LOCALE
_catalogs: dict[str, dict[str, str]] | None = None


class MissingTranslationError(KeyError):
    """Raised when the active catalog has no entry for ``key``."""

    def __init__(self, key: str, locale: str) -> None:
        self.key = key
        self.locale = locale
        super().__init__(f"missing translation key {key!r} for locale {locale!r}")


def get_locale() -> str:
    """Return the active locale. Defaults to ``ru``."""
    return _current_locale


def set_locale(locale: str) -> None:
    """Switch the active locale. Does not read or write ``config``."""
    catalogs = _load_catalogs()
    if locale not in catalogs:
        supported = ", ".join(SUPPORTED_LOCALES)
        raise ValueError(f"unsupported locale {locale!r}; expected one of: {supported}")
    global _current_locale
    _current_locale = locale


def reset_locale() -> None:
    """Restore the built-in default locale (``ru``)."""
    global _current_locale
    _current_locale = DEFAULT_LOCALE


def load_catalog(locale: str) -> dict[str, str]:
    """Return a copy of the flattened catalog for ``locale``."""
    catalogs = _load_catalogs()
    if locale not in catalogs:
        raise ValueError(f"unknown locale {locale!r}")
    return dict(catalogs[locale])


def placeholders_in(text: str) -> frozenset[str]:
    """Return named ``str.format`` placeholders in ``text``."""
    names: list[str] = []
    for _literal, field_name, _format_spec, _conversion in _FORMATTER.parse(text):
        if field_name:
            names.append(field_name)
    return frozenset(names)


def flatten_catalog(data: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten a nested catalog into dotted keys with string values."""
    flat: dict[str, str] = {}
    for raw_key, value in data.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise ValueError("catalog keys must be non-empty strings")
        key = f"{prefix}.{raw_key}" if prefix else raw_key
        if isinstance(value, Mapping):
            flat.update(flatten_catalog(value, key))
            continue
        if not isinstance(value, str):
            raise ValueError(f"catalog value for {key!r} must be a string")
        if key in flat:
            raise ValueError(f"duplicate catalog key {key!r}")
        flat[key] = value
    return flat


def tr(key: str, **kwargs: object) -> str:
    """Translate ``key`` in the active locale and interpolate ``kwargs``.

    The default locale is Russian. A missing key raises
    ``MissingTranslationError`` and never falls back to English.
    """
    if not isinstance(key, str) or not key:
        raise ValueError("translation key must be a non-empty string")

    locale = get_locale()
    catalog = _load_catalogs()[locale]
    if key not in catalog:
        raise MissingTranslationError(key, locale)

    template = catalog[key]
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(
            f"failed to interpolate {key!r} for locale {locale!r}: {exc}"
        ) from exc


def _load_catalogs() -> dict[str, dict[str, str]]:
    global _catalogs
    if _catalogs is None:
        loaded = {locale: _read_catalog(locale) for locale in SUPPORTED_LOCALES}
        _assert_matching_key_sets(loaded)
        _catalogs = loaded
    return _catalogs


def _read_catalog(locale: str) -> dict[str, str]:
    path = _I18N_DIR / f"{locale}.json"
    if not path.is_file():
        raise FileNotFoundError(f"catalog file is missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return flatten_catalog(raw)


def _assert_matching_key_sets(catalogs: Mapping[str, Mapping[str, str]]) -> None:
    ru_keys = set(catalogs["ru"])
    en_keys = set(catalogs["en"])
    if ru_keys != en_keys:
        missing_en = sorted(ru_keys - en_keys)
        missing_ru = sorted(en_keys - ru_keys)
        raise ValueError(
            "ru/en catalog key sets differ; "
            f"missing in en: {missing_en}; missing in ru: {missing_ru}"
        )
    for key in ru_keys:
        ru_fields = placeholders_in(catalogs["ru"][key])
        en_fields = placeholders_in(catalogs["en"][key])
        if ru_fields != en_fields:
            raise ValueError(
                f"placeholder names for {key!r} differ: ru={sorted(ru_fields)} "
                f"en={sorted(en_fields)}"
            )
