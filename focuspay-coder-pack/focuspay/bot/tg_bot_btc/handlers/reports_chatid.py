"""Диагностика: узнать chat_id группы для .env."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from services import config_rates


async def reports_chatid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    if user_id not in config_rates.TELEGRAM_ADMIN_IDS:
        return
    chat = update.effective_chat
    cid = chat.id
    alt = config_rates._supergroup_alt_id(cid)
    lines = [
        f"🆔 <b>chat_id этой группы:</b> <code>{cid}</code>",
        f"Тип: <code>{chat.type}</code>",
    ]
    if chat.title:
        lines.append(f"Название: {chat.title}")
    if alt is not None:
        lines.append(f"Если станет супергруппой: <code>{alt}</code>")
    ops_id = config_rates.ops_group_id()
    if ops_id:
        ok_ops = config_rates.is_ops_group_chat(cid)
        lines.append(
            f"\n<b>Операторы (чеки, заявки):</b> <code>TELEGRAM_OPS_GROUP_ID={ops_id}</code> — "
            + ("✅ эта группа" if ok_ops else "❌ другая группа")
        )
    reports_id = config_rates.reports_group_id()
    if reports_id:
        ok_rep = config_rates.is_reports_group_chat(cid)
        lines.append(
            f"<b>Отчёты владельца (/dash):</b> <code>TELEGRAM_REPORTS_GROUP_ID={reports_id}</code> — "
            + ("✅ эта группа" if ok_rep else "❌ другая группа")
        )
    external_id = config_rates.external_deals_group_id()
    if external_id:
        ok_ext = config_rates.is_external_deals_group_chat(cid)
        lines.append(
            f"<b>Внештатные заявки:</b> <code>TELEGRAM_EXTERNAL_DEALS_GROUP_ID={external_id}</code> — "
            + ("✅ эта группа" if ok_ext else "❌ другая группа")
        )
    lines.append("\nПропишите ID в .env и перезапустите бота.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
