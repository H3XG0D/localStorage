"""Ops-уведомления в админ-группу (сайт/API)."""
from __future__ import annotations

import html
import logging
from typing import Any

from config import settings
from telegram_notify import send_admin_message

logger = logging.getLogger("order_ops_notify")

_OPS_CRYPTO_DECIMALS = {"btc": 8, "ltc": 8, "usdt": 2, "trx": 2}


def format_ops_crypto_amount(amount, crypto: str) -> str:
    base = str(crypto or "").split("_")[0].lower()
    dec = _OPS_CRYPTO_DECIMALS.get(base, 6)
    return f"{float(amount):.{dec}f}"


EVENT_TITLES = {
    "created": "🆕 Создан обмен",
    "awaiting_receipt": "📎 Ожидает чек от клиента",
    "receipt_attached": "📤 Чек отправлен мерчанту",
    "awaiting_confirmation": "⏳ Ожидает подтверждения оплаты",
    "merchant_confirmed": "✅ Мерчант подтвердил оплату",
    "awaiting_payout": "✅ Мерчант подтвердил оплату",
    "paid": "✅ Выплачено",
}


def _site() -> str:
    return (settings.public_site_url or "https://focuspay.org").rstrip("/")


def _operator_url(path: str = "/ops/login") -> str:
    return f"{_site()}{path}"


def _keyboard(
    order_id: str,
    *,
    pay_signature: str | None = None,
    sell: bool = False,
) -> dict:
    rows: list[list[dict]] = [
        [
            {"text": "👁 Кабинет оператора", "url": _operator_url("/ops/login")},
            {"text": "📋 Заявки", "url": _operator_url("/ops/orders")},
        ],
        [
            {
                "text": "🔍 Заявка",
                "url": _operator_url(f"/ops/orders?q={order_id}"),
            }
        ],
    ]
    if pay_signature:
        if sell:
            rows.append(
                [
                    {
                        "text": "✅ Крипта получена",
                        "callback_data": f"pay:{order_id}:{pay_signature}",
                    },
                    {
                        "text": "❌ Не поступила",
                        "callback_data": f"cancel:{order_id}:{pay_signature}",
                    },
                ]
            )
        else:
            rows.append(
                [
                    {
                        "text": "✅ Выплачено",
                        "callback_data": f"pay:{order_id}:{pay_signature}",
                    },
                    {
                        "text": "❌ Отменить",
                        "callback_data": f"cancel:{order_id}:{pay_signature}",
                    },
                ]
            )
    return {"inline_keyboard": rows}


def _format(event: str, order: dict[str, Any], *, note: str | None = None) -> str:
    from merchant_order_id import format_ops_order_id_html

    title = EVENT_TITLES.get(event, "📋 Заявка")
    direction = html.escape(str(order.get("direction", "buy")).upper())
    status = html.escape(str(order.get("status", "")))
    crypto = html.escape(str(order.get("crypto", "")))
    fiat = order.get("fiat_amount")
    crypto_amt = order.get("crypto_amount")
    uid = order.get("user_id")

    lines = [
        f"<b>{title}</b> · {direction}",
        "",
        format_ops_order_id_html(order),
        f"👤 <code>{uid}</code>",
    ]
    if fiat is not None:
        line = f"💰 <b>{float(fiat):,.0f} ₽</b>".replace(",", " ")
        if crypto_amt is not None:
            line += f" · {format_ops_crypto_amount(crypto_amt, crypto)} {crypto}"
        lines.append(line)
    if status:
        lines.append(f"📊 {status}")
    if str(order.get("direction", "buy")).lower() == "buy":
        wallet = (order.get("wallet_address") or order.get("requisites") or "").strip()
        if wallet:
            lines.append(f"📬 Кошелёк: <code>{html.escape(wallet)}</code>")
    elif str(order.get("direction", "buy")).lower() == "sell":
        payout = (order.get("requisites") or "").strip()
        if payout:
            lines.append(f"📬 Выплата ₽: <code>{html.escape(payout)}</code>")
    if note:
        lines.append(html.escape(note))
    return "\n".join(lines)


async def notify_ops_order(
    event: str,
    order: dict[str, Any],
    *,
    note: str | None = None,
    pay_signature: str | None = None,
    sell: bool = False,
) -> None:
    oid = str(order.get("order_id", ""))
    if not oid:
        return
    await send_admin_message(
        _format(event, order, note=note),
        reply_markup=_keyboard(oid, pay_signature=pay_signature, sell=sell),
    )
