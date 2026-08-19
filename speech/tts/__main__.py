"""CLI for Piper TTS helpers.

Examples::

    python -m speech.tts download --consent
    python -m speech.tts download --consent --dry-run
    python -m speech.tts download --consent --force

Requires explicit ``--consent``. Does not download on import.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from speech.tts.download import (
    DEFAULT_VOICE,
    PiperDownloadConsentError,
    PiperDownloadError,
    download_piper_voice,
)
from speech.tts.local_factory import default_piper_dir, resolve_piper_binary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m speech.tts",
        description="Slon Piper TTS utilities (opt-in download)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser(
        "download",
        help=f"Download {DEFAULT_VOICE} ONNX + JSON into models/piper/",
    )
    dl.add_argument(
        "--consent",
        action="store_true",
        help="Required. Confirms operator-approved network download.",
    )
    dl.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: cwd)",
    )
    dl.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Override destination directory",
    )
    dl.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files exist",
    )
    dl.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve paths and print plan; no network",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "download":
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2

    piper_dir = (
        Path(args.dest).expanduser()
        if args.dest is not None
        else default_piper_dir(args.repo_root)
    )
    binary = resolve_piper_binary(piper_dir)
    print(
        "Binary strategy: prefer a local MIT rhasspy/piper binary at "
        f"{piper_dir / 'piper'} or on PATH as 'piper'. "
        "On Apple Silicon, the historical official macOS aarch64 release "
        "tarball has been unreliable — use Homebrew or build from source. "
        f"Resolved binary hint: {binary}"
    )

    try:
        result = download_piper_voice(
            consent=bool(args.consent),
            repo_root=args.repo_root,
            dest_dir=args.dest,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
        )
    except PiperDownloadConsentError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except PiperDownloadError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(result.message)
    print(f"model={result.model_path}")
    print(f"config={result.config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
