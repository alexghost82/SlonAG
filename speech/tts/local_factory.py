"""Build a Piper-backed ``LocalTTSProvider`` for the desktop UI.

Resolves binary/model paths under ``models/piper/`` (see ``piper.py``).
Never downloads models or API keys. Missing assets degrade gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from speech.tts.piper import (
    DEFAULT_PIPER_VOICE,
    PiperBinaryMissingError,
    PiperModelMissingError,
    PiperSpeechSynthesizer,
)
from speech.tts.provider import LocalTTSProvider

DEFAULT_BINARY_NAME = "piper"


@dataclass(frozen=True)
class LocalTTSBuildResult:
    """Outcome of attempting to construct local TTS for the UI."""

    provider: LocalTTSProvider | None
    ready: bool
    message: str
    binary_path: Path | None = None
    model_path: Path | None = None
    voice: str = DEFAULT_PIPER_VOICE


def default_piper_dir(repo_root: str | Path | None = None) -> Path:
    """Return ``<repo>/models/piper`` (or cwd-relative when root omitted)."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return (root / "models" / "piper").resolve()


def resolve_piper_binary(piper_dir: Path) -> Path:
    """Prefer ``models/piper/piper``, else bare ``piper`` for PATH lookup."""
    candidate = piper_dir / DEFAULT_BINARY_NAME
    if candidate.is_file():
        return candidate
    return Path(DEFAULT_BINARY_NAME)


def try_build_local_tts(
    *,
    repo_root: str | Path | None = None,
    voice: str = DEFAULT_PIPER_VOICE,
    speed: float = 1.0,
    volume: float = 1.0,
    validate: bool = True,
) -> LocalTTSBuildResult:
    """Construct ``LocalTTSProvider(engine=PiperSpeechSynthesizer(...))``.

    When ``validate`` is True (default), missing binary/onnx yields
    ``ready=False`` and ``provider=None`` with a clear message — never raises
    for absent assets. Does not auto-download.
    """
    piper_dir = default_piper_dir(repo_root)
    binary = resolve_piper_binary(piper_dir)
    model_path = piper_dir / f"{voice}.onnx"
    try:
        engine = PiperSpeechSynthesizer(
            binary_path=binary,
            model_path=model_path,
            voice=voice,
            validate_on_init=bool(validate),
        )
    except (PiperBinaryMissingError, PiperModelMissingError) as exc:
        return LocalTTSBuildResult(
            provider=None,
            ready=False,
            message=str(exc),
            binary_path=binary,
            model_path=model_path,
            voice=voice,
        )
    except (OSError, ValueError, TypeError) as exc:
        return LocalTTSBuildResult(
            provider=None,
            ready=False,
            message=f"Local TTS unavailable: {exc}",
            binary_path=binary,
            model_path=model_path,
            voice=voice,
        )

    provider = LocalTTSProvider(
        engine=engine,
        voice=voice,
        speed=speed,
        volume=volume,
    )
    return LocalTTSBuildResult(
        provider=provider,
        ready=True,
        message=(
            f"Local TTS ready (Piper {voice}; "
            f"binary={engine.binary_path}; model={engine.model_path})."
        ),
        binary_path=engine.binary_path,
        model_path=engine.model_path,
        voice=voice,
    )


__all__ = [
    "DEFAULT_BINARY_NAME",
    "LocalTTSBuildResult",
    "default_piper_dir",
    "resolve_piper_binary",
    "try_build_local_tts",
]
