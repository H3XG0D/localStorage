"""Telegram-уведомление операторам об авто-заявке без смены."""
from __future__ import annotations

import html
import logging

logger = logging.getLogger("auto_no_shift_notify")


async def notify_auto_buy_order(
    *,
    order_id: str,
    user_id: int,
    fiat_amount: float,
    crypto: str,
) -> None:
    try:
        from telegram_notify import send_admin_message

        text = (
            "<b>Авто-заявка (без смены)</b>\n"
            f"#{html.escape(order_id)} · user <code>{user_id}</code>\n"
            f"{html.escape(crypto.upper())} · {fiat_amount:,.0f} ₽"
        )
        await send_admin_message(text)
    except Exception:
        logger.warning("auto order notify failed", exc_info=True)
