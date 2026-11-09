"""Авто-уведомление клиента о BUY PAID: Business-чат + web-чат."""
from __future__ import annotations

import logging

from db import get_pool

logger = logging.getLogger("buyer_payout_notify")


def _bot_payout_utils():
    import os
    import sys

    root = os.environ.get("TG_BOT_PATH", "/opt/tg_bot_btc")
    if root not in sys.path:
        sys.path.insert(0, root)
    from services.buy_payout import build_explorer_url, format_paid_chat_message

    return build_explorer_url, format_paid_chat_message


def payout_explorer_url(order: dict, *, explorer_url: str | None = None) -> str:
    explicit = (explorer_url or "").strip()
    if explicit:
        return explicit
    tx = str(order.get("payout_tx_hash") or "").strip()
    if not tx:
        return ""
    build_explorer_url, _ = _bot_payout_utils()
    return build_explorer_url(str(order.get("crypto") or ""), tx)


async def _find_thread(conn, *, user_id: int, order_id: str) -> dict | None:
    row = None
    if user_id > 0:
        row = await conn.fetchrow(
            """
            SELECT * FROM web_chat_threads
            WHERE telegram_user_id = $1
            ORDER BY last_message_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            user_id,
        )
    if not row and order_id:
        row = await conn.fetchrow(
            """
            SELECT * FROM web_chat_threads
            WHERE order_id = $1
            ORDER BY last_message_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            order_id,
        )
    return dict(row) if row else None


async def deliver_buy_payout_chat_message(
    order: dict,
    *,
    explorer_url: str | None = None,
) -> bool:
    """Отправить ссылку на транзакцию в переписку с оператором."""
    order_id = str(order.get("order_id") or "").strip()
    user_id = int(order.get("user_id") or 0)
    if not order_id:
        return False

    url = payout_explorer_url(order, explorer_url=explorer_url)
    if not url:
        logger.info("buy payout chat notify skipped order=%s: no tx url", order_id)
        return False

    _, format_paid_chat_message = _bot_payout_utils()
    cashback = {"applied": 0.0, "accrued": 0.0, "overpay_credit": 0.0}
    try:
        from bot_status_bridge import _bot_db

        if _bot_db is not None:
            from services.buy_payout import order_cashback_notify_info

            cashback = await order_cashback_notify_info(order)
    except Exception:
        logger.debug("buy payout chat cashback lookup failed order=%s", order_id, exc_info=True)

    text = format_paid_chat_message(
        order,
        url,
        cashback_applied=float(cashback.get("applied") or 0),
        cashback_accrued=float(cashback.get("accrued") or 0),
        overpay_credit=float(cashback.get("overpay_credit") or 0),
    )

    pool = await get_pool()
    thread_id: int | None = None
    async with pool.acquire() as conn:
        thread = await _find_thread(conn, user_id=user_id, order_id=order_id)
        if thread:
            thread_id = int(thread["id"])
            if order_id and not thread.get("order_id"):
                await conn.execute(
                    "UPDATE web_chat_threads SET order_id = $1, updated_at = now() WHERE id = $2",
                    order_id,
                    thread_id,
                )

    if thread_id is None:
        if user_id <= 0:
            logger.info("buy payout chat notify skipped order=%s: no thread", order_id)
            return False
        from chat_service import get_or_create_thread

        thread = await get_or_create_thread(
            session_token=None,
            telegram_user_id=user_id,
            order_id=order_id,
        )
        thread_id = int(thread["id"])

    from chat_service import admin_send_message

    await admin_send_message(thread_id, text, admin_user_id=None)
    logger.info("buy payout chat notify delivered order=%s thread=%s", order_id, thread_id)
    return True


async def recent_payout_sent(user_id: int) -> dict | None:
    """Свежая выплата покупки, чтобы показать «Выплачено» на сайте и в мини-приложении."""
    if int(user_id) <= 0:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT order_id, crypto, crypto_amount, fiat_amount, requisites, payout_tx_hash
            FROM orders
            WHERE user_id = $1
              AND lower(direction) = 'buy'
              AND status = 'PAID'
              AND COALESCE(btrim(payout_tx_hash), '') <> ''
              AND COALESCE(payout_confirmed_at, updated_at) >= now() - interval '6 hours'
            ORDER BY COALESCE(payout_confirmed_at, updated_at) DESC
            LIMIT 1
            """,
            int(user_id),
        )
    if not row:
        return None
    from payout_track import explorer_url, payout_coin

    crypto = str(row["crypto"] or "")
    txid = str(row["payout_tx_hash"] or "").strip()
    amount = row["crypto_amount"]
    fiat = row["fiat_amount"]
    return {
        "order_id": str(row["order_id"]),
        "coin": payout_coin(crypto).upper(),
        "crypto_amount": float(amount) if amount is not None else None,
        "fiat_amount": float(fiat) if fiat is not None else None,
        "address": str(row["requisites"] or ""),
        "txid": txid,
        "explorer_url": explorer_url(crypto, txid),
    }
