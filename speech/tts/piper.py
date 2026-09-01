"""Local Piper TTS engine (rhasspy/piper MIT CLI).

Injectable ``SpeechSynthesizer`` for ``LocalTTSProvider``. Invokes a
user-supplied local Piper binary; does not download models or call the
network.

Default voice id: ``ru_RU-dmitri-medium`` (MIT; training dataset CC0).

Expected model layout (gitignored under repo ``/models/``)::

    models/piper/ru_RU-dmitri-medium.onnx
    models/piper/ru_RU-dmitri-medium.onnx.json

Manual fetch (operator-run only; never from library code or CI)::

    # Obtain the MIT rhasspy/piper binary for your OS, then:
    # https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU/dmitri/medium

Do **not** treat OHF-Voice ``piper1-gpl`` as the project default. If only a
GPL binary is installed on the machine, record that license separately; this
module still documents rhasspy/piper (MIT) as the intended runtime.

``speed`` maps to Piper ``--length-scale`` as ``1.0 / speed`` when
``speed > 0``; ``volume`` is accepted and ignored (WAV gain out of scope).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_PIPER_VOICE = "ru_RU-dmitri-medium"
DEFAULT_MODEL_RELATIVE = Path("models") / "piper" / f"{DEFAULT_PIPER_VOICE}.onnx"

RunHook = Callable[..., Any]


class PiperBinaryMissingError(FileNotFoundError):
    """Raised when the configured Piper binary path does not exist."""


class PiperModelMissingError(FileNotFoundError):
    """Raised when the configured ONNX model (or sidecar JSON) is missing."""


class PiperSynthesisError(RuntimeError):
    """Raised when the Piper process exits non-zero or returns empty audio."""


class PiperSpeechSynthesizer:
    """``SpeechSynthesizer`` that shells out to a local rhasspy/piper CLI."""

    def __init__(
        self,
        *,
        binary_path: str | Path,
        model_path: str | Path | None = None,
        model_dir: str | Path | None = None,
        voice: str = DEFAULT_PIPER_VOICE,
        run: RunHook | None = None,
        validate_on_init: bool = False,
    ) -> None:
        if model_path is not None and model_dir is not None:
            raise ValueError("Pass model_path or model_dir, not both")
        self.binary_path = Path(binary_path).expanduser()
        self.voice = voice.strip() if isinstance(voice, str) else ""
        if not self.voice:
            raise ValueError("voice must be a non-empty string")
        if model_path is not None:
            self.model_path = Path(model_path).expanduser()
        elif model_dir is not None:
            self.model_path = Path(model_dir).expanduser() / f"{self.voice}.onnx"
        else:
            self.model_path = Path.cwd() / DEFAULT_MODEL_RELATIVE
        self._run: RunHook = run if run is not None else subprocess.run
        if validate_on_init:
            self._require_paths()

    @property
    def config_json_path(self) -> Path:
        """Sidecar JSON expected beside the ONNX model."""
        return Path(str(self.model_path) + ".json")

    def synthesize(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        volume: float,
    ) -> bytes:
        """Synthesize ``text`` to WAV bytes via the local Piper binary.

        ``voice`` is accepted for protocol compatibility; this engine always
        uses the ONNX configured at construction (default
        ``ru_RU-dmitri-medium``). ``volume`` is intentionally a no-op.
        """
        del voice, volume  # protocol kwargs; volume gain out of scope
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        sentence = text.strip()
        if not sentence:
            return b""
        self._require_paths()
        length_scale = _length_scale_for_speed(speed)
        argv = self._build_argv(length_scale=length_scale)
        completed = self._run(
            argv,
            input=sentence.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        return_code = int(getattr(completed, "returncode", 1))
        stdout = getattr(completed, "stdout", b"") or b""
        stderr = getattr(completed, "stderr", b"") or b""
        if return_code != 0:
            detail = _decode_stderr(stderr)
            raise PiperSynthesisError(
                f"Piper exited with code {return_code}"
                + (f": {detail}" if detail else "")
            )
        if not stdout:
            raise PiperSynthesisError("Piper returned empty audio output")
        return bytes(stdout)

    def _build_argv(self, *, length_scale: float) -> list[str]:
        argv = [
            str(self.binary_path),
            "--model",
            str(self.model_path),
            "--output-file",
            "-",
            "--length-scale",
            f"{length_scale:.6g}",
        ]
        espeak_data = self.binary_path.parent / "espeak-ng-data"
        if espeak_data.is_dir():
            argv.extend(("--espeak_data", str(espeak_data)))
        return argv

    def _require_paths(self) -> None:
        binary = self.binary_path
        if not binary.is_file():
            # Allow PATH lookup only when the configured path has no directory.
            if binary.parent == Path(".") and shutil.which(str(binary)):
                resolved = shutil.which(str(binary))
                assert resolved is not None
                self.binary_path = Path(resolved)
            else:
                raise PiperBinaryMissingError(
                    f"Piper binary not found: {self.binary_path}. "
                    "Install the rhasspy/piper MIT CLI and pass binary_path."
                )
        if not self.model_path.is_file():
            raise PiperModelMissingError(
                f"Piper model not found: {self.model_path}. "
                "Place the ONNX under models/piper/ or pass an absolute path. "
                "Models are never auto-downloaded."
            )
        if not self.config_json_path.is_file():
            raise PiperModelMissingError(
                f"Piper model config not found: {self.config_json_path}. "
                "Expected a matching .onnx.json sidecar (no auto-download)."
            )


def _length_scale_for_speed(speed: float) -> float:
    """Map provider speed (>1 faster) to Piper length-scale (>1 slower)."""
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return 1.0
    if value <= 0:
        return 1.0
    return 1.0 / value


def _decode_stderr(stderr: bytes | str) -> str:
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace").strip()
    return str(stderr).strip()


def resolve_default_model_path(repo_root: str | Path | None = None) -> Path:
    """Return the documented default ONNX path under ``models/piper/``."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return (root / DEFAULT_MODEL_RELATIVE).resolve()


__all__ = [
    "DEFAULT_MODEL_RELATIVE",
    "DEFAULT_PIPER_VOICE",
    "PiperBinaryMissingError",
    "PiperModelMissingError",
    "PiperSpeechSynthesizer",
    "PiperSynthesisError",
    "resolve_default_model_path",
]
