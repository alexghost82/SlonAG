"""Browser control — delegates to the production BrowserService.

Backward-compatible: same signature as the legacy implementation.
"""
from __future__ import annotations

from collections.abc import Mapping

from i18n import t

from acta.tools.contracts import ToolResult
from runtime.browser.service import get_browser_service


def browser_control(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None
) -> ToolResult:
    """
    Production browser automation controller.

    actions:
        navigate   – go_to alias, go to URL
        search     – open search engine
        click      – click element
        type       – type text into element
        scroll     – scroll page
        fill_form  – fill form fields
        smart_click– find+click by description
        smart_type – find+type by description
        dom        – get page text or evaluate JS
        screenshot – capture page screenshot
        keys       – press a keyboard key
        tabs       – create/close/switch/list tabs
        cookies    – get/set/clear cookies
        status     – runtime status
        close      – close current page/context
        downloads  – enable/list downloads

    parameters keys:
        action      : str – required
        url         : str – URL for navigate/search
        query       : str – search query
        engine      : str – google|bing|duckduckgo (default: google)
        selector    : str – CSS selector
        text        : str – text to click or type
        description : str – element description for smart_*
        direction   : str – up|down for scroll (default: down)
        amount      : int – scroll amount (default: 500)
        key         : str – key name for keys action (e.g. Enter, Escape, Tab)
        fields      : {selector: value} dict for fill_form
        full_page   : bool – full page screenshot (default: False)
        expression  : str – JS expression for dom action
        mode        : str – create|close|switch|list for tabs action
        index       : int – tab index for close/switch
        tab_action  : str – what to do: create|close|switch|list
        cookie_name : str – name for set_cookie
        cookie_value: str – value for set_cookie
        download_dir: str – downloads directory path
        enable_download: bool – enable downloads
    """
    action = (parameters or {}).get("action", "").lower().strip()
    try:
        svc = get_browser_service()

        if action in ("go_to", "navigate"):
            return _handle_navigate(svc, parameters)
        elif action == "search":
            return _handle_search(svc, parameters)
        elif action in ("click", "smart_click"):
            return _handle_click(svc, parameters)
        elif action in ("type", "smart_type"):
            return _handle_type(svc, parameters)
        elif action == "scroll":
            return _handle_scroll(svc, parameters)
        elif action == "fill_form":
            return _handle_fill_form(svc, parameters)
        elif action == "keys" or action == "press_key":
            return _handle_key(svc, parameters)
        elif action == "dom":
            return _handle_dom(svc, parameters)
        elif action == "screenshot":
            return _handle_screenshot(svc, parameters)
        elif action == "tabs" or action == "tab":
            return _handle_tabs(svc, parameters)
        elif action in ("cookies", "get_cookies"):
            return _handle_cookies_get(svc)
        elif action == "set_cookie":
            return _handle_set_cookie(svc, parameters)
        elif action == "clear_cookies":
            return _handle_cookies_clear(svc)
        elif action == "downloads":
            return _handle_downloads(svc, parameters)
        elif action == "enable_downloads":
            return _handle_enable_downloads(svc, parameters)
        elif action == "status":
            return _handle_status(svc)
        elif action == "page_info":
            return _handle_page_info(svc)
        elif action in ("close", "close_page"):
            return _handle_close(svc)
        elif action == "close_all":
            return _handle_close_all(svc)
        else:
            return ToolResult(
                ok=False, code="unknown_action",
                message=f"Unknown action: {action}",
            )
    except Exception as exc:
        return ToolResult(
            ok=False, code="browser_error",
            message=f"Browser error: {exc}",
        )


def _handle_navigate(svc, params: Mapping) -> ToolResult:
    url = params.get("url", "")
    timeout = params.get("timeout_ms")
    try:
        result = svc.navigate(url, timeout_ms=timeout)
        return ToolResult(
            ok=True, code="navigate_ok", message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="navigate_error",
            message=str(exc)
        )


def _handle_search(svc, params: Mapping) -> ToolResult:
    query = params.get("query", "")
    engine = params.get("engine", "google")
    if not query:
        return ToolResult(
            ok=False, code="missing_field",
            message="query is required for search"
        )
    engines = {
        "google": "https://www.google.com/search?q={q}",
        "bing":   "https://www.bing.com/search?q={q}",
        "duckduckgo": "https://duckduckgo.com/?q={q}",
    }
    tmpl = engines.get(engine.lower(), engines["google"])
    url = tmpl.format(q=query.replace(" ", "+"))
    try:
        result = svc.navigate(url)
        return ToolResult(
            ok=True, code="search_ok", message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="search_error",
            message=str(exc)
        )


def _handle_click(svc, params: Mapping) -> ToolResult:
    action = params.get("action", "").lower().strip()
    timeout = params.get("timeout_ms")
    if action == "smart_click":
        description = params.get("description", "")
        if not description:
            return ToolResult(
                ok=False, code="missing_field",
                message="description required for smart_click"
            )
        result = svc.smart_find(description, kind="button")
        return ToolResult(
            ok=True, code="smart_click", message=result
        )
    selector = params.get("selector")
    text = params.get("text")
    role = params.get("role")
    name = params.get("name")
    try:
        result = svc.click(
            selector=selector, text=text,
            role=role, name=name,
            timeout_ms=timeout,
        )
        ok = not result.startswith(("Click timeout:", "Click error:"))
        return ToolResult(
            ok=ok, code="click_ok", message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="click_error",
            message=str(exc)
        )


def _handle_type(svc, params: Mapping) -> ToolResult:
    action = params.get("action", "").lower().strip()
    if action == "smart_type":
        description = params.get("description", "")
        text = params.get("text", "")
        if not description:
            return ToolResult(
                ok=False, code="missing_field",
                message="description required for smart_type"
            )
        result = svc.smart_find(description, kind="textbox")
        if result.startswith("Not found"):
            return ToolResult(
                ok=False, code="element_not_found",
                message=result
            )
        # Now type the text
        try:
            result2 = svc.type_text(text=text)
            return ToolResult(
                ok=True, code="smart_type_ok",
                message=f"{result}\n{result2}"
            )
        except Exception as exc:
            return ToolResult(
                ok=False, code="smart_type_error",
                message=str(exc)
            )
    selector = params.get("selector")
    text = params.get("text", "")
    clear_first = params.get("clear_first", True)
    timeout = params.get("timeout_ms")
    try:
        result = svc.type_text(
            selector=selector, text=text,
            clear_first=bool(clear_first),
            timeout_ms=timeout,
        )
        ok = not result.startswith("Type error:")
        return ToolResult(
            ok=ok, code="type_ok", message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="type_error",
            message=str(exc)
        )


def _handle_scroll(svc, params: Mapping) -> ToolResult:
    direction = params.get("direction", "down")
    amount = params.get("amount", 500)
    try:
        result = svc.scroll(direction=direction, amount=amount)
        return ToolResult(
            ok=True, code="scroll_ok", message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="scroll_error",
            message=str(exc)
        )


def _handle_fill_form(svc, params: Mapping) -> ToolResult:
    fields = params.get("fields", {})
    if not isinstance(fields, dict):
        return ToolResult(
            ok=False, code="invalid_fields",
            message="fields must be {selector: value} dict"
        )
    try:
        result = svc.fill_form(fields)
        return ToolResult(
            ok=True, code="form_filed", message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="form_error",
            message=str(exc)
        )


def _handle_key(svc, params: Mapping) -> ToolResult:
    key = params.get("key", "Enter")
    try:
        result = svc.press_key(key)
        return ToolResult(
            ok=True, code="key_ok", message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="key_error",
            message=str(exc)
        )


def _handle_dom(svc, params: Mapping) -> ToolResult:
    selector = params.get("selector", "body")
    mode = params.get("mode", "text")
    if mode == "js":
        expression = params.get("expression", "")
        try:
            result = svc.dom_evaluate(expression)
            return ToolResult(
                ok=True, code="js_ok",
                message=str(result),
                data=result,
            )
        except Exception as exc:
            return ToolResult(
                ok=False, code="js_error",
                message=str(exc)
            )
    else:
        max_chars = params.get("max_chars", 10000)
        try:
            result = svc.dom_get_text(
                selector=selector,
                max_chars=int(max_chars),
            )
            return ToolResult(
                ok=True, code="dom_ok",
                message=result,
                data={"text": result},
            )
        except Exception as exc:
            return ToolResult(
                ok=False, code="dom_error",
                message=str(exc)
            )


def _handle_screenshot(svc, params: Mapping) -> ToolResult:
    full_page = params.get("full_page", False)
    try:
        png_bytes = svc.screenshot(full_page=bool(full_page))
        return ToolResult(
            ok=True, code="screenshot_ok",
            message="Screenshot captured",
            artifacts=(),
            data={
                "type": "png_bytes",
                "size": len(png_bytes),
            },
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="screenshot_error",
            message=str(exc)
        )


def _handle_tabs(svc, params: Mapping) -> ToolResult:
    mode = params.get("mode", params.get("tab_action", "list"))
    index = params.get("index", -1)

    if mode == "create":
        url = params.get("url")
        try:
            idx = svc.tab_create(url)
            return ToolResult(
                ok=True, code="tab_created",
                message=f"Tab created, index={idx}",
                data={"index": idx},
            )
        except Exception as exc:
            return ToolResult(
                ok=False, code="tab_create_error",
                message=str(exc)
            )
    elif mode == "close":
        try:
            result = svc.tab_close(index)
            ok = "error" not in result.lower()
            return ToolResult(
                ok=ok, code="tab_closed",
                message=result
            )
        except Exception as exc:
            return ToolResult(
                ok=False, code="tab_close_error",
                message=str(exc)
            )
    elif mode == "switch":
        try:
            result = svc.tab_switch(index)
            ok = "error" not in result.lower()
            return ToolResult(
                ok=ok, code="tab_switched",
                message=result
            )
        except Exception as exc:
            return ToolResult(
                ok=False, code="tab_switch_error",
                message=str(exc)
            )
    else:  # list / default
        try:
            tabs = svc.tabs_list()
            return ToolResult(
                ok=True, code="tabs_listed",
                message=f"{len(tabs)} tab(s)",
                data={"tabs": tabs},
            )
        except Exception as exc:
            return ToolResult(
                ok=False, code="tabs_error",
                message=str(exc)
            )


def _handle_cookies_get(svc) -> ToolResult:
    try:
        cookies = svc.get_cookies()
        return ToolResult(
            ok=True, code="cookies_ok",
            message=f"{len(cookies)} cookie(s)",
            data={"cookies": cookies},
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="cookies_error",
            message=str(exc)
        )


def _handle_set_cookie(svc, params: Mapping) -> ToolResult:
    name = params.get("cookie_name", "")
    value = params.get("cookie_value", "")
    if not name:
        return ToolResult(
            ok=False, code="missing_field",
            message="cookie_name is required"
        )
    try:
        result = svc.set_cookie(
            name=name, value=value,
            domain=params.get("cookie_domain"),
            path=params.get("cookie_path", "/"),
        )
        return ToolResult(
            ok=True, code="cookie_set",
            message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="cookie_error",
            message=str(exc)
        )


def _handle_cookies_clear(svc) -> ToolResult:
    try:
        result = svc.clear_cookies()
        return ToolResult(
            ok=True, code="cookies_cleared",
            message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="cookies_error",
            message=str(exc)
        )


def _handle_downloads(svc) -> ToolResult:
    files = svc.list_downloads()
    return ToolResult(
        ok=True, code="downloads_list",
        message=f"{len(files)} file(s)",
        data={"files": files},
    )


def _handle_enable_downloads(svc, params: Mapping) -> ToolResult:
    download_dir = params.get("download_dir")
    try:
        result = svc.enable_downloads(download_dir)
        return ToolResult(
            ok=True, code="downloads_enabled",
            message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="downloads_error",
            message=str(exc)
        )


def _handle_status(svc) -> ToolResult:
    status = svc.status()
    return ToolResult(
        ok=True, code="status_ok",
        message=status.message or status.availability.value,
        data={
            "availability": status.availability.value,
            "engine": status.engine,
            "version": status.version,
            "tab_count": status.tab_count,
            "active_tab_url": status.active_tab_url,
        },
    )


def _handle_page_info(svc) -> ToolResult:
    info = svc.get_page_info()
    return ToolResult(
        ok=True, code="page_info_ok",
        message=f"Page: {info.get('url')}",
        data=info,
    )


def _handle_close(svc) -> ToolResult:
    try:
        result = svc.close()
        return ToolResult(
            ok=True, code="page_closed",
            message=result
        )
    except Exception as exc:
        return ToolResult(
            ok=False, code="close_error",
            message=str(exc)
        )


def _handle_close_all(svc) -> ToolResult:
    svc.stop()
    return ToolResult(
        ok=True, code="all_closed",
        message="Browser completely closed"
    )
