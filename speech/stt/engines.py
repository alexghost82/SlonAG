"""Injectable STT engines. Optional whisper; never opens the network here."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class CallbackSTTEngine:
    """Delegate transcription to an injected callable (tests / UI glue)."""

    def __init__(self, transcribe_fn: Callable[[bytes, str], str]) -> None:
        self._transcribe_fn = transcribe_fn

    def transcribe(self, audio: bytes, language: str) -> str:
        return self._transcribe_fn(audio, language)


class EmptySTTEngine:
    """Mic path ready, but no local ASR model — always empty transcript."""

    def transcribe(self, audio: bytes, language: str) -> str:
        return ""


class OptionalWhisperEngine:
    """Use ``whisper`` if installed; otherwise raise on first transcribe."""

    def __init__(self, model_name: str = "base", module: Any | None = None) -> None:
        self.model_name = model_name
        self._module = module
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        mod = self._module
        if mod is None:
            import whisper

            mod = whisper
        self._model = mod.load_model(self.model_name)
        return self._model

    def transcribe(self, audio: bytes, language: str) -> str:
        import tempfile
        from pathlib import Path

        model = self._load()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            handle.write(audio)
            path = Path(handle.name)
        try:
            result = model.transcribe(str(path), language=language or None)
        finally:
            path.unlink(missing_ok=True)
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        return str(text).strip()


def try_whisper_engine(model_name: str = "base") -> OptionalWhisperEngine | None:
    """Return a whisper engine when the package imports; else ``None``."""
    try:
        import whisper  # noqa: F401
    except Exception:
        return None
    return OptionalWhisperEngine(model_name=model_name)


__all__ = [
    "CallbackSTTEngine",
    "EmptySTTEngine",
    "OptionalWhisperEngine",
    "try_whisper_engine",
]
