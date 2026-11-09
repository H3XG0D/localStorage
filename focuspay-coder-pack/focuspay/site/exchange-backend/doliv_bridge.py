"""FocusPay → Doliv bridge client (payout jobs + card balances).

Enable with:
  DOLIV_BRIDGE_URL=http://localhost:8002
  DOLIV_BRIDGE_KEY=<raw key from Doliv admin>
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from config import settings

log = logging.getLogger("doliv_bridge")


def bridge_enabled() -> bool:
    url = (getattr(settings, "doliv_bridge_url", None) or "").strip()
    key = (getattr(settings, "doliv_bridge_key", None) or "").strip()
    return bool(url and key)


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Bridge-Key": (settings.doliv_bridge_key or "").strip(),
    }


def _base() -> str:
    return (settings.doliv_bridge_url or "").rstrip("/")


async def create_payout_job(
    *,
    amount_rub: float,
    pay_method: str = "sbp",
    requisites: dict | None = None,
    source: str = "freelancer",
    external_ref: str | None = None,
    ttl_minutes: int = 15,
) -> dict[str, Any] | None:
    if not bridge_enabled():
        return None
    payload = {
        "amount_rub": amount_rub,
        "pay_method": pay_method,
        "requisites": requisites or {},
        "source": source,
        "external_ref": external_ref,
        "ttl_minutes": ttl_minutes,
    }
    url = f"{_base()}/bridge/payout-jobs"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=_headers(), timeout=20) as resp:
                body = await resp.json(content_type=None)
                if resp.status >= 400:
                    log.warning("doliv create_payout_job HTTP %s: %s", resp.status, body)
                    return None
                return body
    except Exception as e:
        log.warning("doliv create_payout_job failed: %s", e)
        return None


async def card_balances() -> dict[str, Any] | None:
    if not bridge_enabled():
        return None
    url = f"{_base()}/bridge/card-balances"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_headers(), timeout=15) as resp:
                body = await resp.json(content_type=None)
                if resp.status >= 400:
                    return None
                return body
    except Exception as e:
        log.warning("doliv card_balances failed: %s", e)
        return None


async def get_payout_job(job_id: int) -> dict[str, Any] | None:
    if not bridge_enabled():
        return None
    url = f"{_base()}/bridge/payout-jobs/{job_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_headers(), timeout=15) as resp:
                if resp.status >= 400:
                    return None
                return await resp.json(content_type=None)
    except Exception as e:
        log.warning("doliv get_payout_job failed: %s", e)
        return None
