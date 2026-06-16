"""Tests for the FACEIT nickname-checker module (no real network)."""
from __future__ import annotations

import httpx
import pytest

from app.modules.faceit.charset import (
    count_digit,
    count_letter,
    iter_digit_nicknames,
    iter_letter_nicknames,
)
from app.modules.faceit.client import FaceitClient, NickStatus
from app.modules.faceit.service import format_check_results, format_free_list


# --- charset -----------------------------------------------------------------
def test_counts():
    assert count_letter(3) == 17576
    assert count_digit(3) == 1000


def test_letter_bounds():
    letters = list(iter_letter_nicknames(3))
    assert len(letters) == 17576
    assert letters[0] == "aaa"
    assert letters[-1] == "zzz"


def test_digit_bounds():
    digits = list(iter_digit_nicknames(3))
    assert len(digits) == 1000
    assert digits[0] == "000"
    assert digits[-1] == "999"


# --- client ------------------------------------------------------------------
def _make_client(handler, *, rps: float = 1000.0) -> FaceitClient:
    """Build a FaceitClient whose HTTP layer is a MockTransport."""
    client = FaceitClient("test-key", rps=rps, cache_ttl=600)
    client._client = httpx.AsyncClient(
        base_url="https://open.faceit.com/data/v4",
        transport=httpx.MockTransport(handler),
    )
    return client


def test_empty_api_key_raises():
    with pytest.raises(ValueError):
        FaceitClient("")


async def test_check_taken():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("nickname") == "s1mple"
        return httpx.Response(200, json={"player_id": "abc-123", "country": "ua"})

    client = _make_client(handler)
    try:
        result = await client.check("s1mple")
    finally:
        await client.aclose()
    assert result.status is NickStatus.TAKEN
    assert result.player_id == "abc-123"


async def test_check_free():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": []})

    client = _make_client(handler)
    try:
        result = await client.check("zzqxv")
    finally:
        await client.aclose()
    assert result.status is NickStatus.FREE
    assert result.player_id is None


async def test_check_429_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"player_id": "after-retry"})

    client = _make_client(handler)
    try:
        result = await client.check("retryme")
    finally:
        await client.aclose()
    assert calls["n"] == 2
    assert result.status is NickStatus.TAKEN
    assert result.player_id == "after-retry"


async def test_check_unexpected_status_is_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _make_client(handler)
    try:
        result = await client.check("boom")
    finally:
        await client.aclose()
    assert result.status is NickStatus.ERROR


async def test_check_caches_definitive_answer():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client = _make_client(handler)
    try:
        await client.check("freenick")
        await client.check("freenick")
    finally:
        await client.aclose()
    assert calls["n"] == 1  # second call served from cache


# --- service formatters ------------------------------------------------------
def _result(nick, status, **kw):
    from app.modules.faceit.client import NickResult

    return NickResult(nickname=nick, status=status, **kw)


def test_format_free_list_wraps_in_code():
    results = [
        _result("aaa", NickStatus.FREE),
        _result("bbb", NickStatus.TAKEN, player_id="x"),
        _result("ccc", NickStatus.FREE),
        _result("ddd", NickStatus.ERROR, detail="boom"),
    ]
    chunks = format_free_list(results)
    assert len(chunks) >= 1
    joined = "\n".join(chunks)
    assert "<code>aaa</code>" in joined
    assert "<code>ccc</code>" in joined
    # taken nick must not appear in the free list section
    assert "<code>bbb</code>" not in joined
    # header counts
    assert "Свободно" in joined


def test_format_free_list_no_free():
    results = [_result("bbb", NickStatus.TAKEN)]
    chunks = format_free_list(results)
    assert len(chunks) == 1
    assert "не найдено" in chunks[0].lower()


def test_format_free_list_chunking():
    # Many free nicks must split into multiple chunks under the size cap.
    results = [_result(f"n{i:05d}", NickStatus.FREE) for i in range(2000)]
    chunks = format_free_list(results)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 3500


def test_format_check_results_labels():
    results = [
        _result("free1", NickStatus.FREE),
        _result("taken1", NickStatus.TAKEN, player_id="x"),
        _result("err1", NickStatus.ERROR, detail="boom"),
    ]
    text = format_check_results(results)
    assert "✅ <code>free1</code>" in text
    assert "⛔ <code>taken1</code>" in text
    assert "⚠️ <code>err1</code>" in text


def test_format_check_results_empty():
    assert "Не переданы" in format_check_results([])
