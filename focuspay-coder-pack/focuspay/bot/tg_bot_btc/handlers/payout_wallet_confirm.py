"""Вопрос клиенту перед автовыплатой: кошелёк с заявки или другой адрес."""
from __future__ import annotations

import logging
import os
import re

import aiohttp
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

logger = logging.getLogger("payout_wallet_confirm")

AWAITING_KEY = "awaiting_payout_wallet_order"
_CB = re.compile(r"^pw:(ok|new):([A-Za-z0-9]{1,32})$")
_CANCEL = frozenset({"отмена", "cancel"})

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or "").strip()


def parse_payout_wallet_callback(data: str) -> tuple[str, str] | None:
    match = _CB.fullmatch((data or "").strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def awaiting_wallet_order(user_data: dict | None) -> str | None:
    if not user_data:
        return None
    raw = str(user_data.get(AWAITING_KEY) or "").strip()
    return raw or None


def wallet_text_should_stop(user_data: dict | None) -> bool:
    return awaiting_wallet_order(user_data) is not None


async def post_wallet_decision(payload: dict) -> tuple[int, dict | None]:
    if not INTERNAL_TOKEN:
        logger.warning("payout wallet confirm skipped: INTERNAL_API_SECRET not set")
        return 503, None
    url = f"{EXCHANGE_API_URL}/api/internal/payout-wallet-confirm"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                try:
                    data = await response.json(content_type=None)
                except Exception:
                    data = None
                if not isinstance(data, dict):
                    data = None
                return response.status, data
    except Exception as exc:
        logger.warning("payout wallet confirm failed: %s", exc)
        return 0, None


def _user_text(status: int, body: dict | None, *, fallback: str) -> str:
    if status == 400 and body:
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    if status == 200 and body:
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return fallback


def _clear_wait(context: ContextTypes.DEFAULT_TYPE, order_id: str) -> None:
    if context.user_data.get(AWAITING_KEY) == order_id:
        context.user_data.pop(AWAITING_KEY, None)


async def _drop_buttons(query) -> None:
    # Пустая клавиатура снимает кнопки. None Telegram просто не присылает.
    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([]))
    except Exception:
        logger.debug("payout wallet buttons already gone", exc_info=True)


async def payout_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    parsed = parse_payout_wallet_callback(query.data or "")
    if not parsed:
        await query.answer()
        return
    kind, order_id = parsed
    user_id = int(query.from_user.id)
    action = "confirm" if kind == "ok" else "await_address"
    status, body = await post_wallet_decision(
        {"order_id": order_id, "user_id": user_id, "action": action}
    )
    if status != 200:
        await query.answer("Не получилось. Попробуйте ещё раз.", show_alert=True)
        return
    await query.answer()
    await _drop_buttons(query)
    if kind == "new" and (body or {}).get("status") == "awaiting_address":
        context.user_data[AWAITING_KEY] = order_id
    else:
        _clear_wait(context, order_id)
    text = _user_text(status, body, fallback="Отправляем на этот адрес")
    if query.message:
        await query.message.reply_text(text)


async def payout_wallet_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Личный текст перехватывается только пока ждём новый адрес."""
    if not wallet_text_should_stop(context.user_data):
        return
    message = update.message
    user = update.effective_user
    if not message or not user:
        raise ApplicationHandlerStop
    order_id = awaiting_wallet_order(context.user_data)
    raw = (message.text or "").strip()
    action = "cancel" if raw.lower() in _CANCEL else "replace"
    status, body = await post_wallet_decision(
        {
            "order_id": order_id,
            "user_id": int(user.id),
            "action": action,
            "address": raw if action == "replace" else None,
        }
    )
    if status == 200 and (body or {}).get("status") in ("confirmed", "pending", "already_sent"):
        _clear_wait(context, order_id or "")
    reply = _user_text(
        status,
        body,
        fallback="Не получилось сохранить адрес. Пришлите его ещё раз.",
    )
    await message.reply_text(reply)
    raise ApplicationHandlerStop
