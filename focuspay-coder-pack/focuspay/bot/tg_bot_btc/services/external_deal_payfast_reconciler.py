"""Сверка pending external_deals с Payfast — автоподтверждение для auto_credit."""
from __future__ import annotations

import asyncio
import logging
import os

import aiohttp

logger = logging.getLogger("external_deal_payfast_reconciler")

RECONCILE_INTERVAL_SEC = 120
RECONCILE_MIN_AGE_SEC = 90

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (
    os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or ""
).strip()


async def _post_internal(path: str, payload: dict) -> dict | None:
    if not INTERNAL_TOKEN:
        return None
    url = f"{EXCHANGE_API_URL}/api/internal{path}"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as r:
                if r.status >= 400:
                    return None
                return await r.json()
    except Exception as e:
        logger.debug("reconcile internal API failed: %s", e)
    return None


async def reconcile_one_external_deal(deal_id: int) -> bool:
    result = await _post_internal(
        f"/external/deals/{deal_id}/payfast-settled",
        {"webhook_body": None},
    )
    if result and result.get("confirmed"):
        logger.info("external deal reconcile confirmed deal_id=%s", deal_id)
        return True
    return False


async def external_deal_payfast_reconciler_task(
    *,
    shutdown_event: asyncio.Event | None = None,
    interval_sec: int = RECONCILE_INTERVAL_SEC,
    min_age_sec: int = RECONCILE_MIN_AGE_SEC,
) -> None:
    from services.db import get_external_deals_for_payfast_reconcile

    while True:
        if shutdown_event and shutdown_event.is_set():
            break
        try:
            rows = await get_external_deals_for_payfast_reconcile(min_age_sec)
            for row in rows:
                try:
                    await reconcile_one_external_deal(int(row["id"]))
                except Exception:
                    logger.exception(
                        "external deal reconcile failed deal_id=%s", row.get("id")
                    )
        except Exception:
            logger.exception("external_deal_payfast_reconciler loop error")

        if shutdown_event is None:
            await asyncio.sleep(interval_sec)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_sec)
            break
        except asyncio.TimeoutError:
            pass
