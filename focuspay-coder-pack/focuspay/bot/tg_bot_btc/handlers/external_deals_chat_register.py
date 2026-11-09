"""Регистрация Telegram-группы внештатных заявок: /external."""
from __future__ import annotations

import logging
import os
import subprocess  # nosec B404

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.external_deals_group_store import write_external_deals_group_id

logger = logging.getLogger(__name__)

_APPLY_EXTERNAL_DEALS_SCRIPT = "/opt/tg_bot_btc/scripts/apply_external_deals_group.sh"


async def register_external_deals_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        if update.message:
            await update.message.reply_text("Команда только для группы с ботом.")
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        return

    cid = chat.id
    title = chat.title or ""
    try:
        path = write_external_deals_group_id(cid)
    except OSError as e:
        logger.error("write external deals group id: %s", e)
        if update.message:
            await update.message.reply_text(f"Ошибка записи chat_id: {e}")
        return

    applied = False
    if os.path.isfile(_APPLY_EXTERNAL_DEALS_SCRIPT):
        try:
            subprocess.run(  # nosec B603
                ["/bin/bash", _APPLY_EXTERNAL_DEALS_SCRIPT, str(cid)],
                check=True,
                timeout=30,
            )
            applied = True
        except Exception as e:
            logger.exception("apply_external_deals_group: %s", e)

    logger.warning(
        "TELEGRAM_EXTERNAL_DEALS_GROUP_ID registered: %s title=%r file=%s applied=%s",
        cid,
        title,
        path,
        applied,
    )
    if update.message:
        msg = (
            f"✅ <b>Группа внештатных заявок</b>\n"
            f"<code>{cid}</code> · {title}\n\n"
            f"Сюда будут приходить appeals по сделкам кабинета внештатника.\n"
            f"Обычные заявки бота остаются в ops-группе."
        )
        if applied:
            msg += "\n\n.env обновлён, бот перезапущен."
        else:
            msg += (
                f"\n\nФайл: <code>{path}</code>\n"
                "На сервере: <code>scripts/apply_external_deals_group.sh CHAT_ID</code>"
            )
        await update.message.reply_text(msg, parse_mode="HTML")

    try:
        await context.bot.send_message(
            chat_id=cid,
            text="🔔 Уведомления по внештатным заявкам подключены к этой группе.",
        )
    except Exception as e:
        logger.warning("external deals group test ping failed: %s", e)
