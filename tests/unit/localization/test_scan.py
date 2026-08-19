"""Hardcoded-string scanner fixtures."""

from __future__ import annotations

from pathlib import Path

from localization.scan import find_hardcoded_strings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_source.py"


def test_scanner_flags_hardcoded_phrase_and_ignores_tr_keys() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    values = [hit.value for hit in find_hardcoded_strings(source)]
    assert "Type a command" in values
    assert "status.ready" not in values
    assert "window.title" not in values


def test_scanner_ignores_inline_tr_call() -> None:
    source = 'label = tr("status.ready")\nplain = "Type a command"\n'
    values = [hit.value for hit in find_hardcoded_strings(source)]
    assert values == ["Type a command"]
