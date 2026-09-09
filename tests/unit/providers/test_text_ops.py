from __future__ import annotations

import pytest

from providers.text_ops import LocalOnlyBlocked, complete_text


def test_complete_text_fail_closed_local_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("providers.text_ops._settings_forbid_cloud", lambda: True)
    with pytest.raises(LocalOnlyBlocked):
        complete_text("hello")


def test_compat_client_returns_empty_when_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("providers.text_ops._settings_forbid_cloud", lambda: True)
    from providers.text_ops import client

    assert client.chat("remember this") == ""
