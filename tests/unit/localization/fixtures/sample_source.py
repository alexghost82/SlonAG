"""Fixture source for the hardcoded-string scanner. Imported only as text."""

from localization import tr


def build_placeholder() -> str:
    return "Type a command"


def build_status() -> str:
    return tr("status.ready")


def build_window_title() -> str:
    return tr("window.title")
