"""Дублирует BUY PAID-уведомление в Business/web-чат через exchange internal API."""
from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger("buyer_payout_notify")

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (
    os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or ""
).strip()


async def deliver_buy_payout_to_client_chat(order: dict, explorer_url: str) -> bool:
    order_id = str(order.get("order_id") or "").strip()
    if not order_id:
        return False
    if not INTERNAL_TOKEN:
        logger.warning("buy payout chat notify skipped: INTERNAL_API_SECRET not set")
        return False
    url = f"{EXCHANGE_API_URL}/api/internal/buyer/buy-payout-notify"
    payload = {
        "order_id": order_id,
        "explorer_url": (explorer_url or "").strip(),
    }
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as r:
                if r.status >= 400:
                    text = await r.text()
                    logger.warning(
                        "buy payout chat notify order=%s -> %s: %s",
                        order_id,
                        r.status,
                        text[:300],
                    )
                    return False
                data = await r.json(content_type=None)
                return bool((data or {}).get("ok"))
    except Exception as e:
        logger.warning("buy payout chat notify order=%s failed: %s", order_id, e)
        return False
