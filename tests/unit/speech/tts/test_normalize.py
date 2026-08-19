"""Russian TTS normalizer: numbers, abbreviations, and yo."""

from __future__ import annotations

from speech.tts.normalize import normalize_tts_text, number_to_ru


def test_normalize_yo_via_ru_locale() -> None:
    assert normalize_tts_text("ёлка и Ёжик") == "елка и Ежик"


def test_normalize_expands_abbreviations() -> None:
    text = normalize_tts_text("Детали, т.е. всё, и т.д.")
    assert "то есть" in text
    assert "и так далее" in text
    assert "е" in text  # ё from «всё» is normalized


def test_number_to_ru_covers_small_and_thousands() -> None:
    assert number_to_ru(0) == "ноль"
    assert number_to_ru(2) == "два"
    assert number_to_ru(21) == "двадцать один"
    assert number_to_ru(1000) == "одна тысяча"
    assert number_to_ru(2000) == "две тысячи"
    assert number_to_ru(5) == "пять"


def test_normalize_replaces_standalone_numbers() -> None:
    assert "два" in normalize_tts_text("У меня 2 яблока.")
