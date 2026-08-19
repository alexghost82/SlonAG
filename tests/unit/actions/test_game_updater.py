"""Unit tests for the optional winreg guard in actions.game_updater."""

from __future__ import annotations


def test_game_updater_imports_without_winreg():
    import actions.game_updater as game_updater

    assert game_updater.game_updater is not None


def test_find_steam_path_returns_none_when_winreg_missing(monkeypatch):
    import actions.game_updater as game_updater

    monkeypatch.setattr(game_updater, "winreg", None)
    assert game_updater._find_steam_path() is None


def test_find_epic_path_returns_none_when_winreg_missing(monkeypatch):
    import actions.game_updater as game_updater

    monkeypatch.setattr(game_updater, "winreg", None)
    assert game_updater._find_epic_path() is None
