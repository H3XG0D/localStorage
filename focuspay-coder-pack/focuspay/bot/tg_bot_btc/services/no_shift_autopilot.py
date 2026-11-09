"""Постоянный клиент получает реквизиты в боте без смены — решение принимает API."""
from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger("no_shift_autopilot")

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (
    os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or ""
).strip()


async def _post(path: str, payload: dict) -> dict | None:
    if not INTERNAL_TOKEN:
        logger.warning("no-shift autopilot skipped: INTERNAL_API_SECRET not set")
        return None
    url = f"{EXCHANGE_API_URL}/api/internal{path}"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status >= 400:
                    text = await response.text()
                    logger.warning(
                        "no-shift autopilot %s -> %s: %s",
                        path,
                        response.status,
                        text[:200],
                    )
                    return None
                data = await response.json(content_type=None)
                return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("no-shift autopilot %s failed: %s", path, exc)
        return None


async def no_shift_access(
    user_id: int,
    fiat_amount: int | None,
    *,
    crypto: str | None = None,
    crypto_amount: float | None = None,
) -> dict | None:
    """Решение API: kind, reason и цифры для отстука."""
    payload: dict = {
        "user_id": int(user_id),
        "direction": "buy",
        "fiat_amount": int(fiat_amount) if fiat_amount is not None else None,
    }
    if crypto:
        payload["crypto"] = str(crypto)[:32]
    if crypto_amount is not None:
        try:
            payload["crypto_amount"] = float(crypto_amount)
        except (TypeError, ValueError):
            pass
    return await _post("/no-shift-access", payload)


async def regular_may_skip_shift(user_id: int, fiat_amount: int | None) -> bool:
    """True только если API разрешил авто-реквизиты этому покупателю."""
    data = await no_shift_access(user_id, fiat_amount)
    return bool(data and data.get("kind") == "allow_auto")


async def mark_regular_no_shift_order(
    *,
    order_id: str,
    user_id: int,
    fiat_amount: float,
    crypto: str,
) -> None:
    if not order_id:
        return
    await _post(
        "/no-shift-access/served",
        {
            "order_id": str(order_id),
            "user_id": int(user_id),
            "fiat_amount": float(fiat_amount or 0),
            "crypto": str(crypto or "BTC"),
        },
    )
