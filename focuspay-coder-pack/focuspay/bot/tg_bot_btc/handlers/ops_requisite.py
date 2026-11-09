"""«сбп 5400» в ops-группе: реквизит у реки-бота, без внештатной сделки."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from handlers.telegram_errors import answer_callback_safe
from services.config_rates import is_ops_group_chat
from services.manual_requisite_issue import (
    cancel_issued_reki,
    format_canceled,
    format_issued,
    issue_from_reki_bot,
)
from services.ops_requisite_parse import parse_requisite_command

logger = logging.getLogger("ops_requisite")

OPS_REQ_CB_PREFIX = "opsreq:"
OPS_REQ_CANCEL_PREFIX = "opsreq:x:"
_SEARCHING_TEXT = "🔎 Ищу реквизит…"


async def _is_bound_operator(telegram_user_id: int) -> bool:
    """Личка — только привязанным через /ops_bind операторам."""
    from services.db import get_pool

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM operator_accounts
                WHERE telegram_user_id = $1 AND is_active = TRUE
                """,
                int(telegram_user_id),
            )
    except Exception:
        logger.warning("operator lookup failed tg=%s", telegram_user_id, exc_info=True)
        return False
    return row is not None


async def _allowed(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    if is_ops_group_chat(chat.id):
        return True
    if chat.type == "private":
        return await _is_bound_operator(user.id)
    return False


def cancel_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отменить", callback_data=f"{OPS_REQ_CANCEL_PREFIX}{code}")]]
    )


async def ops_requisite_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message or update.effective_message
    if not msg or not msg.text:
        return
    parsed = parse_requisite_command(msg.text)
    if not parsed:
        return
    if not await _allowed(update):
        return

    amount_rub = float(parsed["amount_rub"])
    sub_token = str(parsed["sub_token"])
    wait = await msg.reply_text(_SEARCHING_TEXT)
    user = update.effective_user
    result = await issue_from_reki_bot(
        amount_rub=amount_rub,
        sub_token=sub_token,
        operator_tg_id=user.id if user else None,
    )
    if not result.ok or not result.code:
        await _edit_or_reply(msg, wait, result.reason or "Реквизит не выдан.")
        return
    await _edit_or_reply(
        msg,
        wait,
        format_issued(result.code, result.source, sub_token, result.pay_rub, result.bill or {}),
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_keyboard(result.code),
    )


async def _edit_or_reply(msg, wait, text: str, **kwargs) -> None:
    try:
        await wait.edit_text(text, **kwargs)
    except Exception:
        logger.warning("requisite message edit failed", exc_info=True)
        await msg.reply_text(text, **kwargs)


async def ops_requisite_callback(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    if not await _allowed(update):
        await answer_callback_safe(query)
        return
    if not query.data.startswith(OPS_REQ_CANCEL_PREFIX):
        await answer_callback_safe(query, "Напишите сумму заново, например «сбп 5400».")
        return

    from services.manual_requisite import get_ticket

    code = query.data[len(OPS_REQ_CANCEL_PREFIX):]
    ticket = await get_ticket(code)
    ok, notice = await cancel_issued_reki(ticket)
    await answer_callback_safe(query, notice)
    if not query.message:
        return
    if ok:
        try:
            await query.message.edit_text(
                format_canceled(ticket.code if ticket else code),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([]),
            )
        except Exception:
            logger.warning("cancel edit failed code=%s", code, exc_info=True)
        return
    try:
        await query.message.reply_text(notice)
    except Exception:
        logger.warning("cancel notice failed code=%s", code, exc_info=True)
