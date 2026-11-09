"""Выдача USDT операторам — лог и статистика с последней записи."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from payroll_base import order_in_shift


async def _orders_for_operator_since(
    conn,
    operator_id: int,
    since: datetime,
    shift_started: datetime,
    shift_ended: datetime | None,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT order_id, direction, crypto, crypto_amount, fiat_amount, created_at
        FROM orders
        WHERE operator_id = $1
          AND status IN ('PAID', 'COMPLETED')
          AND created_at >= $2
        ORDER BY created_at
        """,
        operator_id,
        since,
    )
    out: list[dict] = []
    for r in rows:
        o = dict(r)
        if not order_in_shift(o["created_at"], shift_started, shift_ended):
            continue
        out.append(o)
    return out


def _stats_from_orders(orders: list[dict]) -> dict[str, Any]:
    orders_count = len(orders)
    fiat_total = sum(float(o.get("fiat_amount") or 0) for o in orders)
    crypto_sent: dict[str, float] = {}
    for o in orders:
        if (o.get("direction") or "").lower() != "buy":
            continue
        c = (o.get("crypto") or "").split("_")[0].lower()
        crypto_sent[c] = crypto_sent.get(c, 0.0) + float(o.get("crypto_amount") or 0)
    return {
        "orders_count": orders_count,
        "fiat_total": round(fiat_total, 2),
        "crypto_sent_buy": {k: round(v, 8) for k, v in crypto_sent.items()},
    }


async def shift_usdt_context(conn, operator_id: int) -> dict | None:
    """Контекст активной смены для записи USDT владельцем."""
    shift = await conn.fetchrow(
        """
        SELECT id, started_at, ended_at
        FROM operator_shifts
        WHERE operator_id = $1 AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        operator_id,
    )
    if not shift:
        return None

    shift_id = int(shift["id"])
    started_at = shift["started_at"]

    last_row = await conn.fetchrow(
        """
        SELECT created_at, amount_usdt
        FROM operator_usdt_issuances
        WHERE shift_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        shift_id,
    )
    since = last_row["created_at"] if last_row else started_at

    total_usdt = float(
        await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_usdt), 0)
            FROM operator_usdt_issuances
            WHERE shift_id = $1
            """,
            shift_id,
        )
        or 0
    )

    orders = await _orders_for_operator_since(
        conn, operator_id, since, started_at, None
    )
    period_stats = _stats_from_orders(orders)

    return {
        "shift_id": shift_id,
        "shift_started_at": started_at.isoformat() if hasattr(started_at, "isoformat") else started_at,
        "last_issuance_at": (
            last_row["created_at"].isoformat()
            if last_row and hasattr(last_row["created_at"], "isoformat")
            else None
        ),
        "last_issuance_usdt": float(last_row["amount_usdt"]) if last_row else None,
        "usdt_issued_total": round(total_usdt, 8),
        "since_last_issuance": period_stats,
    }


async def usdt_issued_total_for_shift(conn, shift_id: int) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_usdt), 0)
        FROM operator_usdt_issuances
        WHERE shift_id = $1
        """,
        shift_id,
    )
    return float(val or 0)


async def usdt_issued_total_for_period(conn, d_from, d_to) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_usdt), 0)
        FROM operator_usdt_issuances
        WHERE created_at::date BETWEEN $1 AND $2
        """,
        d_from,
        d_to,
    )
    return float(val or 0)
