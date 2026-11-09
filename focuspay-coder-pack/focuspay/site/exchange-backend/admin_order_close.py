"""Гейты закрытия AWAITING_CHECK из админки (без расширения generic-машины)."""
from __future__ import annotations

import html


def admin_cancel_awaiting_check_error(status: str | None) -> str | None:
    """None — можно отменять. already_canceled — идемпотентный успех."""
    st = str(status or "").upper()
    if st == "CANCELED":
        return "already_canceled"
    if st in ("PAID", "COMPLETED"):
        return "already_closed"
    if st != "AWAITING_CHECK":
        return "wrong_status"
    return None


def admin_awaiting_check_payout_error(
    direction: str | None,
    status: str | None,
) -> str | None:
    """Гейт dedicated BUY AWAITING_CHECK → PAID. already_paid обрабатывается с hash в боте."""
    if (direction or "").lower() != "buy":
        return "not_buy"
    st = str(status or "").upper()
    if st == "PAID":
        return "already_paid"
    if st != "AWAITING_CHECK":
        return "wrong_status"
    return None


def cancel_user_telegram_text(order_id: str, reason: str) -> str:
    oid = html.escape(str(order_id))
    rsn = html.escape(reason)
    return (
        "❌ <b>Заявка отменена</b>\n\n"
        f"🆔 Заявка: <code>{oid}</code>\n"
        f"📝 Причина: {rsn}\n\n"
        "Если актуально — пересоздайте заявку или напишите оператору @focus_operator."
    )
