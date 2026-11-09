"""Опрос баланса signer и запись hot_wallet_balances."""
from __future__ import annotations

import asyncio
import logging

from db import get_pool
from hot_wallet_topups import alert_topup_tick, effective_spendable
from signer_client import fetch_signer_balances, fetch_signer_health, signer_configured

logger = logging.getLogger("hot_wallet_monitor")

_POLL_SEC = 60
HEARTBEAT_COIN = "signer"


async def _coin_rates() -> dict:
    from routers.public import get_rates_cached

    try:
        return await get_rates_cached() or {}
    except Exception:
        logger.debug("rates unavailable for hot wallet snapshot", exc_info=True)
        return {}


async def record_project_addresses() -> None:
    """Пишет в историю адреса, которые сейчас отдаёт подписант и приём продаж."""
    from project_wallet_archive import record_live_project_addresses
    from signer_client import fetch_signer_deposit_addresses

    signer_addresses: dict = {}
    known = None
    if signer_configured():
        try:
            fetched = await fetch_signer_deposit_addresses()
            raw = fetched.get("addresses") if isinstance(fetched, dict) else None
            if isinstance(raw, dict):
                signer_addresses = raw
            known = fetched.get("known") if isinstance(fetched, dict) else None
        except Exception:
            logger.warning("deposit addresses unavailable for archive", exc_info=True)
            known = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        await record_live_project_addresses(
            conn,
            signer_addresses,
            known if isinstance(known, list) else None,
        )


async def record_hot_wallet_snapshot() -> None:
    if not signer_configured():
        return
    health = await fetch_signer_health()
    signer_ok = health.get("http_status") == 200 and str(health.get("status", "")).lower() in (
        "ok",
        "healthy",
        "",
    )
    bal = await fetch_signer_balances()
    coins = bal.get("coins") or {}
    if not isinstance(coins, dict):
        coins = {}
    rates = await _coin_rates() if coins else {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Heartbeat пишем всегда: иначе при недоступном signer новых строк нет
        # и предохранитель не отличает «молчит» от «ни разу не опрашивали».
        await conn.execute(
            """
            INSERT INTO hot_wallet_balances (coin, signer_ok)
            VALUES ($1, $2)
            """,
            HEARTBEAT_COIN,
            signer_ok,
        )
        for coin, row in coins.items():
            if not isinstance(row, dict):
                continue
            name = str(coin).lower()
            spendable = effective_spendable(row)
            try:
                rate = float(rates.get(name) or 0)
            except (TypeError, ValueError):
                rate = 0.0
            try:
                await conn.execute(
                    """
                    INSERT INTO hot_wallet_balances (
                        coin, confirmed, unconfirmed, spendable, signer_ok, value_rub
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    name,
                    float(row.get("confirmed") or 0),
                    float(row.get("unconfirmed") or 0),
                    spendable,
                    signer_ok,
                    round(spendable * rate, 2),
                )
            except Exception:
                logger.debug("hot_wallet_balances insert skipped", exc_info=True)


async def hot_wallet_monitor_loop() -> None:
    from network_fees import maybe_backfill

    fees_task: asyncio.Task | None = None
    while True:
        # Дозаливка комиссий ходит в эксплореры медленно — отдельной задачей,
        # чтобы не задерживать heartbeat подписанта.
        if fees_task is None or fees_task.done():
            fees_task = asyncio.create_task(maybe_backfill())
        try:
            await record_hot_wallet_snapshot()
            await record_project_addresses()
            from hot_wallet_alert import alert_hot_wallet_tick

            await alert_hot_wallet_tick()
            await alert_topup_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("hot wallet monitor tick failed")
        await asyncio.sleep(_POLL_SEC)
