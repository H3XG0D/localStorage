"""Админ-обработка заявок на вывод внештатников (Telegram)."""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from services.db import get_pool

logger = logging.getLogger("external_payout_admin")


def _row(r) -> dict[str, Any]:
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


async def get_payout(payout_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              p.*,
              e.name AS exchanger_name,
              a.username AS exchanger_username
            FROM external_payouts p
            JOIN external_exchangers e ON e.id = p.exchanger_id
            LEFT JOIN external_exchanger_accounts a
              ON a.external_exchanger_id = p.exchanger_id
            WHERE p.id = $1
            """,
            payout_id,
        )
    return _row(row) if row else None


async def _ledger_balance_usd(conn, exchanger_id: int) -> float:
    val = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_usd), 0) FROM external_ledger WHERE exchanger_id = $1",
        exchanger_id,
    )
    return round(float(val or 0), 6)


async def process_payout_paid(
    payout_id: int,
    *,
    completed_by: str,
    receipt_file: str | None = None,
    tx_hash: str | None = None,
) -> tuple[bool, str | None, dict | None]:
    """pending → paid + ledger. Returns (ok, error_code, payout)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM external_payouts WHERE id = $1 FOR UPDATE",
                payout_id,
            )
            if not row:
                return False, "not_found", None
            if str(row["status"]) != "pending":
                return False, "already_processed", _row(row)

            exchanger_id = int(row["exchanger_id"])
            gross = float(row["gross_usd"])
            balance = await _ledger_balance_usd(conn, exchanger_id)
            if gross > balance + 0.000001:
                return False, "insufficient_balance", _row(row)

            fee = float(row["fee_usd"] or 0)
            net = float(row["net_usd"] or 0)
            updated = await conn.fetchrow(
                """
                UPDATE external_payouts
                SET status = 'paid',
                    tx_hash = COALESCE($2, tx_hash),
                    receipt_file = COALESCE($3, receipt_file)
                WHERE id = $1
                RETURNING *
                """,
                payout_id,
                (tx_hash or "").strip() or None,
                (receipt_file or "").strip() or None,
            )
            await conn.execute(
                """
                INSERT INTO external_ledger
                    (exchanger_id, type, amount_usd, payout_id, note)
                VALUES ($1, 'payout', $2, $3, $4)
                """,
                exchanger_id,
                -abs(gross),
                payout_id,
                f"Вывод: ${net:.2f} на руки, комиссия ${fee:.2f} · {completed_by}",
            )
    return True, None, _row(updated)


async def process_payout_rejected(
    payout_id: int,
    *,
    rejected_by: str,
    reason: str | None = None,
) -> tuple[bool, str | None, dict | None]:
    suffix = f" · reason: {reason.strip()}" if (reason or "").strip() else ""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE external_payouts
            SET status = 'rejected',
                note = CONCAT(
                    COALESCE(note, ''),
                    CASE WHEN COALESCE(note, '') = '' THEN '' ELSE ' ' END,
                    '[rejected by ', $2, $3, ']'
                )
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            payout_id,
            rejected_by,
            suffix,
        )
        if row:
            return True, None, _row(row)
        exists = await conn.fetchval(
            "SELECT 1 FROM external_payouts WHERE id = $1",
            payout_id,
        )
        if not exists:
            return False, "not_found", None
        current = await conn.fetchrow(
            "SELECT * FROM external_payouts WHERE id = $1",
            payout_id,
        )
        return False, "already_processed", _row(current) if current else None
