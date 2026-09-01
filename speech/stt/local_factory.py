"""Build a mic-backed ``LocalSTTProvider`` for desktop UI / bridge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from speech.stt.engines import EmptySTTEngine, try_faster_whisper_engine
from speech.stt.mic import MicCapture, MicCaptureError
from speech.stt.provider import DEFAULT_LANGUAGE, LocalSTTProvider

SpeakingFlag = Callable[[], bool]


@dataclass(frozen=True)
class LocalSTTBuildResult:
    """Outcome of constructing local STT + optional mic capture."""

    provider: LocalSTTProvider | None
    mic: MicCapture | None
    ready: bool
    mic_ready: bool
    message: str
    asr_backend: str = "none"


def try_build_local_stt(
    *,
    repo_root: str | Path | None = None,  # noqa: ARG001 — reserved for model dirs
    language: str = DEFAULT_LANGUAGE,
    is_assistant_speaking: SpeakingFlag | None = None,
    prefer_whisper: bool = True,
    require_mic: bool = False,
) -> LocalSTTBuildResult:
    """Assemble STT with echo-guard hook. Missing ASR degrades (empty engine).

    Microphone probe is optional: when sounddevice cannot open a device,
    ``mic_ready`` is False but a provider may still exist for injected audio.
    """
    _ = repo_root
    asr_backend = "empty"
    engine: object
    model_path = Path(repo_root or Path.cwd()) / "models" / "whisper" / "base"
    faster_whisper = (
        try_faster_whisper_engine(str(model_path)) if prefer_whisper and model_path.is_dir() else None
    )
    if faster_whisper is not None:
        engine = faster_whisper
        asr_backend = "faster_whisper"
    else:
        engine = EmptySTTEngine()

    provider = LocalSTTProvider(
        engine,  # type: ignore[arg-type]
        language=language,
        is_assistant_speaking=is_assistant_speaking,
    )

    mic: MicCapture | None = None
    mic_ready = False
    mic_message = "mic not probed"
    try:
        mic = MicCapture()
        # Lightweight device query — does not record.
        sd = mic._sd_mod()
        _ = sd.query_devices(kind="input")
        mic_ready = True
        mic_message = "mic ready"
    except MicCaptureError as exc:
        mic = None
        mic_ready = False
        mic_message = str(exc)
    except Exception as exc:  # noqa: BLE001
        mic = None
        mic_ready = False
        mic_message = f"mic unavailable: {exc}"

    if require_mic and not mic_ready:
        return LocalSTTBuildResult(
            provider=None,
            mic=None,
            ready=False,
            mic_ready=False,
            message=mic_message,
            asr_backend=asr_backend,
        )

    ready = True
    parts = [f"asr={asr_backend}", mic_message]
    if asr_backend == "empty":
        parts.append(f"offline ASR model missing: {model_path}")
    return LocalSTTBuildResult(
        provider=provider,
        mic=mic if mic_ready else None,
        ready=ready,
        mic_ready=mic_ready,
        message="; ".join(parts),
        asr_backend=asr_backend,
    )


__all__ = [
    "LocalSTTBuildResult",
    "try_build_local_stt",
]
