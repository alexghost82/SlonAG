"""Unit tests for PiperSpeechSynthesizer. No real Piper binary or ONNX."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from providers.contracts import AudioStream, ModelInfo, SpeechRequest
from speech.tts.piper import (
    DEFAULT_PIPER_VOICE,
    PiperBinaryMissingError,
    PiperModelMissingError,
    PiperSpeechSynthesizer,
    PiperSynthesisError,
)
from speech.tts.provider import AUDIO_MIME_TYPE, LocalTTSProvider

# Minimal valid-looking WAV bytes (header only) for fake runner output.
_FAKE_WAV = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    b"D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
)


@dataclass
class _FakeCompleted:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


class _RecordingRunner:
    """Injected subprocess.run stand-in. Never launches a real process."""

    def __init__(self, *, stdout: bytes = _FAKE_WAV, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[dict[str, object]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> _FakeCompleted:
        self.calls.append({"argv": list(argv), **kwargs})
        return _FakeCompleted(returncode=self.returncode, stdout=self.stdout)


@pytest.fixture
def piper_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    binary = tmp_path / "piper"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    model = tmp_path / f"{DEFAULT_PIPER_VOICE}.onnx"
    model.write_bytes(b"onnx-fixture")
    config = Path(str(model) + ".json")
    config.write_text('{"audio":{"sample_rate":22050}}\n', encoding="utf-8")
    return binary, model, config


def test_synthesize_invokes_cli_with_model_and_stdout(
    piper_paths: tuple[Path, Path, Path],
) -> None:
    binary, model, _config = piper_paths
    runner = _RecordingRunner()
    engine = PiperSpeechSynthesizer(
        binary_path=binary,
        model_path=model,
        run=runner,
    )
    audio = engine.synthesize(
        "Привет.",
        voice=DEFAULT_PIPER_VOICE,
        speed=1.0,
        volume=1.0,
    )
    assert audio == _FAKE_WAV
    assert len(runner.calls) == 1
    call = runner.calls[0]
    argv = call["argv"]
    assert isinstance(argv, list)
    assert argv[0] == str(binary)
    assert "--model" in argv
    assert str(model) in argv
    assert argv[argv.index("--output-file") + 1] == "-"
    assert call["input"] == "Привет.".encode("utf-8")
    assert call["capture_output"] is True


def test_speed_maps_to_length_scale(piper_paths: tuple[Path, Path, Path]) -> None:
    binary, model, _config = piper_paths
    runner = _RecordingRunner()
    engine = PiperSpeechSynthesizer(binary_path=binary, model_path=model, run=runner)
    engine.synthesize("Текст.", voice=DEFAULT_PIPER_VOICE, speed=2.0, volume=0.5)
    argv = runner.calls[0]["argv"]
    assert isinstance(argv, list)
    scale = argv[argv.index("--length-scale") + 1]
    assert scale == "0.5"


def test_volume_is_noop_but_call_succeeds(
    piper_paths: tuple[Path, Path, Path],
) -> None:
    binary, model, _config = piper_paths
    runner = _RecordingRunner()
    engine = PiperSpeechSynthesizer(binary_path=binary, model_path=model, run=runner)
    audio = engine.synthesize(
        "Громкость.",
        voice=DEFAULT_PIPER_VOICE,
        speed=1.0,
        volume=0.0,
    )
    assert audio.startswith(b"RIFF")
    assert len(runner.calls) == 1


def test_missing_binary_raises(
    tmp_path: Path,
    piper_paths: tuple[Path, Path, Path],
) -> None:
    _binary, model, _config = piper_paths
    engine = PiperSpeechSynthesizer(
        binary_path=tmp_path / "missing-piper",
        model_path=model,
        run=_RecordingRunner(),
    )
    with pytest.raises(PiperBinaryMissingError):
        engine.synthesize("x", voice=DEFAULT_PIPER_VOICE, speed=1.0, volume=1.0)


def test_missing_model_raises(piper_paths: tuple[Path, Path, Path]) -> None:
    binary, model, _config = piper_paths
    engine = PiperSpeechSynthesizer(
        binary_path=binary,
        model_path=model.parent / "absent.onnx",
        run=_RecordingRunner(),
    )
    with pytest.raises(PiperModelMissingError):
        engine.synthesize("x", voice=DEFAULT_PIPER_VOICE, speed=1.0, volume=1.0)


def test_missing_config_json_raises(piper_paths: tuple[Path, Path, Path]) -> None:
    binary, model, config = piper_paths
    config.unlink()
    engine = PiperSpeechSynthesizer(
        binary_path=binary,
        model_path=model,
        run=_RecordingRunner(),
    )
    with pytest.raises(PiperModelMissingError):
        engine.synthesize("x", voice=DEFAULT_PIPER_VOICE, speed=1.0, volume=1.0)


def test_nonzero_exit_raises(piper_paths: tuple[Path, Path, Path]) -> None:
    binary, model, _config = piper_paths
    runner = _RecordingRunner(returncode=2, stdout=b"")
    engine = PiperSpeechSynthesizer(binary_path=binary, model_path=model, run=runner)
    with pytest.raises(PiperSynthesisError):
        engine.synthesize("x", voice=DEFAULT_PIPER_VOICE, speed=1.0, volume=1.0)


def test_model_dir_layout(tmp_path: Path) -> None:
    binary = tmp_path / "piper"
    binary.write_text("x", encoding="utf-8")
    model_dir = tmp_path / "models" / "piper"
    model_dir.mkdir(parents=True)
    model = model_dir / f"{DEFAULT_PIPER_VOICE}.onnx"
    model.write_bytes(b"onnx")
    Path(str(model) + ".json").write_text("{}", encoding="utf-8")
    runner = _RecordingRunner()
    engine = PiperSpeechSynthesizer(
        binary_path=binary,
        model_dir=model_dir,
        run=runner,
    )
    assert engine.model_path == model
    engine.synthesize("Ок.", voice=DEFAULT_PIPER_VOICE, speed=1.0, volume=1.0)
    assert runner.calls


@pytest.mark.asyncio
async def test_local_tts_provider_wav_mime_with_piper(
    piper_paths: tuple[Path, Path, Path],
) -> None:
    binary, model, _config = piper_paths
    engine = PiperSpeechSynthesizer(
        binary_path=binary,
        model_path=model,
        run=_RecordingRunner(),
    )
    provider = LocalTTSProvider(engine=engine, voice=DEFAULT_PIPER_VOICE)
    stream = await provider.synthesize(
        SpeechRequest(
            model=ModelInfo(
                provider_id="tts_local",
                model_id="piper",
                display_name="Piper",
                audio_output=True,
                local=True,
                source="test",
                license="MIT",
            ),
            text="Один. Два.",
        )
    )
    assert isinstance(stream, AudioStream)
    assert stream.mime_type == AUDIO_MIME_TYPE
    assert stream.mime_type == "audio/wav"
    assert stream.data == _FAKE_WAV + _FAKE_WAV


@pytest.mark.asyncio
async def test_russian_sentences_reach_engine_via_provider(
    piper_paths: tuple[Path, Path, Path],
) -> None:
    binary, model, _config = piper_paths
    runner = _RecordingRunner()
    engine = PiperSpeechSynthesizer(binary_path=binary, model_path=model, run=runner)
    provider = LocalTTSProvider(engine=engine, voice=DEFAULT_PIPER_VOICE)
    await provider.preview("Привет. Как дела?")
    texts = []
    for call in runner.calls:
        raw = call["input"]
        if isinstance(raw, (bytes, bytearray)):
            texts.append(bytes(raw).decode("utf-8"))
        else:
            texts.append(str(raw))
    assert texts == ["Привет.", "Как дела?"]
