"""Voice test fixtures."""

from __future__ import annotations

import sys

import pytest

from providers.registry import clear


class _MockSounddevice:
    """Minimal sounddevice mock for headless CI."""

    class RawOutputStream:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass
        def write(self, data):
            pass
        def stop(self):
            pass
        def close(self):
            pass

    class InputStream:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass
        def stop(self):
            pass
        def close(self):
            pass

    def query_devices(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _mock_sounddevice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace sounddevice with a mock for all voice tests."""
    monkeypatch.setitem(sys.modules, "sounddevice", _MockSounddevice())


@pytest.fixture
def clean_registry():
    """Empty the process-wide registry around each test."""
    clear()
    yield
    clear()


@pytest.fixture
def fake_ui():
    """Provide a mock UI for VoiceBridge tests."""
    from tests.unit.speech.voice.fakes import FakeUI
    return FakeUI()
