"""10% маржи внештатной сделки — оператору(ам) на смене."""
from __future__ import annotations

import logging

logger = logging.getLogger("external_deal_shift_payroll")

SHIFT_EXTERNAL_DEAL_PERCENT = 10.0


async def fetch_active_shift_operator_ids(conn) -> list[int]:
    rows = await conn.fetch(
        """
        SELECT s.operator_id
        FROM operator_shifts s
        JOIN operator_accounts a ON a.id = s.operator_id
        WHERE s.ended_at IS NULL
          AND a.is_active = TRUE
        ORDER BY s.started_at ASC
        """
    )
    return [int(r["operator_id"]) for r in rows]


async def accrue_shift_external_deal(
    conn,
    *,
    deal_id: int,
    net_profit_rub: float,
) -> int:
    """Начислить 10% маржи активным операторам на смене (делится поровну)."""
    total = round(max(0.0, float(net_profit_rub)) * SHIFT_EXTERNAL_DEAL_PERCENT / 100.0, 2)
    if total <= 0:
        return 0

    operator_ids = await fetch_active_shift_operator_ids(conn)
    if not operator_ids:
        return 0

    per_op = round(total / len(operator_ids), 2)
    if per_op <= 0:
        return 0

    accrued = 0
    for operator_id in operator_ids:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM operator_payroll_ledger
            WHERE type = 'accrual'
              AND external_deal_id = $1
              AND operator_id = $2
            """,
            deal_id,
            operator_id,
        )
        if exists:
            continue

        op = await conn.fetchrow(
            "SELECT id, display_name, username FROM operator_accounts WHERE id = $1",
            operator_id,
        )
        if not op:
            continue

        name = op["display_name"] or op["username"] or str(operator_id)
        await conn.execute(
            """
            INSERT INTO operator_payroll_ledger (
                type, amount_rub, operator_id, external_deal_id, note
            )
            VALUES ('accrual', $1, $2, $3, $4)
            """,
            per_op,
            operator_id,
            deal_id,
            f"Внештат #{deal_id} · смена · {name}",
        )
        accrued += 1
        logger.info(
            "Shift external deal accrual deal=%s operator=%s amount=%.2f",
            deal_id,
            operator_id,
            per_op,
        )

    if accrued:
        await conn.execute(
            """
            UPDATE external_deals
            SET operator_earnings_rub = COALESCE(operator_earnings_rub, 0) + $2
            WHERE id = $1
            """,
            deal_id,
            round(per_op * accrued, 2),
        )
    return accrued
