"""Запрос авто-reserve вывода через exchange-backend (тот же путь, что кабинет)."""
from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger("auto_withdraw_client")

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (
    os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or ""
).strip()


async def request_auto_reserve(withdrawal_id: int) -> dict | None:
    """POST /api/internal/withdrawals/auto-reserve. None = сбой связи (заявка pending)."""
    if not INTERNAL_TOKEN:
        logger.warning("auto withdraw skipped: INTERNAL_API_SECRET not set")
        return None
    wid = int(withdrawal_id)
    url = f"{EXCHANGE_API_URL}/api/internal/withdrawals/auto-reserve"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, json={"withdrawal_id": wid}, headers=headers
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    logger.warning(
                        "auto withdraw #%s -> %s: %s",
                        wid,
                        response.status,
                        text[:200],
                    )
                    return None
                try:
                    data = await response.json(content_type=None)
                except Exception:
                    logger.warning("auto withdraw #%s bad json: %s", wid, text[:200])
                    return None
                return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("auto withdraw #%s failed: %s", wid, exc)
        return None
