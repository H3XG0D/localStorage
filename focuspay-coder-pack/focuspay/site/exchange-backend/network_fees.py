"""Учёт сетевых комиссий по всем выплатам крипты.

С кошелька проекта комиссию отдаёт подписант сразу после отправки. По хешам,
которые операторы вставляют со своих кошельков, комиссию дотягиваем из
публичных эксплореров в фоне — медленно, чтобы не упереться в их лимиты.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any

import aiohttp

from db import get_pool

logger = logging.getLogger("network_fees")

SOURCE_PROJECT = "project_wallet"
SOURCE_OPERATOR = "operator_wallet"

BACKFILL_EVERY_SEC = 10 * 60
BACKFILL_BATCH = 20
BACKFILL_DAYS = 30
REQUEST_GAP_SEC = 2.0
RETRY_AFTER = timedelta(hours=6)

_EXPLORERS = {
    "btc": "https://mempool.space/api/tx/{txid}",
    "ltc": "https://litecoinspace.org/api/tx/{txid}",
}
_BLOCKCHAIR = {
    "btc": "https://api.blockchair.com/bitcoin/dashboards/transaction/{txid}",
    "ltc": "https://api.blockchair.com/litecoin/dashboards/transaction/{txid}",
}
_TRONSCAN = "https://apilist.tronscanapi.com/api/transaction-info?hash={txid}"

_last_backfill = 0.0


def fee_unit(coin: str) -> str:
    """USDT ходит в сети TRON: комиссия сжигается в TRX."""
    return "trx" if coin in ("usdt", "trx") else coin


async def _rate_rub(coin: str) -> float:
    from routers.public import get_rates_cached

    try:
        rates = await get_rates_cached() or {}
        return float(rates.get(fee_unit(coin)) or 0)
    except Exception:
        logger.debug("rates unavailable for fee", exc_info=True)
        return 0.0


async def _upsert(
    conn,
    *,
    txid: str,
    coin: str,
    source: str,
    fee_crypto: float | None,
    vsize: int | None,
    order_id: str | None,
    request_id: str | None,
    status: str,
    rate_rub: float,
) -> None:
    fee_rub = round(fee_crypto * rate_rub, 2) if fee_crypto is not None and rate_rub > 0 else None
    feerate = None
    if fee_crypto is not None and vsize and coin in _EXPLORERS:
        feerate = round(fee_crypto * 1e8 / vsize, 3)
    await conn.execute(
        """
        INSERT INTO network_fees (
            txid, coin, fee_crypto, fee_rub, vsize, feerate_sat_vb,
            source, order_id, request_id, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (coin, txid) DO UPDATE SET
            fee_crypto = COALESCE(EXCLUDED.fee_crypto, network_fees.fee_crypto),
            fee_rub = COALESCE(EXCLUDED.fee_rub, network_fees.fee_rub),
            vsize = COALESCE(EXCLUDED.vsize, network_fees.vsize),
            feerate_sat_vb = COALESCE(EXCLUDED.feerate_sat_vb, network_fees.feerate_sat_vb),
            order_id = COALESCE(network_fees.order_id, EXCLUDED.order_id),
            request_id = COALESCE(network_fees.request_id, EXCLUDED.request_id),
            status = EXCLUDED.status,
            updated_at = now()
        """,
        txid,
        coin,
        Decimal(str(fee_crypto)) if fee_crypto is not None else None,
        Decimal(str(fee_rub)) if fee_rub is not None else None,
        int(vsize) if vsize else None,
        Decimal(str(feerate)) if feerate is not None else None,
        source,
        order_id,
        request_id,
        status,
    )


async def record_project_wallet_fee(
    *,
    order_id: str | None,
    request_id: str,
    coin: str,
    txid: str,
    fee_crypto: Any,
    vsize: Any,
) -> None:
    """Комиссия из ответа подписанта; без неё строка дотянется из эксплорера."""
    fee = float(fee_crypto) if fee_crypto not in (None, "") else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _upsert(
            conn,
            txid=txid,
            coin=coin,
            source=SOURCE_PROJECT,
            fee_crypto=fee,
            vsize=int(vsize) if vsize else None,
            order_id=order_id,
            request_id=request_id or None,
            status="ok" if fee is not None else "error",
            rate_rub=await _rate_rub(coin),
        )


def _vsize(weight: Any) -> int | None:
    return int(math.ceil(float(weight) / 4)) if weight else None


async def _esplora_fee(session, coin: str, txid: str) -> tuple[str, float | None, int | None]:
    async with session.get(_EXPLORERS[coin].format(txid=txid)) as resp:
        if resp.status in (400, 404):
            return "not_found", None, None
        if resp.status != 200:
            return "error", None, None
        data = await resp.json(content_type=None)
    if data.get("fee") is None:
        return "error", None, None
    return "ok", float(data["fee"]) / 1e8, _vsize(data.get("weight"))


async def _blockchair_fee(session, coin: str, txid: str) -> tuple[str, float | None, int | None]:
    async with session.get(_BLOCKCHAIR[coin].format(txid=txid)) as resp:
        if resp.status == 404:
            return "not_found", None, None
        if resp.status != 200:
            return "error", None, None
        data = await resp.json(content_type=None)
    tx = (((data or {}).get("data") or {}).get(txid) or {}).get("transaction")
    if not tx:
        return "not_found", None, None
    if tx.get("fee") is None:
        return "error", None, None
    return "ok", float(tx["fee"]) / 1e8, _vsize(tx.get("weight"))


async def fetch_explorer_fee(
    session: aiohttp.ClientSession, coin: str, txid: str
) -> tuple[str, float | None, int | None]:
    """(status, fee в монете комиссии, vsize). status: ok | not_found | error."""
    if coin in _EXPLORERS:
        try:
            result = await _esplora_fee(session, coin, txid)
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
            result = ("error", None, None)
        if result[0] != "error":
            return result
        # litecoinspace часто отвечает 503 под нагрузкой — второй источник.
        return await _blockchair_fee(session, coin, txid)
    if coin in ("usdt", "trx"):
        async with session.get(_TRONSCAN.format(txid=txid)) as resp:
            if resp.status != 200:
                return "error", None, None
            data = await resp.json(content_type=None)
        if not data or not data.get("hash"):
            return "not_found", None, None
        cost = data.get("cost") or {}
        return "ok", float(cost.get("fee") or 0) / 1e6, None
    return "not_found", None, None


async def _backfill_candidates(conn) -> list[dict]:
    rows = await conn.fetch(
        """
        WITH cand AS (
            SELECT DISTINCT ON (lower(split_part(o.crypto, '_', 1)), o.payout_tx_hash)
                   o.payout_tx_hash AS txid,
                   lower(split_part(o.crypto, '_', 1)) AS coin,
                   o.order_id,
                   pr.request_id,
                   o.updated_at AS at
            FROM orders o
            LEFT JOIN payout_requests pr
              ON pr.ref_id = o.order_id AND pr.txid = o.payout_tx_hash
            WHERE lower(o.direction) = 'buy' AND o.status = 'PAID'
              AND COALESCE(o.payout_tx_hash, '') <> ''
              AND o.updated_at >= now() - make_interval(days => $1)
            UNION ALL
            SELECT pr.txid, pr.coin, NULL, pr.request_id, pr.updated_at
            FROM payout_requests pr
            WHERE pr.kind <> 'buy_order' AND pr.kind <> 'manual_buy'
              AND COALESCE(pr.txid, '') <> ''
              AND pr.status IN ('sent', 'confirmed')
              AND pr.updated_at >= now() - make_interval(days => $1)
        )
        SELECT c.* FROM cand c
        LEFT JOIN network_fees nf ON nf.coin = c.coin AND nf.txid = c.txid
        WHERE c.coin IN ('btc', 'ltc', 'usdt', 'trx')
          AND (nf.id IS NULL
               OR (nf.status = 'error' AND nf.updated_at < now() - $2::interval))
        ORDER BY c.at DESC
        LIMIT $3
        """,
        BACKFILL_DAYS,
        RETRY_AFTER,
        BACKFILL_BATCH,
    )
    return [dict(r) for r in rows]


async def backfill_tick() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        cands = await _backfill_candidates(conn)
    if not cands:
        return 0
    rates: dict[str, float] = {}
    done = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        for c in cands:
            coin, txid = c["coin"], c["txid"]
            try:
                status, fee, vsize = await fetch_explorer_fee(session, coin, txid)
            except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
                status, fee, vsize = "error", None, None
            if coin not in rates:
                rates[coin] = await _rate_rub(coin)
            async with pool.acquire() as conn:
                await _upsert(
                    conn,
                    txid=txid,
                    coin=coin,
                    source=SOURCE_PROJECT if c.get("request_id") else SOURCE_OPERATOR,
                    fee_crypto=fee,
                    vsize=vsize,
                    order_id=c.get("order_id"),
                    request_id=c.get("request_id"),
                    status=status,
                    rate_rub=rates[coin],
                )
            done += 1
            await asyncio.sleep(REQUEST_GAP_SEC)
    return done


async def maybe_backfill() -> None:
    """Вызывается из цикла мониторинга кошелька; сам решает, пора ли."""
    global _last_backfill
    if time.monotonic() - _last_backfill < BACKFILL_EVERY_SEC:
        return
    _last_backfill = time.monotonic()
    try:
        n = await backfill_tick()
        if n:
            logger.info("network fees backfill: %s tx", n)
    except Exception:
        logger.exception("network fees backfill failed")


async def fees_summary(conn, days: int = 30) -> dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT source, coin,
               COUNT(*)::int AS tx,
               COALESCE(SUM(fee_rub), 0)::float AS fee_rub,
               COALESCE(AVG(fee_rub), 0)::float AS avg_fee_rub,
               COALESCE(SUM(fee_crypto), 0)::float AS fee_crypto,
               AVG(feerate_sat_vb)::float AS avg_sat_vb
        FROM network_fees
        WHERE status = 'ok' AND created_at >= now() - make_interval(days => $1)
        GROUP BY source, coin
        ORDER BY source, coin
        """,
        int(days),
    )
    pending = await conn.fetchval(
        "SELECT COUNT(*)::int FROM network_fees WHERE status <> 'ok'"
    )
    items = [
        {
            **dict(r),
            "fee_unit": fee_unit(r["coin"]),
            "avg_sat_vb": round(r["avg_sat_vb"], 2) if r["avg_sat_vb"] is not None else None,
        }
        for r in rows
    ]
    return {
        "days": days,
        "items": items,
        "total_rub": round(sum(i["fee_rub"] for i in items), 2),
        "unresolved": int(pending or 0),
    }
