"""Зарплата операторов: начисления на личный баланс, заявки на вывод."""
from __future__ import annotations

import html
import logging

from db import get_pool
from payroll_base import stats_from_orders_conn

logger = logging.getLogger("operator_payroll_pool")


async def backfill_accruals(conn) -> int:
    """Догнать начисления по закрытым сменам без accrual."""
    from operator_payroll_split import backfill_order_payroll_splits

    split_count = await backfill_order_payroll_splits(conn)
    rows = await conn.fetch(
        """
        SELECT s.id, s.operator_id
        FROM operator_shifts s
        WHERE s.ended_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM operator_payroll_ledger l
              WHERE l.shift_id = s.id AND l.type = 'accrual'
          )
        ORDER BY s.ended_at ASC
        LIMIT 200
        """
    )
    n = split_count
    for r in rows:
        if await accrue_shift(conn, int(r["id"]), int(r["operator_id"])):
            n += 1
    return n


async def operator_balance(conn, operator_id: int) -> dict:
    """Личный баланс оператора (net по его строкам в ledger)."""
    total = float(
        await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM operator_payroll_ledger
            WHERE operator_id = $1
            """,
            operator_id,
        )
        or 0
    )
    pending = float(
        await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM operator_payroll_ledger
            WHERE operator_id = $1 AND type = 'hold'
            """,
            operator_id,
        )
        or 0
    )
    pending_requests = int(
        await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM operator_payout_requests
            WHERE operator_id = $1 AND status = 'pending'
            """,
            operator_id,
        )
        or 0
    )
    available = total
    return {
        "total_rub": round(total, 2),
        "pending_holds_rub": round(abs(pending), 2),
        "available_rub": round(available, 2),
        "pending_requests_count": pending_requests,
    }


async def operator_payroll_snapshot(conn, operator_id: int) -> dict:
    """Начислено / выплачено / штрафы / доступно по одному оператору."""
    row = await conn.fetchrow(
        """
        SELECT
            COALESCE(SUM(amount_rub), 0)::float AS available_rub,
            COALESCE(SUM(amount_rub) FILTER (WHERE type IN ('accrual', 'hourly')), 0)::float AS accrued_rub,
            COALESCE(SUM(ABS(amount_rub)) FILTER (WHERE type = 'payout'), 0)::float AS paid_rub,
            COALESCE(SUM(ABS(amount_rub)) FILTER (WHERE type = 'penalty'), 0)::float AS penalty_rub
        FROM operator_payroll_ledger
        WHERE operator_id = $1
        """,
        operator_id,
    )
    return {
        "available_rub": round(float((row and row["available_rub"]) or 0), 2),
        "accrued_rub": round(float((row and row["accrued_rub"]) or 0), 2),
        "paid_rub": round(float((row and row["paid_rub"]) or 0), 2),
        "penalty_rub": round(float((row and row["penalty_rub"]) or 0), 2),
    }


def serialize_payroll_ledger_row(row) -> dict:
    d = dict(row)
    if d.get("amount_rub") is not None:
        d["amount_rub"] = round(float(d["amount_rub"]), 2)
    created = d.get("created_at")
    if created is not None and hasattr(created, "isoformat"):
        d["created_at"] = created.isoformat()
    return d


async def apply_operator_penalty(
    conn,
    operator_id: int,
    amount_rub: float,
    reason: str,
    admin_label: str = "",
) -> dict:
    """Списать штраф с личного баланса. Вызывать внутри транзакции."""
    amount = round(float(amount_rub), 2)
    if amount <= 0:
        raise ValueError("Укажите сумму больше нуля")
    note_reason = (reason or "").strip()
    if len(note_reason) < 2:
        raise ValueError("Укажите причину штрафа")

    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('operator_payroll_pool'))"
    )

    exists = await conn.fetchval(
        "SELECT 1 FROM operator_accounts WHERE id = $1",
        operator_id,
    )
    if not exists:
        raise ValueError("Оператор не найден")

    bal = await operator_balance(conn, operator_id)
    if amount > bal["available_rub"] + 0.01:
        raise ValueError(
            f"Недостаточно на балансе. Доступно: {bal['available_rub']:,.2f} ₽"
        )

    admin_part = f" · {admin_label.strip()}" if (admin_label or "").strip() else ""
    note = f"Штраф · {note_reason}{admin_part}"
    row = await conn.fetchrow(
        """
        INSERT INTO operator_payroll_ledger (
            type, amount_rub, operator_id, note
        )
        VALUES ('penalty', $1, $2, $3)
        RETURNING *
        """,
        -amount,
        operator_id,
        note,
    )
    logger.info(
        "Payroll penalty %.2f operator=%s admin=%s",
        amount,
        operator_id,
        admin_label or "-",
    )
    return dict(row)


async def pool_balance(conn) -> dict:
    total = float(
        await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0)::float FROM operator_payroll_ledger"
        )
        or 0
    )
    pending = float(
        await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM operator_payroll_ledger
            WHERE type = 'hold'
            """
        )
        or 0
    )
    pending_requests = int(
        await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM operator_payout_requests
            WHERE status = 'pending'
            """
        )
        or 0
    )
    available = total
    return {
        "total_rub": round(total, 2),
        "pending_holds_rub": round(abs(pending), 2),
        "available_rub": round(available, 2),
        "pending_requests_count": pending_requests,
    }


async def accrue_shift(conn, shift_id: int, operator_id: int) -> bool:
    """Начислить заработок закрытой смены на баланс оператора (идемпотентно)."""
    exists = await conn.fetchval(
        """
        SELECT 1 FROM operator_payroll_ledger
        WHERE type = 'accrual' AND shift_id = $1
        """,
        shift_id,
    )
    if exists:
        return False

    shift = await conn.fetchrow(
        "SELECT * FROM operator_shifts WHERE id = $1",
        shift_id,
    )
    if not shift or shift["ended_at"] is None:
        return False

    op = await conn.fetchrow(
        "SELECT id, percent, display_name, username FROM operator_accounts WHERE id = $1",
        operator_id,
    )
    if not op:
        return False

    from operator_earnings import utc_aware

    started = utc_aware(shift["started_at"])
    ended = utc_aware(shift["ended_at"])
    from payroll_base import fetch_shift_orders

    order_rows = await fetch_shift_orders(conn, operator_id, started, ended)
    orders = [dict(r) for r in order_rows]
    summary = await stats_from_orders_conn(
        conn, orders, float(op["percent"] or 0)
    )
    earnings = float(summary.get("earnings_rub") or 0)
    if earnings <= 0:
        return False

    name = op["display_name"] or op["username"]
    await conn.execute(
        """
        INSERT INTO operator_payroll_ledger (
            type, amount_rub, shift_id, operator_id, note
        )
        VALUES ('accrual', $1, $2, $3, $4)
        """,
        earnings,
        shift_id,
        operator_id,
        f"Смена #{shift_id} · {name}",
    )
    logger.info(
        "Payroll accrual %.2f shift=%s operator=%s",
        earnings,
        shift_id,
        operator_id,
    )
    return True


async def accrue_external_deal(
    conn,
    *,
    deal_id: int,
    operator_id: int,
    earnings_rub: float,
) -> bool:
    """Начислить оператору % с маржи внештатной сделки (идемпотентно)."""
    earnings = round(float(earnings_rub or 0), 2)
    if earnings <= 0:
        return False

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
        return False

    op = await conn.fetchrow(
        "SELECT id, display_name, username FROM operator_accounts WHERE id = $1",
        operator_id,
    )
    if not op:
        return False

    name = op["display_name"] or op["username"] or str(operator_id)
    await conn.execute(
        """
        INSERT INTO operator_payroll_ledger (
            type, amount_rub, operator_id, external_deal_id, note
        )
        VALUES ('accrual', $1, $2, $3, $4)
        """,
        earnings,
        operator_id,
        deal_id,
        f"Внештатная сделка #{deal_id} · {name}",
    )
    logger.info(
        "Payroll accrual external deal=%s operator=%s amount=%.2f",
        deal_id,
        operator_id,
        earnings,
    )
    return True


async def create_payout_request(
    *,
    operator_id: int,
    amount_rub: float,
    requisites: str,
) -> dict:
    amount = round(float(amount_rub), 2)
    if amount <= 0:
        raise ValueError("Укажите сумму больше нуля")
    req = (requisites or "").strip()
    if len(req) < 5:
        raise ValueError("Укажите реквизиты для выплаты")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext('operator_payroll_pool'))"
            )
            pending_op = await conn.fetchval(
                """
                SELECT 1 FROM operator_payout_requests
                WHERE operator_id = $1 AND status = 'pending'
                """,
                operator_id,
            )
            if pending_op:
                raise ValueError(
                    "У вас уже есть заявка на вывод. Дождитесь решения администратора."
                )

            bal = await operator_balance(conn, operator_id)
            if amount > bal["available_rub"] + 0.01:
                raise ValueError(
                    f"Недостаточно на вашем балансе. Доступно: {bal['available_rub']:,.2f} ₽"
                )

            row = await conn.fetchrow(
                """
                INSERT INTO operator_payout_requests (
                    operator_id, amount_rub, requisites, status
                )
                VALUES ($1, $2, $3, 'pending')
                RETURNING *
                """,
                operator_id,
                amount,
                req,
            )
            await conn.execute(
                """
                INSERT INTO operator_payroll_ledger (
                    type, amount_rub, payout_request_id, operator_id, note
                )
                VALUES ('hold', $1, $2, $3, $4)
                """,
                -amount,
                row["id"],
                operator_id,
                f"Заявка на вывод #{row['id']}",
            )
    return dict(row)


async def process_request_paid(request_id: int, *, note: str | None = None) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            req = await conn.fetchrow(
                """
                SELECT * FROM operator_payout_requests
                WHERE id = $1 FOR UPDATE
                """,
                request_id,
            )
            if not req or req["status"] != "pending":
                return None
            amount = float(req["amount_rub"])

            await conn.execute(
                """
                DELETE FROM operator_payroll_ledger
                WHERE payout_request_id = $1 AND type = 'hold'
                """,
                request_id,
            )
            await conn.execute(
                """
                INSERT INTO operator_payroll_ledger (
                    type, amount_rub, payout_request_id, operator_id, note
                )
                VALUES ('payout', $1, $2, $3, $4)
                """,
                -amount,
                request_id,
                req["operator_id"],
                note or f"Выплата по заявке #{request_id}",
            )
            updated = await conn.fetchrow(
                """
                UPDATE operator_payout_requests
                SET status = 'paid', processed_at = now(), payout_note = $2
                WHERE id = $1
                RETURNING *
                """,
                request_id,
                note,
            )
    return dict(updated) if updated else None


async def process_request_rejected(request_id: int, *, note: str | None = None) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            req = await conn.fetchrow(
                """
                SELECT * FROM operator_payout_requests
                WHERE id = $1 FOR UPDATE
                """,
                request_id,
            )
            if not req or req["status"] != "pending":
                return None
            amount = float(req["amount_rub"])

            await conn.execute(
                """
                DELETE FROM operator_payroll_ledger
                WHERE payout_request_id = $1 AND type = 'hold'
                """,
                request_id,
            )
            await conn.execute(
                """
                INSERT INTO operator_payroll_ledger (
                    type, amount_rub, payout_request_id, operator_id, note
                )
                VALUES ('release', $1, $2, $3, $4)
                """,
                amount,
                request_id,
                req["operator_id"],
                note or f"Отклонено #{request_id}",
            )
            updated = await conn.fetchrow(
                """
                UPDATE operator_payout_requests
                SET status = 'rejected', processed_at = now(), payout_note = $2
                WHERE id = $1
                RETURNING *
                """,
                request_id,
                note,
            )
    return dict(updated) if updated else None


def format_payout_admin_message(req: dict, operator_name: str) -> str:
    req_id = req["id"]
    uname = html.escape(operator_name)
    requisites = html.escape(str(req["requisites"] or ""))
    return (
        f"👷 <b>Заявка на вывод зарплаты</b> #{req_id}\n\n"
        f"Оператор: {uname} (<code>{req['operator_id']}</code>)\n"
        f"💰 Сумма: <b>{float(req['amount_rub']):,.2f} ₽</b>\n"
        f"📝 Реквизиты:\n<code>{requisites}</code>"
    )


def payout_admin_keyboard(request_id: int) -> dict:
    from callback_signatures import sign_operator_payroll

    sig = sign_operator_payroll(request_id)
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Выплачено", "callback_data": f"opay:paid:{request_id}:{sig}"},
                {"text": "❌ Отклонить", "callback_data": f"opay:reject:{request_id}:{sig}"},
            ]
        ]
    }
