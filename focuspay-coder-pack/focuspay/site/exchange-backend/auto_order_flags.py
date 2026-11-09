"""Пометка auto_served на заявке."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("auto_order_flags")


async def mark_order_auto_served(conn, order_id: str, payment_snapshot: dict | None) -> None:
    snap = dict(payment_snapshot or {})
    snap["auto_served"] = True
    try:
        await conn.execute(
            """
            UPDATE orders
            SET auto_served = TRUE,
                payment_snapshot = COALESCE(payment_snapshot, '{}'::jsonb) || $2::jsonb
            WHERE order_id = $1
            """,
            order_id,
            json.dumps({"auto_served": True}),
        )
    except Exception:
        await conn.execute(
            """
            UPDATE orders
            SET payment_snapshot = COALESCE(payment_snapshot, '{}'::jsonb) || $2::jsonb
            WHERE order_id = $1
            """,
            order_id,
            json.dumps(snap),
        )
        logger.debug("orders.auto_served column missing", exc_info=True)
