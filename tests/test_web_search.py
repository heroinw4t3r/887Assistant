"""Tests for AI web search helpers."""
from __future__ import annotations

from app.modules.ai.web_search import SearchResult, format_results_for_prompt


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
