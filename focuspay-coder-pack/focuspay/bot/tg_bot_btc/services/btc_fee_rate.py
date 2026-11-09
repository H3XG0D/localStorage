"""Ставка отправки BTC (sat/vB) для котировки покупки через exchange-backend."""
from __future__ import annotations

import logging
import os
import time

import aiohttp

logger = logging.getLogger("btc_fee_rate")

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (
    os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or ""
).strip()

_TTL_SECONDS = 60.0
_cache: dict[str, float] = {}


async def btc_fee_rate_sat_vb() -> float | None:
    """None = ставка неизвестна. Котировка тогда идёт без наценки за сеть.

    Выдача реквизитов не должна зависеть от signer, поэтому любая ошибка здесь
    деградирует до «наценки нет», а не до отказа в обмене.
    """
    now = time.monotonic()
    cached = _cache.get("rate")
    if cached and now - _cache.get("at", 0.0) < _TTL_SECONDS:
        return cached
    if not INTERNAL_TOKEN:
        logger.warning("btc fee rate skipped: INTERNAL_API_SECRET not set")
        return cached or None

    url = f"{EXCHANGE_API_URL}/api/internal/btc-fee-rate"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status >= 400:
                    logger.warning("btc fee rate -> %s", response.status)
                    return cached or None
                data = await response.json(content_type=None)
    except Exception as exc:
        logger.warning("btc fee rate failed: %s", exc)
        return cached or None

    rate = float((data or {}).get("rate_sat_vb") or 0)
    if rate <= 0:
        return cached or None
    _cache.update({"rate": rate, "at": now})
    return rate
