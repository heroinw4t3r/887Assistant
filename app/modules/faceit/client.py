"""FACEIT Data API client.

CONTRACT:
  * Base URL: https://open.faceit.com/data/v4
  * Auth header: ``Authorization: Bearer <FACEIT_API_KEY>``
  * Lookup: GET /players?nickname=<nick>  (case-sensitive)
        200 -> nickname is taken (returns player object)
        404 -> nickname not found (free for normal registration)
  * Must honour FACEIT_RATE_LIMIT_RPS and respect FACEIT ToS.

TODO(subagent-4): implement an httpx async client with a token-bucket/throttle
and a small TTL cache.
"""
from __future__ import annotations
