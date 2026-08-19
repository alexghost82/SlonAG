"""CLI entry for the live Desktop Control API listener.

Examples::

    python -m server
    python -m server --host 127.0.0.1 --port 8765
    python -m server --host 192.168.1.20 --port 8765 --allow-non-loopback
    python -m server --tls --tls-generate
    python -m server --tls --tls-cert models/certs/desktop-control.crt \\
        --tls-key models/certs/desktop-control.key

Default bind is loopback. Same-LAN private addresses require
``--allow-non-loopback``. Wildcards and public binds are rejected.
Pairing and auth remain mandatory. TLS is optional (personal LAN).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from server.bind_policy import BindHostError
from server.listener import DEFAULT_BIND_HOST, DEFAULT_BIND_PORT, DesktopControlListener
from server.tls import TlsConfigError, ensure_tls_material


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server",
        description="Slon Desktop Control API (loopback-default listener)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_BIND_HOST,
        help=f"Bind host (default {DEFAULT_BIND_HOST}; loopback unless LAN opt-in)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_BIND_PORT,
        help=f"Bind port (default {DEFAULT_BIND_PORT})",
    )
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="Allow a private same-LAN bind_host (never wildcards/public)",
    )
    parser.add_argument(
        "--tls",
        action="store_true",
        help="Serve HTTPS using cert/key (see --tls-cert/--tls-key/--tls-generate)",
    )
    parser.add_argument(
        "--tls-cert",
        type=Path,
        default=None,
        help="PEM certificate path",
    )
    parser.add_argument(
        "--tls-key",
        type=Path,
        default=None,
        help="PEM private key path",
    )
    parser.add_argument(
        "--tls-generate",
        action="store_true",
        help="Generate a self-signed cert under models/certs/ if missing",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root for default models/certs/ layout",
    )
    parser.add_argument(
        "--bonjour",
        action="store_true",
        help="Advertise Desktop Control via Bonjour/mDNS (_mark-control._tcp)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tls_cert: Path | None = None
    tls_key: Path | None = None
    if args.tls or args.tls_cert or args.tls_key or args.tls_generate:
        try:
            material = ensure_tls_material(
                certfile=args.tls_cert,
                keyfile=args.tls_key,
                repo_root=args.repo_root,
                generate=bool(args.tls_generate),
            )
        except TlsConfigError as exc:
            print(f"tls rejected: {exc}", file=sys.stderr)
            return 2
        tls_cert = material.certfile
        tls_key = material.keyfile
        print(material.message)

    try:
        listener = DesktopControlListener(
            bind_host=args.host,
            bind_port=args.port,
            allow_non_loopback=bool(args.allow_non_loopback),
            tls_certfile=tls_cert,
            tls_keyfile=tls_key,
            require_tls=bool(args.tls),
            advertise_bonjour=bool(args.bonjour),
        )
    except (BindHostError, TlsConfigError) as exc:
        print(f"bind rejected: {exc}", file=sys.stderr)
        return 2

    host, port = listener.start()
    print(
        f"Desktop Control API listening on {listener.scheme}://{host}:{port}/v1 "
        f"(allow_non_loopback={listener.allow_non_loopback}, "
        f"tls={listener.tls_enabled}). "
        "Auth/pairing required. Ctrl+C to stop."
    )

    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        while not stop and listener.listening:
            time.sleep(0.25)
    finally:
        listener.stop()
        print("Desktop Control API stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
