"""Клиент подтверждает, что получил рубли по SELL-чеку выплаты."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from services.db import get_order, get_pool, update_order_status

logger = logging.getLogger("payout_receipt_confirm")

CALLBACK_PREFIX = "spayout:"
_SELL_CLOSE_STATUSES = ("PENDING", "AWAITING_CHECK", "COMPLETED", "OPERATOR_PENDING")


async def mark_payout_receipt_confirmed(order_id: str, user_id: int) -> str:
    """ok | already | missing | forbidden"""
    order = await get_order(order_id)
    if not order or int(order["user_id"]) != int(user_id):
        return "forbidden"
    if str(order.get("direction") or "").lower() != "sell":
        return "forbidden"
    pool = await get_pool()
    already = False
    async with pool.acquire() as conn:
        async with conn.transaction():
            alloc = await conn.fetchrow(
                """
                SELECT id, client_confirmed_at
                FROM payout_requisite_allocations
                WHERE order_id = $1 AND status = 'PAID' AND receipt_file IS NOT NULL
                ORDER BY paid_at DESC NULLS LAST, id DESC
                LIMIT 1
                FOR UPDATE
                """,
                order_id,
            )
            if not alloc:
                return "missing"
            if alloc["client_confirmed_at"] is not None:
                already = True
            else:
                await conn.execute(
                    """
                    UPDATE payout_requisite_allocations
                    SET client_confirmed_at = now(), updated_at = now()
                    WHERE id = $1 AND client_confirmed_at IS NULL
                    """,
                    int(alloc["id"]),
                )
    await close_sell_after_client_confirm(order_id, order)
    return "already" if already else "ok"


async def close_sell_after_client_confirm(order_id: str, order=None) -> None:
    """PAID + суммы с заявки. Смена оператора не нужна."""
    if order is None:
        order = await get_order(order_id)
    if not order:
        return
    status = str(order.get("status") or "").upper()
    if status == "PAID":
        return
    if status and status not in _SELL_CLOSE_STATUSES:
        logger.warning("sell close skipped order=%s status=%s", order_id, status)
        return
    ok = await update_order_status(order_id, "PAID")
    if not ok:
        logger.warning("sell PAID after receipt confirm failed order=%s", order_id)
        return
    from services.partner_tracking import schedule_partner_exchange

    schedule_partner_exchange(dict(order))
    crypto_received = float(order.get("crypto_amount") or 0)
    fiat_paid = float(order.get("fiat_amount") or 0)
    finance_id = order.get("finance_operator_id") or order.get("operator_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        alloc_amt = await conn.fetchval(
            """
            SELECT amount_rub
            FROM payout_requisite_allocations
            WHERE order_id = $1 AND status = 'PAID'
            ORDER BY paid_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            order_id,
        )
        if alloc_amt is not None:
            fiat_paid = float(alloc_amt)
        await conn.execute(
            """
            UPDATE orders
            SET operator_id = COALESCE(operator_id, $1),
                finance_operator_id = COALESCE(finance_operator_id, $1),
                operator_crypto_received = $2,
                operator_fiat_paid_out = $3,
                updated_at = now()
            WHERE order_id = $4
            """,
            int(finance_id) if finance_id is not None else None,
            crypto_received,
            fiat_paid,
            order_id,
        )
    await _try_finalize_payroll(order_id)


async def _try_finalize_payroll(order_id: str) -> None:
    backend_root = Path("/opt/exchange-backend")
    if backend_root.is_dir() and str(backend_root) not in sys.path:
        sys.path.append(str(backend_root))
    try:
        from operator_payroll_split import ensure_order_payroll_split
    except ImportError:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await ensure_order_payroll_split(conn, order_id)
    except Exception:
        logger.exception("sell payroll after client confirm order=%s", order_id)


async def payout_receipt_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    if not data.startswith(CALLBACK_PREFIX):
        return
    order_id = data[len(CALLBACK_PREFIX) :].strip()
    user = query.from_user
    if not order_id or user is None:
        await _answer(query, "Неверные данные", alert=True)
        return
    try:
        result = await mark_payout_receipt_confirmed(order_id, int(user.id))
    except Exception:
        logger.exception("payout receipt confirm failed order=%s", order_id)
        await _answer(query, "Не удалось подтвердить. Попробуйте ещё раз.", alert=True)
        return
    if result == "forbidden":
        await _answer(query, "Это не ваша заявка", alert=True)
        return
    if result == "missing":
        await _answer(query, "Чек о выплате ещё не приложен", alert=True)
        return
    await _answer(query, "Получение подтверждено")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("payout confirm markup removal failed", exc_info=True)


async def _answer(query, text: str, *, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except Exception:
        logger.debug("payout confirm answer failed", exc_info=True)
