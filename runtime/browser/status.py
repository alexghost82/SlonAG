"""Browser runtime status and availability."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class BrowserErrorCode(str, Enum):
    CHROMIUM_MISSING = "chromium_missing"
    PLAYWRIGHT_MISSING = "playwright_missing"
    LAUNCH_FAILED = "launch_failed"
    BROWSER_CLOSED = "browser_closed"
    PAGE_NOT_FOUND = "page_not_found"
    TIMEOUT = "timeout"
    DOWNLOAD_FAILED = "download_failed"
    JS_DENIED = "js_denied"
    GENERIC = "generic"


class BrowserAvailability(str, Enum):
    """Deterministic availability states."""
    READY = "ready"
    BOOTSTRAPPED = "bootstrapped"       # Playwright ok, browser not yet launched
    LAUNCHED = "launched"                # Browser running, page ready
    LAUNCHING = "launching"              # In the process of launching
    ERROR = "error"                      # Cannot use (no Chromium, etc.)


@dataclass(frozen=True)
class BrowserStatus:
    """Immutable status snapshot of the browser runtime."""
    availability: BrowserAvailability
    error_code: BrowserErrorCode | None = None
    engine: str | None = None            # "chromium", "firefox", etc.
    version: str | None = None
    tab_count: int = 0
    active_tab_url: str | None = None
    message: str | None = None


def _check_chromium_installed() -> bool:
    """Check if Playwright's Chromium binary is installed on disk."""
    cache_dir = Path.home() / ".cache" / "ms-playwright"
    if not cache_dir.exists():
        return False
    for d in cache_dir.iterdir():
        if d.name.startswith("chromium-"):
            chrome_bin = d / "chrome-linux" / "chrome"
            if chrome_bin.exists():
                return True
            chrome_bin2 = d / "chrome-linux-arm64" / "chrome"
            if chrome_bin2.exists():
                return True
    return False


def _check_playwright_available() -> bool:
    """Check if Playwright Python module is importable."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _detect_chromium_version() -> str | None:
    """Try to read Chromium version from binary."""
    cache_dir = Path.home() / ".cache" / "ms-playwright"
    if not cache_dir.exists():
        return None
    for d in cache_dir.iterdir():
        if d.name.startswith("chromium-"):
            for bin_name in ["chrome-linux/chrome", "chrome-linux-arm64/chrome"]:
                chrome_bin = d / bin_name
                if chrome_bin.exists():
                    try:
                        result = subprocess.run(
                            [str(chrome_bin), "--version"],
                            capture_output=True, text=True, timeout=5
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            return result.stdout.strip()
                    except Exception:
                        pass
    return None


def detect_runtime_availability() -> BrowserAvailability:
    """Return a deterministic availability state."""
    if not _check_playwright_available():
        return BrowserAvailability.ERROR

    if not _check_chromium_installed():
        return BrowserAvailability.ERROR

    return BrowserAvailability.READY


def get_runtime_status() -> BrowserStatus:
    """Return a full status snapshot without launching the browser."""
    if not _check_playwright_available():
        return BrowserStatus(
            availability=BrowserAvailability.ERROR,
            error_code=BrowserErrorCode.PLAYWRIGHT_MISSING,
            message="Playwright не установлен. Установите через: pip install playwright && python -m playwright install chromium",
        )

    if not _check_chromium_installed():
        return BrowserStatus(
            availability=BrowserAvailability.ERROR,
            error_code=BrowserErrorCode.CHROMIUM_MISSING,
            message=(
                "Chromium не установлен. Для работы браузерной автоматизации "
                "необходимо установить Playwright Chromium:\n\n"
                "    pip install playwright\n"
                "    python -m playwright install chromium\n\n"
                "Эта команда загружает Chromium в ~/.cache/ms-playwright/. "
                "После установки browser runtime будет доступен."
            ),
        )

    version = _detect_chromium_version()
    return BrowserStatus(
        availability=BrowserAvailability.READY,
        engine="chromium",
        version=version,
        message=None,
    )
