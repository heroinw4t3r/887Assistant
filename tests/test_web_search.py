"""Tests for AI web search helpers.

No real network call is ever made: the tavily-without-key path short-circuits,
and the DuckDuckGo inner runner is monkeypatched.
"""
from __future__ import annotations

import asyncio
import dataclasses

import httpx

from app.modules.ai import web_search
from app.modules.ai.web_search import SearchResult, format_results_for_prompt, search_web


@dataclasses.dataclass
class FakeSettings:
    web_search_enabled: bool = True
    web_search_provider: str = "tavily"
    web_search_max_results: int = 5
    tavily_api_key: str = ""
    llm_request_timeout: int = 60


def test_format_results_for_prompt() -> None:
    text = format_results_for_prompt(
        "погода москва",
        [
            SearchResult(
                title="Яндекс.Погода",
                url="https://yandex.ru/pogoda/moscow",
                snippet="Облачно, +5°C",
            )
        ],
    )
    assert "погода москва" in text
    assert "Яндекс.Погода" in text
    assert "https://yandex.ru/pogoda/moscow" in text
    assert "+5°C" in text


async def test_tavily_without_key_returns_empty() -> None:
    """provider=tavily + missing key must NOT fall back to DDG — returns []."""
    settings = FakeSettings(web_search_provider="tavily", tavily_api_key="")
    assert await search_web("погода", settings) == []


async def test_empty_query_returns_empty() -> None:
    settings = FakeSettings(web_search_provider="tavily", tavily_api_key="key")
    assert await search_web("   ", settings) == []


async def test_unknown_provider_returns_empty() -> None:
    settings = FakeSettings(web_search_provider="bing", tavily_api_key="key")
    assert await search_web("погода", settings) == []


async def test_duckduckgo_exception_returns_empty(monkeypatch) -> None:
    """An explicit DDG opt-in that raises must degrade to [] (never raise)."""
    def boom(*args, **kwargs):
        raise RuntimeError("ddg connection reset")

    monkeypatch.setattr("duckduckgo_search.DDGS", boom)

    settings = FakeSettings(web_search_provider="duckduckgo")
    assert await search_web("погода", settings) == []


async def test_duckduckgo_timeout_returns_empty(monkeypatch) -> None:
    """A DDG call that hangs must be cut off by the hard timeout and return []."""
    async def fake_wait_for(awaitable, timeout):
        # Consume the coroutine to avoid "never awaited" warnings, then time out.
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(web_search.asyncio, "wait_for", fake_wait_for)

    settings = FakeSettings(web_search_provider="duckduckgo")
    assert await search_web("погода", settings) == []


async def test_tavily_http_error_returns_empty(monkeypatch) -> None:
    """A Tavily HTTP failure degrades gracefully to [] instead of raising."""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeClient)

    results = await web_search._search_tavily("погода", "key", 5)
    assert results == []
