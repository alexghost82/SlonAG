"""Russian TTS text normalization: abbreviations, numbers, and yo."""

from __future__ import annotations

import re

try:
    from localization.ru_locale import normalize_yo as _normalize_yo
    from localization.ru_locale import plural_ru
except ImportError:  # pragma: no cover - localization is present in this repo
    def _normalize_yo(text: str) -> str:
        return text

    def plural_ru(n: int, one: str, few: str, many: str) -> str:
        abs_n = abs(int(n))
        mod10 = abs_n % 10
        mod100 = abs_n % 100
        if mod10 == 1 and mod100 != 11:
            return one
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            return few
        return many

_ONES_M = (
    "ноль",
    "один",
    "два",
    "три",
    "четыре",
    "пять",
    "шесть",
    "семь",
    "восемь",
    "девять",
)
_ONES_F = (
    "ноль",
    "одна",
    "две",
    "три",
    "четыре",
    "пять",
    "шесть",
    "семь",
    "восемь",
    "девять",
)
_TEENS = (
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
)
_TENS = (
    "",
    "",
    "двадцать",
    "тридцать",
    "сорок",
    "пятьдесят",
    "шестьдесят",
    "семьдесят",
    "восемьдесят",
    "девяносто",
)
_HUNDREDS = (
    "",
    "сто",
    "двести",
    "триста",
    "четыреста",
    "пятьсот",
    "шестьсот",
    "семьсот",
    "восемьсот",
    "девятьсот",
)

_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    (r"\bт\.?\s*д\.", "и так далее"),
    (r"\bт\.?\s*п\.", "и тому подобное"),
    (r"\bт\.?\s*е\.", "то есть"),
    (r"\bн\.?\s*э\.", "нашей эры"),
    (r"\bдр\.", "другие"),
    (r"\bруб\.", "рублей"),
    (r"\bкоп\.", "копеек"),
    (r"\bтыс\.", "тысяч"),
    (r"\bмлн\b", "миллионов"),
    (r"\bмлрд\b", "миллиардов"),
    (r"\bкм\b", "километров"),
    (r"\bкг\b", "килограммов"),
    (r"\bсм\b", "сантиметров"),
    (r"\bмм\b", "миллиметров"),
    (r"\bгг\.", "годы"),
)

_NUMBER_RE = re.compile(r"(?<!\w)-?\d+(?!\w)")
_MAX_SPOKEN_NUMBER = 999_999


def number_to_ru(value: int) -> str:
    """Return a spoken Russian form for ``value`` (0–999999, plus a minus)."""
    if value < 0:
        return f"минус {number_to_ru(-value)}"
    if value == 0:
        return "ноль"
    if value > _MAX_SPOKEN_NUMBER:
        return str(value)
    thousands, rest = divmod(value, 1000)
    parts: list[str] = []
    if thousands:
        words = _under_thousand(thousands, feminine=True)
        unit = plural_ru(thousands, "тысяча", "тысячи", "тысяч")
        parts.append(f"{words} {unit}".strip())
    if rest:
        parts.append(_under_thousand(rest, feminine=False))
    return " ".join(parts)


def normalize_tts_text(text: str) -> str:
    """Expand common abbreviations, speak numbers, and normalize ``ё``."""
    if not isinstance(text, str):
        raise TypeError("normalize_tts_text() expected a string")
    result = text
    for pattern, replacement in _ABBREVIATIONS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    result = _NUMBER_RE.sub(_replace_number, result)
    result = _normalize_yo(result)
    return re.sub(r"\s+", " ", result).strip()


def _under_thousand(value: int, *, feminine: bool) -> str:
    if value == 0:
        return ""
    parts: list[str] = []
    hundreds, rest = divmod(value, 100)
    if hundreds:
        parts.append(_HUNDREDS[hundreds])
    if 10 <= rest <= 19:
        parts.append(_TEENS[rest - 10])
        return " ".join(parts)
    tens, ones = divmod(rest, 10)
    if tens:
        parts.append(_TENS[tens])
    if ones:
        table = _ONES_F if feminine else _ONES_M
        parts.append(table[ones])
    return " ".join(parts)


def _replace_number(match: re.Match[str]) -> str:
    token = match.group(0)
    try:
        return number_to_ru(int(token))
    except ValueError:
        return token
