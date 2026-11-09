"""Payfast webhook → exchange internal API для автоподтверждения внештатных сделок."""
from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger("external_deal_payfast_webhook")

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (
    os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or ""
).strip()


async def _post_internal(path: str, payload: dict) -> dict | None:
    if not INTERNAL_TOKEN:
        logger.warning("external deal webhook: INTERNAL_API_SECRET not set")
        return None
    url = f"{EXCHANGE_API_URL}/api/internal{path}"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as r:
                if r.status >= 400:
                    text = await r.text()
                    logger.warning("internal API %s -> %s: %s", path, r.status, text[:300])
                    return None
                return await r.json()
    except Exception as e:
        logger.warning("internal API %s failed: %s", path, e)
    return None


async def handle_external_deal_payfast_webhook(merchant_ref: str, webhook_body: dict) -> None:
    result = await _post_internal(
        "/external/deals/payfast-settled-by-ref",
        {"merchant_ref": merchant_ref, "webhook_body": webhook_body},
    )
    if result and result.get("confirmed"):
        logger.info(
            "external deal auto-confirmed ref=%s deal_id=%s",
            merchant_ref,
            result.get("deal_id"),
        )
    elif result:
        logger.debug(
            "external deal webhook skipped ref=%s reason=%s",
            merchant_ref,
            result.get("reason"),
        )
