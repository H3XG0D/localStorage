"""Сверка авто-выплат с сменами операторов (фаза 4)."""
from __future__ import annotations

import logging

from db import get_pool

logger = logging.getLogger("auto_recon")


async def record_auto_buy_payout(
    conn,
    order_id: str,
    amount_rub: float,
    coin: str,
    txid: str,
) -> None:
    """Пишет строку сверки; shift_id — смена, открытая на момент записи (если есть)."""
    shift_id = await conn.fetchval(
        """
        SELECT id FROM operator_shifts
        WHERE ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """
    )
    try:
        await conn.execute(
            """
            INSERT INTO auto_recon_entries (shift_id, order_id, amount_rub, coin, txid, note)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            shift_id,
            order_id,
            round(float(amount_rub), 2),
            coin.lower(),
            txid,
            "auto_buy_payout",
        )
    except Exception:
        logger.debug("auto_recon_entries insert skipped", exc_info=True)


async def list_recon_for_shift(shift_id: int, *, limit: int = 200) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM auto_recon_entries
            WHERE shift_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            int(shift_id),
            limit,
        )
    return [dict(r) for r in rows]
