"""Аудит автовыплат на основном сервере."""
from __future__ import annotations

import json
import logging

from db import get_pool

logger = logging.getLogger("auto_payout_audit")


async def audit_payout_event(request_id: str, event: str, detail: dict | None = None) -> None:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO auto_payout_audit (request_id, event, detail)
                VALUES ($1, $2, $3::jsonb)
                """,
                request_id,
                event[:64],
                json.dumps(detail or {}, ensure_ascii=False),
            )
    except Exception:
        logger.debug("auto_payout_audit insert skipped", exc_info=True)
