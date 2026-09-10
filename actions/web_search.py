from __future__ import annotations

#web_search.py
import json
import logging

from i18n import t

import sys
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
def _get_api_key() -> str:
    from config.secrets import get_secret

    key = get_secret("gemini_api_key")
    if key is None:
        raise RuntimeError(t("error.gemini_key_missing"))
    return key


def _gemini_search(query: str) -> str:
    from providers.gemini.live import genai

    client   = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError(t("error.gemini_empty_response"))
    return text


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()

def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        logger.warning("Gemini compare failed: %s — falling back to DDG", e)

    # DDG fallback: fetch results per item and merge
    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
    return "\n".join(lines)

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Введите запрос для поиска."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] mode={mode}")

    logger.info("query_length=%s mode=%s", len(query), mode)
# replace: result = _gemini_search(query) block with:
    try:
        from providers.text_ops import client
        result = client.chat(
            query,
            system="You are a web search assistant. Answer factually and concisely."
        )
        logger.info("text_ops search ok")
        return result
    except Exception as e:
        logger.warning("text_ops search failed (%s) — trying DDG...", e)
        results = _ddg_search(query)
        result  = _format_ddg(query, results)
        logger.info("DDG: %s result(s)", len(results))
        return result
    
    except Exception as e:
        logger.error("All backends failed: %s", e)
        return f"Search failed, sir: {e}"
