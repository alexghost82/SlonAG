"""Russian locale helpers."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from localization.ru_locale import format_datetime_ru, normalize_yo, plural_ru


def test_normalize_yo_maps_yo_to_ye() -> None:
    assert normalize_yo("ёлка") == "елка"
    assert normalize_yo("Ёжик") == "Ежик"
    assert normalize_yo("елка") == "елка"
    assert normalize_yo("Ёлка и ёж") == "Елка и еж"


def test_plural_ru_covers_one_few_many() -> None:
    forms = ("файл", "файла", "файлов")
    assert plural_ru(1, *forms) == "файл"
    assert plural_ru(2, *forms) == "файла"
    assert plural_ru(5, *forms) == "файлов"
    assert plural_ru(21, *forms) == "файл"


def test_format_datetime_ru_uses_genitive_month() -> None:
    assert format_datetime_ru(date(2026, 8, 15)) == "15 августа 2026"
    assert format_datetime_ru(datetime(2026, 1, 2, 9, 5)) == "2 января 2026, 09:05"


def test_format_datetime_ru_rejects_time_on_date() -> None:
    with pytest.raises(ValueError, match="datetime"):
        format_datetime_ru(date(2026, 8, 15), with_time=True)
