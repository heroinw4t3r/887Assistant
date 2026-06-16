"""Web search helpers for the AI chat module."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("ai.web_search")

# Hard ceiling for the DuckDuckGo thread call so it can never hang the bot.
_DDG_MAX_TIMEOUT = 12

# Whether we already warned about a missing Tavily API key (warn once).
_warned_missing_tavily_key = False


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


def format_results_for_prompt(query: str, results: list[SearchResult]) -> str:
    lines = [f"Результаты веб-поиска по запросу «{query}»:", ""]
    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item.title}")
        lines.append(f"   URL: {item.url}")
        if item.snippet:
            lines.append(f"   {item.snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def _normalize_results(raw_items: list[dict]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in raw_items:
        title = str(item.get("title") or item.get("name") or "Без названия").strip()
        url = str(item.get("href") or item.get("url") or item.get("link") or "").strip()
        snippet = str(
            item.get("body") or item.get("snippet") or item.get("content") or ""
        ).strip()
        if title or url or snippet:
            results.append(SearchResult(title=title or url or "Источник", url=url, snippet=snippet))
    return results


async def _search_duckduckgo(
    query: str, max_results: int, timeout: float
) -> list[SearchResult]:
    """DuckDuckGo search with a hard timeout — never hangs, never raises.

    DDG is unreliable from datacenter IPs (it can hang 10–40s), so the thread
    call is bounded by ``asyncio.wait_for`` and any failure degrades to ``[]``.
    """

    def _run() -> list[dict]:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
    except TimeoutError:
        logger.warning("DuckDuckGo search timed out after %.0fs; returning no results", timeout)
        return []
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, never break the turn
        logger.warning("DuckDuckGo search failed: %s", exc)
        return []
    return _normalize_results(raw)


async def _search_tavily(query: str, api_key: str, max_results: int) -> list[SearchResult]:
    """Tavily search over HTTP with a short timeout — degrades to ``[]`` on error."""
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Tavily search failed: %s", exc)
        return []
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, never break the turn
        logger.warning("Tavily search error: %s", exc)
        return []

    return _normalize_results(list(data.get("results") or []))


async def search_web(query: str, settings) -> list[SearchResult]:
    """Run a web search using the configured provider.

    Designed to NEVER hang and NEVER hard-fail a chat turn. The worst case is an
    empty list, meaning "no web results available" — the caller answers without
    web context.
    """
    global _warned_missing_tavily_key

    clean_query = query.strip()
    if not clean_query:
        return []

    max_results = max(1, int(getattr(settings, "web_search_max_results", 5) or 5))
    provider = (getattr(settings, "web_search_provider", "") or "tavily").strip().lower()
    tavily_key = getattr(settings, "tavily_api_key", "") or ""

    if provider == "tavily":
        if not tavily_key:
            # Do NOT fall back to DuckDuckGo: it hangs on hosting IPs. Warn once.
            if not _warned_missing_tavily_key:
                logger.warning(
                    "WEB_SEARCH_PROVIDER=tavily but TAVILY_API_KEY is not set; "
                    "web search disabled (answering without web context)."
                )
                _warned_missing_tavily_key = True
            return []
        results = await _search_tavily(clean_query, tavily_key, max_results)
    elif provider == "duckduckgo":
        timeout = min(int(getattr(settings, "llm_request_timeout", 60) or 60), _DDG_MAX_TIMEOUT)
        results = await _search_duckduckgo(clean_query, max_results, float(timeout))
    else:
        logger.warning("Unknown web_search_provider %r; returning no results", provider)
        return []

    return results[:max_results]
