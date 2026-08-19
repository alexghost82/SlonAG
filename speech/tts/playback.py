"""Optional WAV playback for local TTS preview (no network)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def play_wav_bytes(data: bytes) -> None:
    """Play WAV bytes via an OS helper (afplay / aplay / paplay).

    Empty data is a no-op. Raises ``RuntimeError`` when no helper works.
    """
    if not data:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(data)
        path = Path(handle.name)
    try:
        if _play_os_helper(path):
            return
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    raise RuntimeError(
        "No local audio playback backend available (need afplay/aplay/paplay)."
    )


def _play_os_helper(path: Path) -> bool:
    commands: list[tuple[str, ...]]
    if sys.platform == "darwin":
        commands = [("afplay", str(path))]
    elif sys.platform.startswith("linux"):
        commands = (("aplay", str(path)), ("paplay", str(path)))
    else:
        return False
    for cmd in commands:
        completed = subprocess.run(cmd, check=False, capture_output=True)
        if completed.returncode == 0:
            return True
    return False


__all__ = ["play_wav_bytes"]
