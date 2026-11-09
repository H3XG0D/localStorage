"""Единый prompt оплаты BUY: текст + ReplyKeyboard + WebApp Inline."""
from __future__ import annotations

import html
import os
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, WebAppInfo

from services.callback_signatures import sign_order
from services.payment_snapshot import order_payment_snapshot


MENU_ACTIVE_ORDER = "Активная заявка"


def webapp_requisites_enabled() -> bool:
    return (os.getenv("WEBAPP_REQUISITES") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def webapp_base_url() -> str:
    from services import config_rates

    site = (
        os.getenv("WEBAPP_URL")
        or getattr(config_rates, "PUBLIC_SITE_URL", None)
        or "https://focuspay.org"
    )
    return str(site).rstrip("/")


def requisites_webapp_url(order_id: str) -> str:
    sig = sign_order(str(order_id))
    return f"{webapp_base_url()}/webapp/?order_id={order_id}&sig={sig}"


def awaiting_payment_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["💸 Я оплатил"], ["🚫 Отмена"]], resize_keyboard=True)


def build_requisites_webapp_markup(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💳 Открыть реквизиты",
                    web_app=WebAppInfo(url=requisites_webapp_url(order_id)),
                )
            ]
        ]
    )


def _parse_snap(order: dict) -> dict:
    return order_payment_snapshot(order)


def _bill_from_order(order: dict) -> dict:
    snap = _parse_snap(order)
    bill = snap.get("bill")
    return bill if isinstance(bill, dict) else {}


def format_buy_payment_html(
    order: dict,
    *,
    title: str | None = None,
    extra_lines: list[str] | None = None,
    include_legacy_bill: bool | None = None,
) -> str:
    """Текст заявки без/с bill в зависимости от WEBAPP_REQUISITES."""
    from datetime import datetime

    from services.buyer_access_guards import format_payment_rules_block
    from services.merchant_order_id import resolve_merchant_display_id
    from services.tg_emoji import e
    from services.ux_copy import txt_order_created

    if include_legacy_bill is None:
        include_legacy_bill = not webapp_requisites_enabled()

    display_id = html.escape(resolve_merchant_display_id(dict(order)))
    crypto = str(order.get("crypto") or "?").upper()
    fiat = float(order.get("fiat_amount") or 0)
    crypto_amt = order.get("crypto_amount")
    receive_line = None
    if crypto_amt is not None:
        try:
            amt = f"{float(crypto_amt):.8f}".rstrip("0").rstrip(".")
            receive_line = (
                f"{e('obmen')} Вы получите: ~<b>{amt}</b> {html.escape(crypto)}"
            )
        except (TypeError, ValueError):
            receive_line = (
                f"{e('obmen')} Вы получите: ~<b>{html.escape(str(crypto_amt))}</b> "
                f"{html.escape(crypto)}"
            )

    if include_legacy_bill:
        bill = _bill_from_order(order)
        if bill:
            requisites_block = (
                f"{e('card')} <b>Реквизиты:</b>\n"
                f"Банк: {html.escape(str(bill.get('bank') or '—'))}\n"
                f"Получатель: <code>{html.escape(str(bill.get('reciver') or '—'))}</code>\n"
                f"ФИО: {html.escape(str(bill.get('fio') or '—'))}"
            )
        else:
            requisites_block = f"{e('info')} Реквизиты появятся в следующем сообщении."
    else:
        requisites_block = (
            f"{e('card')} Реквизиты — по кнопке <b>«Открыть реквизиты»</b> ниже "
            f"(или «Активная заявка» в главном меню)."
        )

    requisites_expires_at = order.get("expires_at")
    if isinstance(requisites_expires_at, str):
        try:
            requisites_expires_at = datetime.fromisoformat(
                requisites_expires_at.replace("Z", "+00:00")
            )
        except ValueError:
            requisites_expires_at = None
    if not isinstance(requisites_expires_at, datetime):
        requisites_expires_at = None

    return txt_order_created(
        display_id=display_id,
        fiat=fiat,
        receive_line=receive_line,
        requisites_block=requisites_block,
        rules_block=format_payment_rules_block(requisites_expires_at),
        title=title,
        extra_lines=extra_lines,
    )


def payment_markups_for_order(order: dict) -> tuple[ReplyKeyboardMarkup, InlineKeyboardMarkup | None]:
    reply = awaiting_payment_keyboard()
    if webapp_requisites_enabled():
        return reply, build_requisites_webapp_markup(str(order["order_id"]))
    return reply, None


async def send_buy_payment_prompt(
    bot_or_msg,
    order: dict,
    *,
    title: str | None = None,
    extra_lines: list[str] | None = None,
    chat_id: int | None = None,
) -> None:
    """
    bot_or_msg: Message (has reply_text) или Bot (needs chat_id).
    Шлёт текст + reply KB; если webapp — отдельно inline с WebApp.
    """
    text = format_buy_payment_html(
        order, title=title, extra_lines=extra_lines
    )
    reply_kb, inline_kb = payment_markups_for_order(order)

    if hasattr(bot_or_msg, "reply_text"):
        await bot_or_msg.reply_text(text, parse_mode="HTML", reply_markup=reply_kb)
        if inline_kb:
            await bot_or_msg.reply_text(
                "⬇️ Откройте реквизиты:",
                reply_markup=inline_kb,
            )
        return

    if chat_id is None:
        raise ValueError("chat_id required when sending via bot")
    await bot_or_msg.send_message(
        chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_kb
    )
    if inline_kb:
        await bot_or_msg.send_message(
            chat_id=chat_id,
            text="⬇️ Откройте реквизиты:",
            reply_markup=inline_kb,
        )


def order_requisites_revealed(order: dict) -> bool:
    snap = _parse_snap(order)
    return bool(snap.get("requisites_revealed_at"))
