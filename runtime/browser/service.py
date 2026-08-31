"""Core BrowserService — deterministic Playwright lifecycle manager.

Uses a background thread with its own event loop.
All public methods are synchronous (run via run_coroutine_threadsafe).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import (
        Browser as AsyncBrowser,
        BrowserContext as AsyncBrowserContext,
        Page as AsyncPage,
        Playwright as AsyncPlaywright,
    )

# Lazy import for runtime use — playwright is optional at import time
_playwright_mod = None


def _get_playwright():
    """Lazy import of playwright.async_api — fails only when actually needed."""
    global _playwright_mod, PlaywrightTimeout
    if _playwright_mod is None:
        from playwright import async_api as _m
        _playwright_mod = _m
        PlaywrightTimeout = _m.TimeoutError
    return _playwright_mod


# Stub so 'except PlaywrightTimeout' has a name at import time.
# Set to None; _get_playwright() replaces it with the real class.
PlaywrightTimeout: type[Exception] | None = None  # noqa: E999


from runtime.browser.exceptions import (
    BrowserError,
    BrowserLaunchError,
    BrowserPageError,
    BrowserTimeoutError,
)
from runtime.browser.status import BrowserAvailability, BrowserStatus, detect_runtime_availability, get_runtime_status

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 15000
_NAVIGATION_TIMEOUT_MS = 30000


@dataclass(frozen=True)
class TabInfo:
    """Snapshot of a single tab/page."""
    index: int
    url: str
    title: str
    is_active: bool


class BrowserService:
    """Manages a single Playwright Chromium browser instance with tab lifecycle."""

    def __init__(self, profile_path: str | None = None,
                 timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._playwright: AsyncPlaywright | None = None
        self._browser: AsyncBrowser | None = None
        self._context: AsyncBrowserContext | None = None
        self._page: AsyncPage | None = None
        self._available = BrowserAvailability.ERROR
        self._timeout_ms = timeout_ms
        self._profile_path = profile_path
        self._download_path: Path | None = None
        self._js_denied_domains: set[str] = set()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the browser background thread. Idempotent."""
        if self._thread and self._thread.is_alive():
            return
        self._available = detect_runtime_availability()
        if self._available == BrowserAvailability.ERROR:
            status = get_runtime_status()
            raise BrowserLaunchError(
                f"Browser runtime is not available: {status.message or status.error_code}"
            )
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="SlonBrowserThread"
        )
        self._thread.start()
        if not self._ready.wait(timeout=15):
            raise BrowserLaunchError(
                "Browser thread did not become ready within 15s"
            )

    def stop(self) -> None:
        """Close browser and stop the background thread."""
        self.run(self._close_all())
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def availability(self) -> BrowserAvailability:
        return self._available

    @property
    def is_launched(self) -> bool:
        return (
            self._browser is not None
            and self._browser.is_connected()
            and self._page is not None
            and not self._page.is_closed()
        )

    # ── Public API (thread-safe) ─────────────────────────────────────────

    def status(self) -> BrowserStatus:
        return self.run(self._collect_status())

    def navigate(self, url: str, timeout_ms: int | None = None) -> str:
        return self.run(
            lambda: self._do_navigate(url, timeout_ms or _NAVIGATION_TIMEOUT_MS)
        )

    def get_page_info(self) -> dict[str, object]:
        return self.run(self._collect_page_info)

    def tabs_list(self) -> list[dict[str, object]]:
        return self.run(self._collect_tabs)

    def tab_create(self, url: str | None = None) -> int:
        return self.run(lambda: self._do_tab_create(url))

    def tab_close(self, index: int = -1) -> str:
        return self.run(lambda: self._do_tab_close(index))

    def tab_switch(self, index: int) -> str:
        return self.run(lambda: self._do_tab_switch(index))

    def screenshot(self, full_page: bool = False) -> bytes:
        return self.run(lambda: self._do_screenshot(full_page))

    def dom_get_text(self, selector: str = "body",
                     max_chars: int = 10000) -> str:
        return self.run(
            lambda: self._do_dom_get_text(selector, max_chars)
        )

    def dom_evaluate(self, expression: str) -> Any:
        return self.run(lambda: self._do_dom_evaluate(expression))

    def click(self, selector: str | None = None, text: str | None = None,
              role: str | None = None, name: str | None = None,
              timeout_ms: int | None = None) -> str:
        return self.run(
            lambda: self._do_click(
                selector, text, role, name,
                timeout_ms or _DEFAULT_TIMEOUT_MS
            )
        )

    def type_text(self, selector: str | None = None, text: str = "",
                  clear_first: bool = True,
                  timeout_ms: int | None = None) -> str:
        return self.run(
            lambda: self._do_type_text(
                selector, text, clear_first,
                timeout_ms or _DEFAULT_TIMEOUT_MS
            )
        )

    def press_key(self, key: str) -> str:
        return self.run(lambda: self._do_press_key(key))

    def scroll(self, direction: str = "down",
               amount: int = 500) -> str:
        return self.run(lambda: self._do_scroll(direction, amount))

    def fill_form(self, fields: Mapping[str, str]) -> str:
        return self.run(lambda: self._do_fill_form(dict(fields)))

    def smart_find(self, description: str,
                   kind: str = "textbox") -> str:
        return self.run(
            lambda: self._do_smart_find(description, kind)
        )

    def get_cookies(self) -> list[dict[str, object]]:
        return self.run(self._do_get_cookies)

    def set_cookie(self, name: str, value: str,
                   domain: str | None = None, path: str = "/",
                   **kwargs: Any) -> str:
        return self.run(
            lambda: self._do_set_cookie(name, value, domain, path, **kwargs)
        )

    def clear_cookies(self) -> str:
        return self.run(self._do_clear_cookies)

    def enable_downloads(self, download_dir: str | Path | None = None) -> str:
        dir_path = (download_dir
                    if download_dir
                    else str(Path.home() / ".slon" / "browser_downloads"))
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        self._download_path = Path(dir_path)
        return self.run(
            lambda: self._do_enable_downloads(str(dir_path))
        )

    def list_downloads(self) -> list[str]:
        if self._download_path is None:
            return []
        return [
            str(f)
            for f in sorted(self._download_path.iterdir())
            if f.is_file()
        ]

    def set_js_policy(self, *domains: str) -> str:
        self._js_denied_domains = set(domains)
        return (
            f"JS policy set: {len(self._js_denied_domains)} "
            f"domains blocked"
        )

    def close(self) -> str:
        return self.run(self._do_close_current_page)

    # ── Internal async methods ───────────────────────────────────────────

    async def _launch(self) -> None:
        """Initialize Playwright and Chromium."""
        pa = _get_playwright()
        self._playwright = await pa.async_playwright().start()
        engine = self._playwright.chromium

        chromium_args = [
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--disable-dev-shm-prepare",
        ]

        launch_kwargs: dict[str, Any] = {
            "headless": True,
            "args": chromium_args,
            "timeout": 10000,
        }

        if self._profile_path:
            launch_kwargs["user_data_dir"] = self._profile_path

        try:
            self._browser = await engine.launch(**launch_kwargs)
            self._available = BrowserAvailability.LAUNCHED
        except Exception as exc:
            logger.warning(
                "Chromium launch failed (%s), "
                "using bundled Playwright chromium", exc
            )
            self._browser = await engine.launch(
                headless=True,
                args=["--start-maximized",
                      "--no-first-run",
                      "--no-default-browser-check"],
            )
            self._available = BrowserAvailability.LAUNCHED

        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
        )
        self._page = await self._context.new_page()
        self._available = BrowserAvailability.LAUNCHED

    async def _ensure_page(self) -> AsyncPage:
        if (self._page is None
                or self._page.is_closed()
                or self._browser is None
                or self._browser.is_closed()):
            await self._launch()
        return self._page

    async def _collect_status(self) -> BrowserStatus:
        if (self._browser is None
                or self._browser.is_closed()):
            avail = BrowserAvailability.BOOTSTRAPPED
            if self._playwright is None:
                avail = BrowserAvailability.ERROR
        elif (self._page is None
              or self._page.is_closed()):
            avail = BrowserAvailability.BOOTSTRAPPED
        else:
            avail = BrowserAvailability.LAUNCHED

        tabs = []
        url = None
        if self._context:
            try:
                tabs = [
                    {"url": p.url, "title": p.title,
                     "active": p == self._page}
                    for p in self._context.pages
                ]
                if self._page and not self._page.is_closed():
                    url = self._page.url
            except Exception:
                pass

        return BrowserStatus(
            availability=avail,
            engine="chromium",
            tab_count=len(tabs),
            active_tab_url=url,
        )

    async def _collect_page_info(self) -> dict[str, object]:
        page = await self._ensure_page()
        tabs_info = []
        try:
            for p in self._context.pages:  # type: ignore[union-attr]
                tabs_info.append({
                    "url": p.url,
                    "title": p.title,
                    "index": len(tabs_info),
                    "active": p == page,
                })
        except Exception:
            pass
        return {
            "url": page.url,
            "title": page.title,
            "tabs": tabs_info,
        }

    async def _collect_tabs(self) -> list[dict[str, object]]:
        await self._ensure_page()
        tabs_info = []
        try:
            for i, p in enumerate(self._context.pages):  # type: ignore[union-attr]
                tabs_info.append({
                    "index": i,
                    "url": p.url,
                    "title": p.title,
                    "active": p == self._page,
                })
        except Exception:
            pass
        return tabs_info

    # ── Navigation ───────────────────────────────────────────────────────

    async def _do_navigate(self, url: str,
                           timeout_ms: int) -> str:
        page = await self._ensure_page()
        if not url.startswith(("http://", "https://",
                               "data:", "about:")):
            url = "https://" + url
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            return f"Navigate OK: {page.url}"
        except PlaywrightTimeout:
            return f"Navigate timeout: {url}"
        except Exception as exc:
            return f"Navigate error: {exc}"

    # ── Tab management ────────────────────────────────────────────────────

    async def _do_tab_create(self, url: str | None
                             = None) -> int:
        await self._ensure_page()
        page = await self._context.new_page()  # type: ignore[union-attr]
        if url:
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=_NAVIGATION_TIMEOUT_MS,
                )
            except Exception:
                pass
        return len(self._context.pages) - 1  # type: ignore[union-attr]

    async def _do_tab_close(self, index: int = -1) -> str:
        await self._ensure_page()
        pages = self._context.pages  # type: ignore[union-attr]
        if not pages:
            return "No tabs to close"
        if index == -1:
            index = len(pages) - 1
        if index < 0 or index >= len(pages):
            return f"Invalid tab index: {index}"
        try:
            page = pages[index]
            await page.close()
        except Exception as exc:
            return f"Tab close error: {exc}"
        remaining = len(self._context.pages)  # type: ignore[union-attr]
        if (remaining > 0 and self._page
                and self._page.is_closed()):  # type: ignore[union-attr]
            self._page = self._context.pages[0]  # type: ignore[union-attr]
        return f"Tab closed, {remaining} remaining"

    async def _do_tab_switch(self, index: int) -> str:
        await self._ensure_page()
        pages = self._context.pages  # type: ignore[union-attr]
        if index < 0 or index >= len(pages):
            return f"Invalid tab index: {index}"
        page = pages[index]
        await page.bring_to_front()
        self._page = page
        return f"Switched to tab {index}: {page.url}"

    # ── Close / cleanup ──────────────────────────────────────────────────

    async def _do_close_current_page(self) -> str:
        if self._page and not self._page.is_closed():
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        return "Page and context closed"

    async def _close_all(self) -> None:
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if (self._browser
                    and self._browser.is_connected()):
                await self._browser.close()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None

    # ── Screenshot ───────────────────────────────────────────────────────

    async def _do_screenshot(self,
                             full_page: bool = False
                             ) -> bytes:
        page = await self._ensure_page()
        return await page.screenshot(
            full_page=full_page, type="png"
        )

    # ── DOM extraction ───────────────────────────────────────────────────

    async def _do_dom_get_text(self, selector: str = "body",
                               max_chars: int = 10000) -> str:
        page = await self._ensure_page()
        try:
            if selector == "body":
                text = await page.inner_text("body")
            else:
                text = (
                    await page.locator(selector)
                    .first.inner_text()
                )
            return (text[:max_chars]
                    if len(text) > max_chars else text)
        except Exception as exc:
            return f"DOM text error: {exc}"

    async def _do_dom_evaluate(self, expression: str
                               ) -> Any:
        page = await self._ensure_page()
        try:
            result = await page.evaluate(expression)
            return result
        except Exception as exc:
            raise BrowserPageError(
                f"JS evaluation failed: {exc}"
            )

    # ── Click ─────────────────────────────────────────────────────────────

    async def _do_click(self, selector: str | None,
                        text: str | None, role: str | None,
                        name: str | None, timeout_ms: int
                        ) -> str:
        page = await self._ensure_page()
        try:
            if text:
                await (page.get_by_text(
                    text, exact=False
                ).first.click(timeout=timeout_ms))
                return f"Clicked text: '{text}'"
            elif role and name:
                await (page.get_by_role(
                    role, name=name
                ).first.click(timeout=timeout_ms))
                return f"Clicked role=/{role}/{name}"
            elif selector:
                await (page.locator(selector)
                       .first.click(timeout=timeout_ms))
                return f"Clicked selector: {selector}"
            return "Click: no target specified"
        except PlaywrightTimeout:
            return f"Click timeout: {selector or text or role}"
        except Exception as exc:
            return f"Click error: {exc}"

    # ── Type ──────────────────────────────────────────────────────────────

    async def _do_type_text(self, selector: str | None,
                            text: str, clear_first: bool,
                            timeout_ms: int) -> str:
        page = await self._ensure_page()
        try:
            if selector:
                el = page.locator(selector).first
            else:
                el = page.locator(":focus")
            if clear_first:
                await el.clear()
            await el.type(text, delay=30)
            target = ("selector " + selector
                      if selector else "focused")
            return f"Typed into {target}: {text[:50]}"
        except Exception as exc:
            return f"Type error: {exc}"

    # ── Key press ─────────────────────────────────────────────────────────

    async def _do_press_key(self, key: str) -> str:
        page = await self._ensure_page()
        try:
            await page.keyboard.press(key)
            return f"Key pressed: {key}"
        except Exception as exc:
            return f"Key error: {exc}"

    # ── Scroll ────────────────────────────────────────────────────────────

    async def _do_scroll(self, direction: str = "down",
                         amount: int = 500) -> str:
        page = await self._ensure_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction} by {amount}px"
        except Exception as exc:
            return f"Scroll error: {exc}"

    # ── Form fill ──────────────────────────────────────────────────────────

    async def _do_fill_form(
            self, fields: dict[str, str]
    ) -> str:
        page = await self._ensure_page()
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=30)
                results.append(f"✓ {selector}")
            except Exception as exc:
                results.append(f"✗ {selector}: {exc}")
        return "Form filled: " + ", ".join(results)

    # ── Smart element finder ──────────────────────────────────────────────

    async def _do_smart_find(self, description: str,
                             kind: str = "textbox"
                             ) -> str:
        page = await self._ensure_page()
        try:
            for method, locator in [
                ("placeholder",
                 page.get_by_placeholder(
                     description, exact=False
                 )),
                ("label",
                 page.get_by_label(
                     description, exact=False
                 )),
                ("text",
                 page.get_by_text(
                     description, exact=False
                 )),
            ]:
                try:
                    el = locator.first
                    if kind == "textbox":
                        await el.focus()
                    else:
                        await el.click()
                    return (
                        f"Found {kind} via {method}: "
                        f"'{description}'"
                    )
                except Exception:
                    continue

            if kind == "textbox":
                try:
                    el = page.get_by_role(
                        "textbox"
                    ).first
                    await el.focus()
                    return "Focused first textbox"
                except Exception:
                    pass

            return f"Not found: '{description}' ({kind})"
        except Exception as exc:
            return f"Smart find error: {exc}"

    # ── Cookies ────────────────────────────────────────────────────────────

    async def _do_get_cookies(
            self
    ) -> list[dict[str, object]]:
        if self._context is None:  # type: ignore[union-attr]
            return []
        return await self._context.cookies()  # type: ignore[union-attr]

    async def _do_set_cookie(self, name: str, value: str,
                             domain: str | None = None,
                             path: str = "/",
                             **kwargs: Any) -> str:
        if self._context is None:  # type: ignore[union-attr]
            return "No context"
        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "path": path,
        }
        if domain:
            cookie["domain"] = domain
        cookie.update(kwargs)
        await self._context.add_cookies([cookie])  # type: ignore[union-attr]
        return f"Cookie set: {name}"

    async def _do_clear_cookies(self) -> str:
        if self._context is None:  # type: ignore[union-attr]
            return "No context"
        await self._context.clear_cookies()  # type: ignore[union-attr]
        return "Cookies cleared"

    async def _do_enable_downloads(
            self, download_dir: str
    ) -> str:
        if self._context is None:  # type: ignore[union-attr]
            return "No context"
        await self._context.set_extra_http_headers(
            {"Accept-Language": "en-US,en;q=0.9"}
        )
        return f"Downloads enabled to: {download_dir}"

    # ── Background loop ───────────────────────────────────────────────────

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._launch())
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()
            self._loop = None

    # ── Coroutine runner ──────────────────────────────────────────────────

    def run(self, coro, timeout: int = 30) -> Any:
        """Run a coroutine on the browser thread."""
        if not self._loop:
            raise RuntimeError(
                "BrowserService not started"
            )
        future = asyncio.run_coroutine_threadsafe(
            coro, self._loop
        )
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise BrowserTimeoutError(
                "Browser action timed out"
            )
        except Exception as exc:
            # Re-raise known exception types
            pw = _get_playwright()
            if isinstance(exc, pw.TimeoutError):
                raise BrowserTimeoutError(
                    "Playwright timeout"
                ) from exc
            raise


# ── Singleton accessor ───────────────────────────────────────────────────

_service: BrowserService | None = None


def get_browser_service(
        profile_path: str | None = None,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> BrowserService:
    global _service
    if _service is None:
        _service = BrowserService(
            profile_path=profile_path,
            timeout_ms=timeout_ms,
        )
    return _service
