"""Offline unit tests for opt-in Piper voice download."""

from __future__ import annotations

from pathlib import Path

import pytest

from speech.tts.download import (
    DEFAULT_VOICE,
    PiperDownloadConsentError,
    PiperDownloadError,
    download_piper_voice,
    voice_urls,
)


def test_consent_required_no_fetcher_call(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"x"

    with pytest.raises(PiperDownloadConsentError):
        download_piper_voice(
            consent=False,
            dest_dir=tmp_path,
            fetcher=fetcher,
        )
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_download_with_injected_fetcher(tmp_path: Path) -> None:
    urls = voice_urls()
    payloads = {url: f"data-for-{name}".encode() for name, url in urls.items()}

    def fetcher(url: str) -> bytes:
        return payloads[url]

    result = download_piper_voice(
        consent=True,
        dest_dir=tmp_path,
        fetcher=fetcher,
    )
    assert result.downloaded is True
    assert result.skipped_existing is False
    assert result.model_path.is_file()
    assert result.config_path.is_file()
    assert result.model_path.read_bytes() == payloads[urls[f"{DEFAULT_VOICE}.onnx"]]


def test_skip_existing_without_network(tmp_path: Path) -> None:
    model = tmp_path / f"{DEFAULT_VOICE}.onnx"
    config = tmp_path / f"{DEFAULT_VOICE}.onnx.json"
    model.write_bytes(b"onnx")
    config.write_bytes(b"{}")
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"nope"

    result = download_piper_voice(
        consent=True,
        dest_dir=tmp_path,
        fetcher=fetcher,
    )
    assert result.skipped_existing is True
    assert result.downloaded is False
    assert calls == []


def test_dry_run_no_write(tmp_path: Path) -> None:
    result = download_piper_voice(
        consent=True,
        dest_dir=tmp_path,
        dry_run=True,
        fetcher=lambda url: b"should-not-run",
    )
    assert result.downloaded is False
    assert not result.model_path.exists()
    assert "Dry-run" in result.message


def test_unsupported_voice() -> None:
    with pytest.raises(PiperDownloadError):
        voice_urls("en_US-lessac-medium")
