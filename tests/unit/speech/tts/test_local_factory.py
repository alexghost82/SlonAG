"""Unit tests for Piper local TTS factory (no real binary required)."""

from __future__ import annotations

from pathlib import Path

from speech.tts.local_factory import (
    LocalTTSBuildResult,
    default_piper_dir,
    resolve_piper_binary,
    try_build_local_tts,
)
from speech.tts.piper import DEFAULT_PIPER_VOICE
from speech.tts.provider import LocalTTSProvider


def test_default_piper_dir_under_models(tmp_path: Path) -> None:
    assert default_piper_dir(tmp_path) == (tmp_path / "models" / "piper").resolve()


def test_resolve_binary_prefers_models_piper(tmp_path: Path) -> None:
    piper_dir = tmp_path / "models" / "piper"
    piper_dir.mkdir(parents=True)
    binary = piper_dir / "piper"
    binary.write_text("x", encoding="utf-8")
    assert resolve_piper_binary(piper_dir) == binary


def test_try_build_degrades_when_missing(tmp_path: Path) -> None:
    result = try_build_local_tts(repo_root=tmp_path, validate=True)
    assert isinstance(result, LocalTTSBuildResult)
    assert result.ready is False
    assert result.provider is None
    assert "Piper" in result.message or "not found" in result.message.lower()


def test_try_build_ready_with_fixture_paths(tmp_path: Path) -> None:
    piper_dir = tmp_path / "models" / "piper"
    piper_dir.mkdir(parents=True)
    binary = piper_dir / "piper"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    model = piper_dir / f"{DEFAULT_PIPER_VOICE}.onnx"
    model.write_bytes(b"onnx")
    Path(str(model) + ".json").write_text("{}", encoding="utf-8")

    result = try_build_local_tts(repo_root=tmp_path, validate=True)
    assert result.ready is True
    assert isinstance(result.provider, LocalTTSProvider)
    assert result.voice == DEFAULT_PIPER_VOICE
    assert getattr(result.provider.engine, "model_path") == model
