"""Sentence chunking for streaming-by-sentence TTS."""

from __future__ import annotations

from speech.tts.sentences import split_sentences


def test_split_sentences_on_period_question_exclamation() -> None:
    chunks = split_sentences("Привет. Как дела? Отлично!")
    assert chunks == ["Привет.", "Как дела?", "Отлично!"]


def test_split_sentences_keeps_ellipsis_with_current_sentence() -> None:
    chunks = split_sentences("Подожди... Готово.")
    assert chunks == ["Подожди...", "Готово."]


def test_split_sentences_single_clause_without_terminator() -> None:
    assert split_sentences("просто фраза") == ["просто фраза"]


def test_split_sentences_empty_and_whitespace() -> None:
    assert split_sentences("") == []
    assert split_sentences("   \n") == []
