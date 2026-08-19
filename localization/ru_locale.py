"""Small Russian locale helpers: yo-normalization, plurals, date/time."""

from __future__ import annotations

from datetime import date, datetime

_YO_TO_YE = str.maketrans({"ё": "е", "Ё": "Е"})

_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def normalize_yo(text: str) -> str:
    """Map ``ё``/``Ё`` to ``е``/``Е`` so yo-variants compare as the same word."""
    if not isinstance(text, str):
        raise TypeError("normalize_yo() expected a string")
    return text.translate(_YO_TO_YE)


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Return the Russian plural form for ``n``.

    ``one`` is used for 1, 21, 31, …; ``few`` for 2–4, 22–24, …;
    ``many`` for 0, 5–20, 25–30, and the 11–14 teens.
    """
    abs_n = abs(int(n))
    mod10 = abs_n % 10
    mod100 = abs_n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def format_datetime_ru(value: datetime | date, *, with_time: bool | None = None) -> str:
    """Format ``value`` as a Russian date, optionally with 24-hour time.

    Examples: ``15 августа 2026`` or ``15 августа 2026, 01:18``.
    """
    if isinstance(value, datetime):
        include_time = True if with_time is None else with_time
        day = _format_date_ru(value.date())
        if not include_time:
            return day
        return f"{day}, {value.strftime('%H:%M')}"
    if isinstance(value, date):
        if with_time:
            raise ValueError("with_time=True requires a datetime value")
        return _format_date_ru(value)
    raise TypeError("format_datetime_ru() expected datetime or date")


def _format_date_ru(value: date) -> str:
    return f"{value.day} {_MONTHS_GENITIVE[value.month - 1]} {value.year}"
