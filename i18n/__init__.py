"""
i18n - canonical localization layer for SlonAG.
Defaults to Russian ("ru"); falls back to English, then to the raw key.
Supports dot-separated catalog lookup and str.format-style parameter interpolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

_DEFAULT_LOCALE: str = "ru"
_lock = RLock()
_catalogs: dict[str, dict[str, str]] = {}
_flat_en: dict[str, str] = {}
_flat_ru: dict[str, str] = {}


def _flatten(nested: dict, parent_key: str = "", sep: str = ".") -> dict[str, str]:
    items: list[tuple[str, str]] = []
    for k, v in nested.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten(v, new_key, sep).items())
        else:
            items.append((new_key, str(v)))
    return dict(items)


def _load_catalogs() -> None:
    global _flat_en, _flat_ru
    with _lock:
        if _catalogs:
            return
        i18n_dir = Path(__file__).resolve().parent
        for fname in ("en.json", "ru.json"):
            path = i18n_dir / fname
            if path.is_file():
                with open(path, encoding="utf-8") as f:
                    _catalogs[fname[:-5]] = json.load(f)
        _flat_en = _flatten(_catalogs.get("en", {}))
        _flat_ru = _flatten(_catalogs.get("ru", {}))


def set_locale(locale: str) -> None:
    global _DEFAULT_LOCALE
    _DEFAULT_LOCALE = locale
    _load_catalogs()


def t(key: str, /, *args, **kwargs) -> str:
    _load_catalogs()
    active = _flat_ru if _DEFAULT_LOCALE == "ru" else _flat_en
    val = active.get(key)
    if val is None:
        fallback = _flat_ru if _DEFAULT_LOCALE != "ru" else _flat_en
        val = fallback.get(key)
    if val is None:
        val = key
    if args or kwargs:
        try:
            val = val.format(*args, **kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return val


_ = t


__all__ = ["t", "set_locale", "_"]
