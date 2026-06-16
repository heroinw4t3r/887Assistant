"""Web search helpers for the AI chat module."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.modules.ai.providers import AIError

logger = logging.getLogger("ai.web_search")


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


async def _search_duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    def _run() -> list[dict]:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        raw = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001 - convert to user-facing AIError
        logger.warning("DuckDuckGo search failed: %s", exc)
        raise AIError(
            "Не удалось выполнить поиск в интернете. Попробуйте переформулировать запрос "
            "или повторите позже."
        ) from exc
    return _normalize_results(raw)


async def _search_tavily(query: str, api_key: str, max_results: int) -> list[SearchResult]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Tavily search failed: %s", exc)
        raise AIError(
            "Сервис веб-поиска временно недоступен. Попробуйте позже."
        ) from exc

    return _normalize_results(list(data.get("results") or []))


async def search_web(query: str, settings) -> list[SearchResult]:
    """Run a web search using the configured provider."""
    clean_query = query.strip()
    if not clean_query:
        return []

    max_results = max(1, int(getattr(settings, "web_search_max_results", 5) or 5))
    provider = (getattr(settings, "web_search_provider", "") or "duckduckgo").strip().lower()
    tavily_key = getattr(settings, "tavily_api_key", "") or ""

    if provider == "tavily" and tavily_key:
        results = await _search_tavily(clean_query, tavily_key, max_results)
    else:
        results = await _search_duckduckgo(clean_query, max_results)

    return results[:max_results]
