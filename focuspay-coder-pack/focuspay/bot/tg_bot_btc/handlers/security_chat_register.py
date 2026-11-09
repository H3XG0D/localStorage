"""Регистрация Telegram-групп: «123» → операторы, /sec123 → security API."""
from __future__ import annotations

import logging
import os
import subprocess  # nosec B404

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.ops_group_store import write_ops_group_id

logger = logging.getLogger(__name__)

_SECURITY_CHAT_ID_FILE = "/opt/exchange-backend/.security_chat_id"
_APPLY_SECURITY_SCRIPT = "/opt/exchange-backend/scripts/apply_security_chat.sh"
_APPLY_OPS_SCRIPT = "/opt/tg_bot_btc/scripts/apply_ops_group.sh"


async def _register_ops_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        path = write_ops_group_id(cid)
    except OSError as e:
        logger.error("write ops group id: %s", e)
        if update.message:
            await update.message.reply_text(f"Ошибка записи chat_id: {e}")
        return

    applied = False
    if os.path.isfile(_APPLY_OPS_SCRIPT):
        try:
            subprocess.run(  # nosec B603
                ["/bin/bash", _APPLY_OPS_SCRIPT, str(cid)],
                check=True,
                timeout=30,
            )
            applied = True
        except Exception as e:
            logger.exception("apply_ops_group: %s", e)

    logger.warning(
        "TELEGRAM_OPS_GROUP_ID registered: %s title=%r file=%s applied=%s",
        cid,
        title,
        path,
        applied,
    )
    if update.message:
        msg = (
            f"✅ <b>Группа операторов</b> (заявки, чеки, «Выплачено»)\n"
            f"<code>{cid}</code> · {title}\n\n"
            f"Сюда будут приходить все ops-уведомления.\n"
            f"Отчёты владельца (/dash) остаются в админ-группе."
        )
        if applied:
            msg += "\n\n.env обновлён, бот перезапущен."
        else:
            msg += (
                f"\n\nФайл: <code>{path}</code>\n"
                "На сервере: <code>scripts/apply_ops_group.sh CHAT_ID</code>"
            )
        await update.message.reply_text(msg, parse_mode="HTML")

    try:
        await context.bot.send_message(
            chat_id=cid,
            text="🔔 Ops-уведомления подключены к этой группе.",
        )
    except Exception as e:
        logger.warning("ops group test ping failed: %s", e)


async def _register_security_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        os.makedirs(os.path.dirname(_SECURITY_CHAT_ID_FILE), exist_ok=True)
        with open(_SECURITY_CHAT_ID_FILE, "w", encoding="utf-8") as f:
            f.write(str(cid))
    except OSError as e:
        logger.error("write security chat id: %s", e)
        if update.message:
            await update.message.reply_text(f"Ошибка записи chat_id: {e}")
        return

    applied = False
    if os.path.isfile(_APPLY_SECURITY_SCRIPT):
        try:
            subprocess.run(  # nosec B603
                ["/bin/bash", _APPLY_SECURITY_SCRIPT, str(cid)],
                check=True,
                timeout=30,
            )
            applied = True
        except Exception as e:
            logger.exception("apply_security_chat: %s", e)

    logger.warning(
        "SECURITY_TELEGRAM_CHAT_ID registered: %s title=%r applied=%s",
        cid,
        title,
        applied,
    )
    if update.message:
        msg = (
            f"✅ Группа логов безопасности (SECURITY API)\n"
            f"<code>{cid}</code> · {title}\n\n"
            f"<i>Заявки операторам — текст <b>123</b> в ops-группе.</i>"
        )
        if applied:
            msg += "\n\nAPI перезапущен, security-алерты идут сюда."
        else:
            msg += "\n\nНа сервере выполните apply_security_chat.sh"
        await update.message.reply_text(msg, parse_mode="HTML")


async def security_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _register_security_chat(update, context)


async def security_chat_text_123(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if (update.message.text or "").strip() != "123":
        return
    await _register_ops_group(update, context)
