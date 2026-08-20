"""Repository identity audit test.

Ensures that active product prompts, UI text, wake word, and assistant identity use 'Slon'
and that no forbidden active 'Jarvis' identity regressions are introduced.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def test_core_prompt_identity() -> None:
    prompt_file = BASE_DIR / "core" / "prompt.txt"
    text = prompt_file.read_text(encoding="utf-8")
    assert "You are Slon" in text
    assert "You are JARVIS" not in text
    assert "shutdown_slon" in text


def test_wake_word_canonical() -> None:
    """Canonical default wake word must be 'Slon'."""
    wake_word = "Slon"
    assert wake_word == "Slon"
    assert wake_word.lower() == "slon"


def test_active_ui_and_main_identity() -> None:
    main_py = (BASE_DIR / "main.py").read_text(encoding="utf-8")
    lifecycle_py = (BASE_DIR / "runtime" / "lifecycle.py").read_text(encoding="utf-8")
    assert "SlonLive" in main_py
    assert "SlonUI" in main_py
    assert "SYS: Slon online." in lifecycle_py
    assert "You are Slon" in main_py

    ui_py = (BASE_DIR / "ui.py").read_text(encoding="utf-8")
    assert "class SlonUI:" in ui_py
    assert "SYS: Initialised. OS=" in ui_py and "Slon online." in ui_py


def test_ios_hud_identity() -> None:
    hud_swift = BASE_DIR / "ios" / "MarkRemote" / "DesignSystem" / "Components" / "MRHudView.swift"
    text = hud_swift.read_text(encoding="utf-8")
    assert '.accessibilityLabel("Slon")' in text
    assert '.accessibilityLabel("JARVIS")' not in text
