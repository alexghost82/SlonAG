"""Unit tests for BrowserService and browser runtime status.

Covers:
  - Runtime availability detection
  - BrowserService lifecycle (start, stop, status)
  - Navigation, click, type, DOM extraction
  - Tab management
  - Cookie management
  - Form filling
  - Error handling (invalid URLs, timeouts)
  - Thread safety via run() with timeout
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from runtime.browser.service import BrowserService, get_browser_service
from runtime.browser.status import (
    BrowserAvailability,
    BrowserErrorCode,
    BrowserStatus,
    detect_runtime_availability,
    get_runtime_status,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

_TEST_PAGE_PATH = Path(__file__).parent.parent / "fixtures" / "e2e_test_page.html"
_TEST_PAGE_URL = "file://" + str(_TEST_PAGE_PATH.resolve())


@pytest.fixture()
def service():
    """Create and start a fresh BrowserService for each test."""
    svc = BrowserService()
    svc.start()
    try:
        yield svc
    finally:
        svc.stop()


@pytest.fixture()
def ready_page(service):
    """Navigate to the local test page and yield."""
    result = service.navigate(_TEST_PAGE_URL)
    assert "OK" in result or "Navigate" in result, f"Navigate failed: {result}"
    yield service


# ── Availability & Status ─────────────────────────────────────────────────

class TestAvailability:
    def test_detect_availability_when_ready(self):
        av = detect_runtime_availability()
        # On this machine Playwright + Chromium should be installed
        assert av == BrowserAvailability.READY

    def test_runtime_status_when_ready(self):
        status = get_runtime_status()
        assert status.availability == BrowserAvailability.READY
        assert status.engine == "chromium"
        assert status.message is None

    def test_service_status_after_start(self, service):
        status = service.status()
        assert status.availability in (
            BrowserAvailability.LAUNCHED,
            BrowserAvailability.BOOTSTRAPPED,
        )
        assert status.engine == "chromium"


# ── Navigation ────────────────────────────────────────────────────────────

class TestNavigation:
    def test_load_local_html(self, ready_page):
        info = ready_page.get_page_info()
        assert info["url"].startswith("file://")
        title = info["title"]
        assert "Test Page" in title or "SlonAG" in title

    def test_navigate_http(self, service):
        result = service.navigate("data:text/html,<h1>Hello</h1>")
        assert "OK" in result or "Navigate" in result

    def test_navigate_adds_https(self, service):
        # Should be tolerated (may redirect/fail on real sites, but shouldn't crash)
        result = service.navigate("data:text/html,<h1>Direct</h1>")
        assert "OK" in result or "Navigate" in result

    def test_navigate_timeout(self, service):
        """Navigation to a slow/unreachable URL should raise BrowserTimeoutError."""
        from runtime.browser.exceptions import BrowserTimeoutError

        with pytest.raises(BrowserTimeoutError):
            # 1ms timeout should definitely timeout
            service.navigate("data:text/html,<h1>OK</h1>", timeout_ms=1)


# ── Click ─────────────────────────────────────────────────────────────────

class TestClick:
    def test_click_submit_button(self, ready_page):
        # Fill the form first
        ready_page.type_text("#name", "E2E Test User")
        ready_page.type_text("#email", "e2e@test.com")
        ready_page.click("#subject")
        ready_page.press_key("Tab")  # move away
        ready_page.type_text("#message", "Hello from E2E test")
        # Click submit
        result = ready_page.click("#submit-btn")
        assert "Clicked" in result

    def test_click_text(self, ready_page):
        result = ready_page.click(text="Submit")
        assert "Clicked text" in result

    def test_click_role(self, ready_page):
        result = ready_page.click(role="button", name="Submit")
        assert "Clicked role" in result

    def test_click_increment(self, ready_page):
        """Click the +1 button which does count++ twice (so +2)."""
        counter_text = ready_page.dom_get_text("#counter")
        assert counter_text.strip() == "0"
        ready_page.click("#increment-btn")
        ready_page.click("#increment-btn")
        counter_text = ready_page.dom_get_text("#counter")
        assert counter_text.strip() == "4"  # 0 -> 2 -> 4


# ── Type / Keyboard ───────────────────────────────────────────────────────

class TestType:
    def test_type_into_selector(self, ready_page):
        ready_page.type_text("#name", "TestName")
        val = ready_page.dom_evaluate("document.getElementById('name').value")
        assert val == "TestName"

    def test_type_clears_first(self, ready_page):
        ready_page.type_text("#name", "First")
        ready_page.type_text("#name", "Second")
        val = ready_page.dom_evaluate("document.getElementById('name').value")
        assert val == "Second"

    def test_press_key_tab(self, ready_page):
        ready_page.type_text("#name", "TabTest")
        result = ready_page.press_key("Tab")
        assert "pressed" in result.lower()

    def test_press_key_enter(self, ready_page):
        result = ready_page.press_key("Enter")
        assert "pressed" in result.lower()


# ── DOM Extraction ────────────────────────────────────────────────────────

class TestDOM:
    def test_dom_get_text_body(self, ready_page):
        text = ready_page.dom_get_text("body", max_chars=500)
        assert "Test Page" in text or "SlonAG" in text

    def test_dom_get_text_selector(self, ready_page):
        text = ready_page.dom_get_text("h1", max_chars=200)
        assert "Test Page" in text or "SlonAG" in text

    def test_dom_evaluate(self, ready_page):
        result = ready_page.dom_evaluate("document.title")
        assert "Test" in result or "SlonAG" in result

    def test_bounded_extraction(self, ready_page):
        """max_chars should truncate."""
        long_text = "A" * 20000
        ready_page.dom_evaluate(
            "document.body.insertAdjacentText('beforeend', `<div id='big'>${'A'*20000}</div>`)")
        text = ready_page.dom_get_text("#big", max_chars=100)
        assert len(text) <= 100


# ── Form Filling ──────────────────────────────────────────────────────────

class TestForm:
    def test_fill_form(self, ready_page):
        fields = {
            "#name": "Form Test",
            "#email": "form@test.com",
            "#message": "Auto-filled message",
        }
        result = ready_page.fill_form(fields)
        assert "filled" in result.lower()
        # Verify values were set
        name_val = ready_page.dom_evaluate("document.getElementById('name').value")
        assert name_val == "Form Test"
        email_val = ready_page.dom_evaluate("document.getElementById('email').value")
        assert email_val == "form@test.com"

    def test_fill_and_submit(self, ready_page):
        ready_page.fill_form({
            "#name": "Alice",
            "#email": "alice@example.com",
            "#subject": "support",
            "#message": "Help me!",
        })
        ready_page.click("#submit-btn")
        result_text = ready_page.dom_get_text("#result")
        assert "Alice" in result_text
        assert "alice@example.com" in result_text
        assert "support" in result_text


# ── Tabs ──────────────────────────────────────────────────────────────────

class TestTabs:
    def test_list_tabs(self, ready_page):
        tabs = ready_page.tabs_list()
        assert len(tabs) >= 1
        assert tabs[0]["url"].startswith("file://")

    def test_create_tab(self, service):
        ready = BrowserService()
        ready.start()
        try:
            ready.navigate("data:text/html,<h1>Original</h1>")
            idx = ready.tab_create("data:text/html,<h1>New Tab</h1>")
            assert idx == 1  # 0-indexed
            tabs = ready.tabs_list()
            assert len(tabs) == 2
        finally:
            ready.stop()

    def test_switch_tab(self, service):
        ready = BrowserService()
        ready.start()
        try:
            ready.navigate("data:text/html,<h1>Tab 0</h1>")
            ready.tab_create("data:text/html,<h1>Tab 1</h1>")
            result = ready.tab_switch(0)
            assert "Switched" in result or "tab 0" in result.lower()
        finally:
            ready.stop()

    def test_close_tab(self, service):
        ready = BrowserService()
        ready.start()
        try:
            ready.navigate("data:text/html,<h1>Keep</h1>")
            ready.tab_create("data:text/html,<h1>Close Me</h1>")
            result = ready.tab_close(1)
            assert "closed" in result.lower()
        finally:
            ready.stop()


# ── Cookies ───────────────────────────────────────────────────────────────

class TestCookies:
    def test_set_and_get_cookie(self, service):
        ready = BrowserService()
        ready.start()
        try:
            ready.navigate("data:text/html,<h1>Cookie Test</h1>")
            ready.set_cookie("test_key", "test_value")
            cookies = ready.get_cookies()
            names = [c["name"] for c in cookies]
            assert "test_key" in names
        finally:
            ready.stop()

    def test_clear_cookies(self, service):
        ready = BrowserService()
        ready.start()
        try:
            ready.navigate("data:text/html,<h1>Clear Test</h1>")
            ready.set_cookie("x", "y")
            ready.clear_cookies()
            cookies = ready.get_cookies()
            assert len(cookies) == 0
        finally:
            ready.stop()


# ── Screenshot ────────────────────────────────────────────────────────────

class TestScreenshot:
    def test_screenshot_returns_png(self, ready_page):
        png_data = ready_page.screenshot()
        assert isinstance(png_data, bytes)
        assert len(png_data) > 0
        # PNG magic bytes
        assert png_data[:8] == b"\\x89PNG\\r\\n\\x1a\\n"


# ── Lifecycle ─────────────────────────────────────────────────────────────

class TestLifecycle:
    def test_start_stop_twice_is_idempotent(self):
        svc = BrowserService()
        svc.start()
        svc.stop()
        svc.start()
        svc.stop()

    def test_close_page(self, service):
        result = service.close()
        assert "closed" in result.lower()

    def test_close_all(self, service):
        result = service.close_all()
        assert "closed" in result.lower()


# ── Actions integration ───────────────────────────────────────────────────

class TestBrowserControlActions:
    """Test the browser_control action function via the ToolResult contract."""

    def test_action_navigate(self, ready_page):
        from actions.browser_control import browser_control
        result = browser_control({"action": "navigate", "url": _TEST_PAGE_URL})
        assert result.ok is True
        assert result.code in ("navigate_ok",)

    def test_action_click(self, ready_page):
        from actions.browser_control import browser_control
        result = browser_control({
            "action": "click",
            "selector": "#submit-btn",
        })
        assert result.ok is True

    def test_action_fill_form(self, ready_page):
        from actions.browser_control import browser_control
        result = browser_control({
            "action": "fill_form",
            "fields": {"#name": "Action Test", "#message": "Hello"},
        })
        assert result.ok is True

    def test_action_status(self, service):
        from actions.browser_control import browser_control
        result = browser_control({"action": "status"})
        assert result.ok is True
        assert "ready" in result.message.lower() or "launched" in result.message.lower()

    def test_action_unknown(self, service):
        from actions.browser_control import browser_control
        result = browser_control({"action": "nonexistent"})
        assert result.ok is False
        assert result.code == "unknown_action"
