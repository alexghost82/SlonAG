"""Opt-in download helper for Piper ONNX voices.

Never downloads unless ``consent=True``. Network I/O goes through an injected
``fetcher`` so unit tests and CI stay offline.

Default voice: ``ru_RU-dmitri-medium`` (MIT; dataset CC0) from
rhasspy/piper-voices on Hugging Face.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from speech.tts.piper import DEFAULT_PIPER_VOICE

DEFAULT_VOICE = DEFAULT_PIPER_VOICE
HF_VOICE_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "ru/ru_RU/dmitri/medium"
)
VOICE_FILES: tuple[str, str] = (
    f"{DEFAULT_VOICE}.onnx",
    f"{DEFAULT_VOICE}.onnx.json",
)

Fetcher = Callable[[str], bytes]


class PiperDownloadConsentError(PermissionError):
    """Raised when download is requested without explicit consent."""


class PiperDownloadError(RuntimeError):
    """Raised when a consented download fails."""


@dataclass(frozen=True)
class PiperDownloadResult:
    """Paths written (or that would be written on dry-run)."""

    voice: str
    model_path: Path
    config_path: Path
    downloaded: bool
    skipped_existing: bool
    message: str


def default_piper_model_dir(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return (root / "models" / "piper").resolve()


def voice_urls(voice: str = DEFAULT_VOICE) -> dict[str, str]:
    """Return filename → URL map for the known default voice family."""
    if voice != DEFAULT_VOICE:
        raise PiperDownloadError(
            f"Unsupported voice for download helper: {voice!r}. "
            f"Only {DEFAULT_VOICE!r} is wired in Wave 13."
        )
    return {
        VOICE_FILES[0]: f"{HF_VOICE_BASE}/{VOICE_FILES[0]}",
        VOICE_FILES[1]: f"{HF_VOICE_BASE}/{VOICE_FILES[1]}",
    }


def _stdlib_fetcher(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — operator opt-in
        return resp.read()


def download_piper_voice(
    *,
    consent: bool,
    repo_root: str | Path | None = None,
    dest_dir: str | Path | None = None,
    voice: str = DEFAULT_VOICE,
    fetcher: Fetcher | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> PiperDownloadResult:
    """Download onnx + json into ``models/piper/`` when ``consent`` is True.

    Parameters
    ----------
    consent:
        Must be True. False raises ``PiperDownloadConsentError`` and performs
        no I/O beyond path resolution.
    fetcher:
        Injected ``url -> bytes``. Defaults to stdlib urllib (real network).
        Tests must pass a fake fetcher.
    """
    if not consent:
        raise PiperDownloadConsentError(
            "Piper voice download requires explicit consent=True "
            "(or CLI --consent). Refusing network access."
        )

    target = (
        Path(dest_dir).expanduser().resolve()
        if dest_dir is not None
        else default_piper_model_dir(repo_root)
    )
    urls = voice_urls(voice)
    model_name, config_name = VOICE_FILES
    model_path = target / model_name
    config_path = target / config_name

    if (
        not force
        and model_path.is_file()
        and config_path.is_file()
        and model_path.stat().st_size > 0
        and config_path.stat().st_size > 0
    ):
        return PiperDownloadResult(
            voice=voice,
            model_path=model_path,
            config_path=config_path,
            downloaded=False,
            skipped_existing=True,
            message=f"Voice assets already present under {target}",
        )

    if dry_run:
        return PiperDownloadResult(
            voice=voice,
            model_path=model_path,
            config_path=config_path,
            downloaded=False,
            skipped_existing=False,
            message=f"Dry-run: would download into {target}",
        )

    fetch = fetcher if fetcher is not None else _stdlib_fetcher
    target.mkdir(parents=True, exist_ok=True)
    try:
        for name, url in urls.items():
            data = fetch(url)
            if not data:
                raise PiperDownloadError(f"Empty response for {name}")
            (target / name).write_bytes(data)
    except PiperDownloadError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        raise PiperDownloadError(f"Download failed: {exc}") from exc

    return PiperDownloadResult(
        voice=voice,
        model_path=model_path,
        config_path=config_path,
        downloaded=True,
        skipped_existing=False,
        message=f"Downloaded {voice} into {target}",
    )


__all__ = [
    "DEFAULT_VOICE",
    "HF_VOICE_BASE",
    "PiperDownloadConsentError",
    "PiperDownloadError",
    "PiperDownloadResult",
    "VOICE_FILES",
    "default_piper_model_dir",
    "download_piper_voice",
    "voice_urls",
]
