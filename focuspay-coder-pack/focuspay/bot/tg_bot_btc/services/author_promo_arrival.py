"""Приход по ссылке автора t.me/...?start=p_CODE. Не тратит лимит активаций купона."""
from __future__ import annotations

import logging
import re

from services.db import get_pool

logger = logging.getLogger("author_promo_arrival")

_START = re.compile(r"^p_([A-Za-z0-9]+)", re.IGNORECASE)


def author_coupon_block_reason(
    author_telegram_id,
    user_id: int,
    *,
    has_completed_order: bool,
) -> str | None:
    """Зеркало site/exchange-backend/author_promo.author_coupon_block_reason."""
    if author_telegram_id is None:
        return None
    if int(author_telegram_id) == int(user_id):
        return "Нельзя использовать свой промокод"
    if has_completed_order:
        return "Промокод только для первого обмена"
    return None


def parse_author_start(payload: str) -> str | None:
    match = _START.match((payload or "").strip())
    if not match:
        return None
    return match.group(1).upper()


async def assign_author_arrival(conn, user_id: int, code: str) -> bool:
    campaign = await conn.fetchrow(
        """
        SELECT code, author_telegram_id
        FROM promo_campaigns
        WHERE UPPER(code) = $1
          AND author_telegram_id IS NOT NULL
          AND is_active = TRUE
        """,
        code,
    )
    if not campaign:
        return False
    if int(campaign["author_telegram_id"]) == int(user_id):
        return False
    result = await conn.execute(
        """
        INSERT INTO promo_attributions (user_id, promo_code, assigned_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO NOTHING
        """,
        int(user_id),
        campaign["code"],
    )
    return str(result).endswith("1")


async def apply_author_promo_arrival(user_id: int, payload: str) -> bool:
    code = parse_author_start(payload)
    if not code:
        return False
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await assign_author_arrival(conn, user_id, code)
    except Exception as exc:
        logger.warning("author arrival failed user=%s: %r", user_id, exc)
        return False
