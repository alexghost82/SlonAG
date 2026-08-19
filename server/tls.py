"""TLS helpers for the Desktop Control LAN / loopback listener.

Personal/non-commercial use: generate a short-lived self-signed cert via the
``openssl`` CLI when available, or document mkcert. Never commit key material.
"""

from __future__ import annotations

import ssl
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CERT_DIR_RELATIVE = Path("models") / "certs"
DEFAULT_CERT_NAME = "desktop-control.crt"
DEFAULT_KEY_NAME = "desktop-control.key"
DEFAULT_COMMON_NAME = "mark-desktop.local"


class TlsConfigError(ValueError):
    """Invalid TLS paths or generation failure."""


@dataclass(frozen=True)
class TlsMaterial:
    """Filesystem paths for a PEM cert + private key."""

    certfile: Path
    keyfile: Path
    generated: bool
    message: str


def default_cert_dir(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return (root / DEFAULT_CERT_DIR_RELATIVE).resolve()


def resolve_tls_paths(
    *,
    certfile: str | Path | None = None,
    keyfile: str | Path | None = None,
    cert_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> tuple[Path, Path]:
    if certfile is not None and keyfile is not None:
        return Path(certfile).expanduser(), Path(keyfile).expanduser()
    if certfile is not None or keyfile is not None:
        raise TlsConfigError("Pass both certfile and keyfile, or neither")
    base = (
        Path(cert_dir).expanduser().resolve()
        if cert_dir is not None
        else default_cert_dir(repo_root)
    )
    return base / DEFAULT_CERT_NAME, base / DEFAULT_KEY_NAME


def generate_self_signed_cert(
    certfile: str | Path,
    keyfile: str | Path,
    *,
    common_name: str = DEFAULT_COMMON_NAME,
    days: int = 825,
    openssl_bin: str = "openssl",
) -> TlsMaterial:
    """Create a self-signed server cert with ``openssl req -x509``.

    Requires ``openssl`` on PATH (or ``openssl_bin``). Suitable for same-LAN
    personal use; iOS must trust the cert (Settings → Certificate Trust) or use
    mkcert-generated material instead — see ``docs/audit/tls-lan.md``.
    """
    cert_path = Path(certfile).expanduser()
    key_path = Path(keyfile).expanduser()
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        openssl_bin,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-sha256",
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        str(int(days)),
        "-subj",
        f"/CN={common_name}",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise TlsConfigError(
            f"openssl not found ({openssl_bin!r}). Install OpenSSL or use mkcert; "
            "see docs/audit/tls-lan.md"
        ) from exc
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise TlsConfigError(f"openssl failed: {err or completed.returncode}")
    if not cert_path.is_file() or not key_path.is_file():
        raise TlsConfigError("openssl reported success but cert/key missing")
    return TlsMaterial(
        certfile=cert_path,
        keyfile=key_path,
        generated=True,
        message=f"Generated self-signed TLS material for CN={common_name}",
    )


def ensure_tls_material(
    *,
    certfile: str | Path | None = None,
    keyfile: str | Path | None = None,
    cert_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    generate: bool = False,
    common_name: str = DEFAULT_COMMON_NAME,
) -> TlsMaterial:
    """Return existing cert/key paths, or generate when ``generate`` is True."""
    cert_path, key_path = resolve_tls_paths(
        certfile=certfile,
        keyfile=keyfile,
        cert_dir=cert_dir,
        repo_root=repo_root,
    )
    if cert_path.is_file() and key_path.is_file():
        return TlsMaterial(
            certfile=cert_path,
            keyfile=key_path,
            generated=False,
            message=f"Using existing TLS material at {cert_path}",
        )
    if not generate:
        raise TlsConfigError(
            f"TLS material missing ({cert_path}, {key_path}). "
            "Pass generate=True / --tls-generate, or provide --tls-cert/--tls-key."
        )
    return generate_self_signed_cert(
        cert_path,
        key_path,
        common_name=common_name,
    )


def build_server_ssl_context(
    certfile: str | Path, keyfile: str | Path
) -> ssl.SSLContext:
    """Build a TLS server context for ``ThreadingHTTPServer``."""
    cert_path = Path(certfile)
    key_path = Path(keyfile)
    if not cert_path.is_file() or not key_path.is_file():
        raise TlsConfigError(f"TLS files not found: {cert_path}, {key_path}")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx


__all__ = [
    "DEFAULT_CERT_DIR_RELATIVE",
    "DEFAULT_CERT_NAME",
    "DEFAULT_COMMON_NAME",
    "DEFAULT_KEY_NAME",
    "TlsConfigError",
    "TlsMaterial",
    "build_server_ssl_context",
    "default_cert_dir",
    "ensure_tls_material",
    "generate_self_signed_cert",
    "resolve_tls_paths",
]
