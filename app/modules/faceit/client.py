"""FACEIT Data API client.

CONTRACT:
  * Base URL: https://open.faceit.com/data/v4
  * Auth header: ``Authorization: Bearer <FACEIT_API_KEY>``
  * Lookup: GET /players?nickname=<nick>  (CASE-SENSITIVE)
        200 -> nickname is TAKEN (returns a player object)
        404 -> nickname not found  (FREE for normal registration)
        429 -> rate limited (back off / retry)
        other / 5xx / network -> ERROR (unknown; never assume free)
  * Must honour FACEIT_RATE_LIMIT_RPS and respect FACEIT ToS.

Implementation notes:
  * A single shared ``httpx.AsyncClient`` is reused across requests.
  * Rate limiting is a simple min-interval throttle (1 / rps) guarded by an
    ``asyncio.Lock`` so concurrent callers are serialised to the configured pace.
  * A small TTL dict caches definitive TAKEN/FREE answers (never transient
    ERRORs) to avoid re-hitting the API for the same nickname within the window.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum

import httpx

BASE_URL = "https://open.faceit.com/data/v4"
_PLAYERS_PATH = "/players"

# How many times to retry a 429 before giving up and returning ERROR.
_MAX_429_RETRIES = 2
# Base back-off (seconds) used when the API does not send a Retry-After header.
_DEFAULT_RETRY_AFTER = 1.0


class NickStatus(str, Enum):
    """Definitive availability verdict for a FACEIT nickname."""

    TAKEN = "taken"
    FREE = "free"
    ERROR = "error"


@dataclass(slots=True)
class NickResult:
    """Result of a single nickname lookup."""

    nickname: str
    status: NickStatus
    player_id: str | None = None
    detail: str | None = None

    @property
    def is_free(self) -> bool:
        return self.status is NickStatus.FREE

    @property
    def is_taken(self) -> bool:
        return self.status is NickStatus.TAKEN


class FaceitClient:
    """Async client for the FACEIT Data API player-lookup endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        rps: float = 4.0,
        cache_ttl: int = 600,
        timeout: float = 10.0,
        base_url: str = BASE_URL,
    ) -> None:
        if not api_key:
            raise ValueError(
                "FACEIT_API_KEY is empty. Set it in the environment before using FaceitClient."
            )
        self._api_key = api_key
        # Guard against a zero / negative rps that would break the interval math.
        self._min_interval = 1.0 / rps if rps and rps > 0 else 0.0
        self._cache_ttl = max(0, cache_ttl)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        # Throttle state.
        self._rate_lock = asyncio.Lock()
        self._last_request_ts = 0.0
        # Cache: nickname -> (NickResult, expires_at monotonic ts).
        self._cache: dict[str, tuple[NickResult, float]] = {}

    async def _throttle(self) -> None:
        """Block until at least ``_min_interval`` has elapsed since the last call."""
        if self._min_interval <= 0:
            return
        async with self._rate_lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_ts = time.monotonic()

    def _cache_get(self, nickname: str) -> NickResult | None:
        cached = self._cache.get(nickname)
        if cached is None:
            return None
        result, expires_at = cached
        if time.monotonic() >= expires_at:
            self._cache.pop(nickname, None)
            return None
        return result

    def _cache_put(self, result: NickResult) -> None:
        # Only cache definitive answers; transient errors must be retried.
        if self._cache_ttl <= 0 or result.status is NickStatus.ERROR:
            return
        self._cache[result.nickname] = (result, time.monotonic() + self._cache_ttl)

    async def check(self, nickname: str) -> NickResult:
        """Look up a single nickname and return its availability verdict.

        The lookup is case-sensitive (FACEIT treats it so). Definitive
        TAKEN/FREE answers are cached for ``cache_ttl`` seconds.
        """
        cached = self._cache_get(nickname)
        if cached is not None:
            return cached

        result = await self._lookup(nickname)
        self._cache_put(result)
        return result

    async def _lookup(self, nickname: str) -> NickResult:
        attempt = 0
        while True:
            await self._throttle()
            try:
                response = await self._client.get(
                    _PLAYERS_PATH, params={"nickname": nickname}
                )
            except httpx.HTTPError as exc:
                return NickResult(
                    nickname=nickname,
                    status=NickStatus.ERROR,
                    detail=f"network error: {exc.__class__.__name__}",
                )

            status = response.status_code
            if status == 200:
                player_id = self._extract_player_id(response)
                return NickResult(
                    nickname=nickname, status=NickStatus.TAKEN, player_id=player_id
                )
            if status == 404:
                return NickResult(nickname=nickname, status=NickStatus.FREE)
            if status == 429:
                if attempt >= _MAX_429_RETRIES:
                    return NickResult(
                        nickname=nickname,
                        status=NickStatus.ERROR,
                        detail="rate limited (429) after retries",
                    )
                await asyncio.sleep(self._retry_after(response, attempt))
                attempt += 1
                continue
            return NickResult(
                nickname=nickname,
                status=NickStatus.ERROR,
                detail=f"unexpected HTTP {status}",
            )

    @staticmethod
    def _extract_player_id(response: httpx.Response) -> str | None:
        try:
            data = response.json()
        except ValueError:
            return None
        if isinstance(data, dict):
            return data.get("player_id")
        return None

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return max(0.0, float(header))
            except ValueError:
                pass
        # Exponential-ish back-off: 1s, 2s, ...
        return _DEFAULT_RETRY_AFTER * (2**attempt)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> FaceitClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
