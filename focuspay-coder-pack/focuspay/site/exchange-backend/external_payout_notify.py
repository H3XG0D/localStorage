"""Уведомления о заявках на вывод внештатников."""
from __future__ import annotations

import html
import re

from callback_signatures import sign_external_payout
from config import settings
from telegram_notify import send_admin_message, send_ops_message

_WALLET_RE = re.compile(r"Кошелёк:\s*(.+)", re.IGNORECASE)


def wallet_from_note(note: str | None) -> str:
    if not note:
        return ""
    m = _WALLET_RE.search(note)
    if m:
        return m.group(1).strip()
    return note.strip()


def btc_amount_from_usd(net_usd: float, market_rub: dict[str, float]) -> float | None:
    usdt_rub = float(market_rub.get("usdt") or 0)
    btc_rub = float(market_rub.get("btc") or 0)
    if usdt_rub <= 0 or btc_rub <= 0:
        return None
    btc_usd = btc_rub / usdt_rub
    if btc_usd <= 0:
        return None
    return round(float(net_usd) / btc_usd, 8)


def external_payout_admin_keyboard(payout_id: int) -> dict:
    sig = sign_external_payout(payout_id)
    site = settings.public_site_url.rstrip("/")
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🌐 Админка",
                    "url": f"{site}/x8/external",
                },
            ],
            [
                {
                    "text": "✅ Пропустить",
                    "callback_data": f"extwd:skip:{payout_id}:{sig}",
                },
                {
                    "text": "📎 Прикрепить чек",
                    "callback_data": f"extwd:receipt:{payout_id}:{sig}",
                },
                {
                    "text": "❌ Отклонить",
                    "callback_data": f"extwd:reject:{payout_id}:{sig}",
                },
            ],
        ]
    }


def format_external_payout_admin_message(
    payout: dict,
    *,
    exchanger_name: str | None,
    username: str | None,
    market_rub: dict[str, float] | None = None,
) -> str:
    name = html.escape(str(exchanger_name or "внештатник"))
    uname = html.escape(str(username or "").lstrip("@"))
    who = f"{name}" + (f" · @{uname}" if uname else "")
    wallet = html.escape(wallet_from_note(payout.get("note")))
    crypto = str(payout.get("crypto") or "usdt").upper()
    crypto_amount = float(payout.get("crypto_amount") or 0)
    gross = float(payout.get("gross_usd") or 0)
    fee = float(payout.get("fee_usd") or 0)
    net = float(payout.get("net_usd") or 0)
    site = settings.public_site_url.rstrip("/")

    lines = [
        f"💸 <b>Внештат · заявка на вывод</b> #{int(payout['id'])}",
        f"👤 {who}",
        f"💰 Списание: <b>${gross:,.2f}</b> · комиссия ${fee:,.2f} · на руки <b>${net:,.2f}</b>",
        f"🪙 Выплата: <b>{crypto_amount:.6f} {crypto}</b>",
    ]

    if crypto == "BTC":
        lines.append(f"₿ К отправке: <b>{crypto_amount:.8f} BTC</b>")
    elif market_rub:
        btc_amt = btc_amount_from_usd(net, market_rub)
        if btc_amt is not None:
            lines.append(f"₿ К отправке: <b>{btc_amt:.8f} BTC</b>")

    if wallet:
        lines.append(f"👛 Кошелёк:\n<code>{wallet}</code>")

    lines.append(f'🌐 <a href="{site}/x8/external">Админка · внештат</a>')
    return "\n".join(lines)


async def notify_admin_external_payout_requested(
    payout: dict,
    *,
    exchanger_name: str | None,
    username: str | None,
    market_rub: dict[str, float] | None = None,
) -> int | None:
    chat_id = settings.reports_telegram_group_id()
    if not chat_id:
        return None
    text = format_external_payout_admin_message(
        payout,
        exchanger_name=exchanger_name,
        username=username,
        market_rub=market_rub,
    )
    return await send_admin_message(
        text,
        chat_id=chat_id,
        reply_markup=external_payout_admin_keyboard(int(payout["id"])),
    )


async def notify_ops_external_deals(text: str) -> None:
    from external_deals_telegram import external_deals_chat

    chat_id, topic_id = external_deals_chat()
    if not chat_id or not settings.telegram_bot_token:
        return
    try:
        await send_ops_message(text, chat_id=chat_id, message_thread_id=topic_id)
    except Exception:
        return
