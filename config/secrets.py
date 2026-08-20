"""Named secret storage via OS stores, with a 0600 file fallback.

Supported names: ``gemini_api_key``, ``openrouter_api_key``, ``openai_api_key``.

Resolution order:
1. macOS Keychain through the ``security`` CLI, when available;
2. Windows Credential Manager through ``ctypes``, when available;
3. Linux Secret Service through ``secret-tool``, when that platform tool exists;
4. ``config/api_keys.json`` with mode ``0600`` only if no system store is available.

This module never logs or prints secret values, and exception messages must
not echo them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KNOWN_SECRET_NAMES = frozenset(
    {"gemini_api_key", "openrouter_api_key", "openai_api_key"}
)
SERVICE_NAME = "Slon"
FALLBACK_PATH = Path(__file__).resolve().parent / "api_keys.json"


class SecretStoreError(RuntimeError):
    """Secret store failure. Messages must never include secret values."""


def get_secret(name: str) -> str | None:
    """Return a named secret, or ``None`` when it is not stored."""
    _validate_secret_name(name)
    try:
        if _system_store_available():
            value = _system_get(name)
        else:
            value = _file_get(name)
    except SecretStoreError:
        raise
    except Exception:
        raise SecretStoreError(f"failed to read secret {name}") from None
    if not isinstance(value, str) or not value:
        return None
    return value


def set_secret(name: str, value: str) -> None:
    """Store a named secret. ``value`` must never appear in exceptions."""
    _validate_secret_name(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"secret {name} must be a non-empty string")
    try:
        if _system_store_available():
            _system_set(name, value)
        else:
            _file_set(name, value)
    except SecretStoreError:
        raise
    except Exception:
        raise SecretStoreError(f"failed to store secret {name}") from None


def _validate_secret_name(name: str) -> None:
    if name not in KNOWN_SECRET_NAMES:
        raise ValueError(f"unknown secret name {name!r}")


def _system_store_available() -> bool:
    if sys.platform == "darwin":
        return shutil.which("security") is not None
    if sys.platform == "win32":
        return _windows_available()
    if sys.platform.startswith("linux"):
        return shutil.which("secret-tool") is not None
    return False


def _system_get(name: str) -> str | None:
    if sys.platform == "darwin":
        return _macos_get(name)
    if sys.platform == "win32":
        return _windows_get(name)
    if sys.platform.startswith("linux"):
        return _linux_get(name)
    return None


def _system_set(name: str, value: str) -> None:
    if sys.platform == "darwin":
        _macos_set(name, value)
        return
    if sys.platform == "win32":
        _windows_set(name, value)
        return
    if sys.platform.startswith("linux"):
        _linux_set(name, value)
        return
    raise SecretStoreError("no system secret store on this platform")


def _run_tool(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _macos_get(name: str) -> str | None:
    result = _run_tool(
        ["security", "find-generic-password", "-s", SERVICE_NAME, "-a", name, "-w"]
    )
    if result.returncode != 0:
        return None
    value = result.stdout.rstrip("\n")
    return value or None


def _macos_set(name: str, value: str) -> None:
    result = _run_tool(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            SERVICE_NAME,
            "-a",
            name,
            "-w",
            value,
        ]
    )
    if result.returncode != 0:
        raise SecretStoreError(f"failed to store secret {name} in macOS Keychain")


def _linux_get(name: str) -> str | None:
    result = _run_tool(
        ["secret-tool", "lookup", "service", SERVICE_NAME, "account", name]
    )
    if result.returncode != 0:
        return None
    value = result.stdout.rstrip("\n")
    return value or None


def _linux_set(name: str, value: str) -> None:
    result = _run_tool(
        [
            "secret-tool",
            "store",
            "--label",
            f"{SERVICE_NAME} {name}",
            "service",
            SERVICE_NAME,
            "account",
            name,
        ],
        input_text=value,
    )
    if result.returncode != 0:
        raise SecretStoreError(f"failed to store secret {name} in Secret Service")


def _windows_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return hasattr(ctypes, "windll") and hasattr(ctypes.windll, "advapi32")
    except (AttributeError, OSError):
        return False


def _windows_structs():
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    return ctypes, CREDENTIAL


def _windows_get(name: str) -> str | None:
    ctypes, credential_type = _windows_structs()
    advapi32 = ctypes.windll.advapi32
    cred_ptr = ctypes.c_void_p()
    target = f"{SERVICE_NAME}/{name}"
    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(cred_ptr)):
        return None
    try:
        cred = ctypes.cast(cred_ptr, ctypes.POINTER(credential_type)).contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return blob.decode("utf-16-le")
    except Exception:
        raise SecretStoreError(f"failed to read secret {name}") from None
    finally:
        advapi32.CredFree(cred_ptr)


def _windows_set(name: str, value: str) -> None:
    ctypes, credential_type = _windows_structs()
    advapi32 = ctypes.windll.advapi32
    blob = value.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob))
    cred = credential_type()
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = f"{SERVICE_NAME}/{name}"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.c_void_p)
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = name
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise SecretStoreError(f"failed to store secret {name} in Credential Manager")


def _file_get(name: str) -> str | None:
    path = FALLBACK_PATH
    if not path.is_file():
        return None
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            raise SecretStoreError(f"failed to secure secret file for {name}") from None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SecretStoreError(f"failed to read secret {name}") from None
    if not isinstance(payload, dict):
        return None
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        return None
    return value


def _file_set(name: str, value: str) -> None:
    path = FALLBACK_PATH
    payload: dict[str, object] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict):
            payload = existing
    payload[name] = value
    _atomic_write_0600(path, payload)


def _atomic_write_0600(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".api_keys.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except (AttributeError, OSError):
            pass
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
