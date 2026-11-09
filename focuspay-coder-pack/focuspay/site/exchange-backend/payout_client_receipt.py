"""Чек выплаты по SELL: пересылка клиенту и подтверждение получения."""
from __future__ import annotations

import html
import logging

from fastapi import HTTPException

from payout_requisite_receipts import receipt_disk_path

logger = logging.getLogger(__name__)

CONFIRM_CALLBACK_PREFIX = "spayout:"


def sell_payout_caption(order: dict) -> str:
    oid = html.escape(str(order.get("order_id") or ""))
    fiat = order.get("fiat_amount")
    crypto = html.escape(str(order.get("crypto") or "").upper())
    crypto_amt = order.get("crypto_amount")
    fiat_s = f"{float(fiat):,.0f}".replace(",", " ") if fiat is not None else "—"
    crypto_s = f"{float(crypto_amt):g}" if crypto_amt is not None else "—"
    return (
        "✅ <b>Выплата отправлена</b>\n\n"
        f"🆔 Заявка: <code>{oid}</code>\n"
        f"💎 Вы отдали: <b>{crypto_s}</b> {crypto}\n"
        f"💵 Выплата: <b>{fiat_s}</b> ₽\n\n"
        "Чек о переводе во вложении. Нажмите кнопку, когда деньги придут."
    )


def payout_receipt_keyboard(order_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "Подтвердить получение",
                    "callback_data": f"{CONFIRM_CALLBACK_PREFIX}{order_id}",
                }
            ]
        ]
    }


async def payout_receipt_state(order_id: str) -> tuple[bool, bool]:
    """(есть файл чека, клиент подтвердил)."""
    from db import get_pool

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT receipt_file, client_confirmed_at
                FROM payout_requisite_allocations
                WHERE order_id = $1 AND status = 'PAID' AND receipt_file IS NOT NULL
                ORDER BY paid_at DESC NULLS LAST, id DESC
                LIMIT 1
                """,
                order_id,
            )
    except Exception:
        logger.debug("payout receipt state unreadable", exc_info=True)
        return False, False
    if not row:
        return False, False
    return True, row["client_confirmed_at"] is not None


async def deliver_payout_receipt_to_client(
    order: dict,
    receipt_file: str | None,
) -> bool:
    """Отправить чек в Telegram. False — нет чата, файла или API не принял."""
    user_id = int(order.get("user_id") or 0)
    if user_id <= 0 or not receipt_file:
        return False
    path = receipt_disk_path(receipt_file)
    if path is None:
        logger.warning("payout receipt missing on disk order=%s file=%s", order.get("order_id"), receipt_file)
        return False
    from telegram_notify import send_user_document

    message_id = await send_user_document(
        user_id,
        str(path),
        sell_payout_caption(order),
        reply_markup=payout_receipt_keyboard(str(order.get("order_id") or "")),
    )
    return bool(message_id)


SELL_CLOSE_STATUSES = ("PENDING", "AWAITING_CHECK", "COMPLETED", "OPERATOR_PENDING")


def _row_get(row, key):
    try:
        return row[key]
    except Exception:
        return None


async def close_sell_after_client_confirm(order_id: str) -> dict:
    """Закрыть SELL в PAID после подтверждения рублей клиентом. Смена не нужна."""
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
        if not order:
            return {"ok": False, "reason": "missing"}
        if str(_row_get(order, "direction") or "").lower() != "sell":
            return {"ok": False, "reason": "not_sell"}
        status = str(_row_get(order, "status") or "").upper()
        if status == "PAID":
            return {"ok": True, "already_paid": True, "order": dict(order)}
        if status not in SELL_CLOSE_STATUSES:
            logger.warning("sell close skipped order=%s status=%s", order_id, status)
            return {"ok": False, "reason": "bad_status", "order": dict(order)}
        alloc = await conn.fetchrow(
            """
            SELECT amount_rub
            FROM payout_requisite_allocations
            WHERE order_id = $1 AND status = 'PAID'
            ORDER BY paid_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            order_id,
        )
        crypto_received = float(_row_get(order, "crypto_amount") or 0)
        fiat_raw = _row_get(alloc, "amount_rub") if alloc else _row_get(order, "fiat_amount")
        fiat_paid_out = float(fiat_raw or 0)
        finance_id = _row_get(order, "finance_operator_id") or _row_get(order, "operator_id")

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, "PAID"):
        logger.warning("sell close status bridge failed order=%s", order_id)
        return {"ok": False, "reason": "status"}

    finance_param = int(finance_id) if finance_id is not None else None
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            """
            UPDATE orders
            SET operator_id = COALESCE(operator_id, $1),
                finance_operator_id = COALESCE(finance_operator_id, $1),
                operator_crypto_received = $2,
                operator_fiat_paid_out = $3,
                updated_at = now()
            WHERE order_id = $4
            RETURNING *
            """,
            finance_param,
            crypto_received,
            fiat_paid_out,
            order_id,
        )

    try:
        from operator_payroll_split import ensure_order_payroll_split

        async with pool.acquire() as conn:
            async with conn.transaction():
                await ensure_order_payroll_split(conn, order_id)
    except Exception:
        logger.exception("sell payroll after client confirm order=%s", order_id)

    order_dict = dict(updated or order)
    try:
        from bot_status_bridge import notify_order_completed_for_user

        await notify_order_completed_for_user(order_dict)
    except Exception as exc:
        logger.warning("notify sell close order=%s: %s", order_id, exc)
    return {"ok": True, "already_paid": False, "order": order_dict}


async def confirm_payout_receipt(order_id: str, user_id: int) -> dict:
    from db import get_pool

    pool = await get_pool()
    already = False
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT order_id, user_id, direction FROM orders WHERE order_id = $1 FOR UPDATE",
                order_id,
            )
            if not order or int(order["user_id"]) != int(user_id):
                raise HTTPException(status_code=404, detail="Order not found")
            if str(order["direction"] or "").lower() != "sell":
                raise HTTPException(status_code=400, detail="Подтверждение получения только по продаже")
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
                raise HTTPException(status_code=409, detail="Чек о выплате ещё не приложен")
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
    closed = await close_sell_after_client_confirm(order_id)
    return {
        "ok": True,
        "already_confirmed": already,
        "order": closed.get("order"),
        "closed": bool(closed.get("ok")),
    }
