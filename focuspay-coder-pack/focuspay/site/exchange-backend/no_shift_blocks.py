"""Запись отказов в no_shift_requisites_blocks (как в боте)."""
from __future__ import annotations

from db import get_pool


async def record_no_shift_block(
    user_id: int,
    direction: str,
    *,
    reason: str = "no_shift",
    fiat_amount: int | None = None,
) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        inserted = await conn.fetchval(
            """
            INSERT INTO no_shift_requisites_blocks (user_id, direction, reason, fiat_amount)
            SELECT $1, $2, $3, $4
            WHERE NOT EXISTS (
                SELECT 1 FROM no_shift_requisites_blocks
                WHERE user_id = $1 AND direction = $2
                  AND created_at > now() - interval '5 minutes'
            )
            RETURNING id
            """,
            int(user_id),
            (direction or "buy")[:16],
            (reason or "no_shift")[:20],
            fiat_amount,
        )
    return inserted is not None
