"""Кэш операторских фраз антиспама из Postgres (TTL 30 с)."""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("group_spam_phrases_store")

CACHE_TTL_SEC = 30

_cache: tuple[str, ...] = ()
_cache_ts: float = 0.0


def extra_phrases_cached() -> tuple[str, ...]:
    return _cache


async def refresh_phrases(*, force: bool = False) -> tuple[str, ...]:
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache_ts and now - _cache_ts < CACHE_TTL_SEC:
        return _cache
    try:
        from services.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT phrase FROM group_spam_phrases ORDER BY id")
        _cache = tuple(str(r["phrase"]) for r in rows if r["phrase"])
        _cache_ts = now
    except Exception:
        logger.warning("group_spam_phrases refresh failed", exc_info=True)
        _cache_ts = now
    return _cache


async def extra_phrases() -> tuple[str, ...]:
    return await refresh_phrases(force=False)
