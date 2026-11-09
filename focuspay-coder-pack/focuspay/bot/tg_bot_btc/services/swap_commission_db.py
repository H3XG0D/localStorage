"""Запись комиссий со свапов в БД."""
from __future__ import annotations

import logging
from decimal import Decimal

from services.db import get_pool
from services.rates_api import get_market_price

logger = logging.getLogger("swap_commission_db")


async def crypto_amount_to_rub(crypto: str, amount: Decimal) -> tuple[float, float]:
    """Возвращает (rate_rub_per_unit, amount_rub)."""
    c = (crypto or "").lower()
    if c == "rub":
        amt = float(amount)
        return 1.0, round(amt, 2)
    price, stale, blocked = await get_market_price(c)
    if blocked or price is None or price <= 0:
        raise ValueError(f"Нет курса для {c.upper()}")
    if stale:
        logger.warning("swap commission: stale rate for %s", c)
    rate = float(price)
    return rate, round(rate * float(amount), 2)


async def insert_swap_commission_entry(
    *,
    chat_id: int,
    message_id: int,
    topic_id: int | None,
    telegram_user_id: int | None,
    raw_text: str,
    crypto: str,
    crypto_amount: Decimal,
    part_index: int = 0,
) -> dict | None:
    rate_rub, amount_rub = await crypto_amount_to_rub(crypto, crypto_amount)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO swap_commission_entries (
                chat_id, message_id, part_index, topic_id, telegram_user_id,
                raw_text, crypto, crypto_amount, rate_rub, amount_rub
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (chat_id, message_id, part_index) DO NOTHING
            RETURNING *
            """,
            chat_id,
            message_id,
            part_index,
            topic_id,
            telegram_user_id,
            raw_text[:2000],
            crypto.lower(),
            float(crypto_amount),
            rate_rub,
            amount_rub,
        )
    return dict(row) if row else None
