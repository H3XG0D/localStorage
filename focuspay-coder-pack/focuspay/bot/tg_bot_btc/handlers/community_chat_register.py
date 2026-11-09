"""Привязка focus чата для автоприёма заявок на вступление."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.community_chat_store import write_community_chat_id
from services.community_join_sync import (
    decline_community_join_requests,
    sync_community_join_requests,
)
from services.config_rates import TELEGRAM_ADMIN_IDS, community_chat_id

logger = logging.getLogger("community_chat_register")


async def register_community_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Команда только для группы с ботом.")
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text(
            "Только админ может привязать чат. Используйте /community в focus чате."
        )
        return

    try:
        path = write_community_chat_id(chat.id)
    except OSError as e:
        logger.error("write community chat id: %s", e)
        await update.message.reply_text(f"Ошибка записи chat_id: {e}")
        return

    title = chat.title or ""
    sync_note = ""
    try:
        sync = await sync_community_join_requests(context.bot, chat_id=chat.id)
        if sync.approved:
            sync_note = f"\n\n🔄 Висящие заявки: одобрено <b>{sync.approved}</b>."
        else:
            sync_note = (
                f"\n\n🔄 Проверено пользователей: {sync.checked}. "
                "Висящих заявок среди них не найдено."
            )
    except Exception as e:
        logger.warning("community sync after register failed: %s", e)
        sync_note = f"\n\n⚠️ Синхронизация висящих заявок не удалась: {e}"

    await update.message.reply_text(
        f"✅ <b>Focus чат привязан</b>\n"
        f"<code>{chat.id}</code> · {title}\n\n"
        "Заявки на вступление: пропускаем только тех, кто нажимал /start в боте.\n"
        f"Файл: <code>{path}</code>"
        f"{sync_note}",
        parse_mode="HTML",
    )
    logger.info(
        "community chat registered chat_id=%s title=%r file=%s",
        chat.id,
        title,
        path,
    )


async def sync_community_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Принудительно обработать висящие заявки (approve/decline по bot_users)."""
    if not update.effective_user or not update.message:
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("Только админ.")
        return

    gid = community_chat_id()
    if not gid:
        await update.message.reply_text(
            "Чат не привязан. Сначала /community в focus чате."
        )
        return

    await update.message.reply_text("⏳ Синхронизация висящих заявок…")
    try:
        sync = await sync_community_join_requests(context.bot, chat_id=gid)
    except Exception as e:
        logger.exception("community sync failed")
        await update.message.reply_text(f"Ошибка синхронизации: {e}")
        return

    await update.message.reply_text(
        "✅ <b>Синхронизация завершена</b>\n"
        f"Проверено: {sync.checked}\n"
        f"Одобрено: {sync.approved}\n"
        f"Лимит каналов: {sync.channels_blocked}\n"
        f"Без заявки: {sync.skipped}\n"
        f"Ошибок: {sync.errors}",
        parse_mode="HTML",
    )


async def decline_community_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Отклонить висящие заявки по user_id из списка в команде."""
    if not update.effective_user or not update.message:
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("Только админ.")
        return

    gid = community_chat_id()
    if not gid:
        await update.message.reply_text("Чат не привязан. Сначала /community в focus чате.")
        return

    raw = (update.message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        await update.message.reply_text(
            "Формат: <code>/community_decline 123456789 987654321</code>\n"
            "user_id можно скопировать из списка заявок в Telegram.",
            parse_mode="HTML",
        )
        return

    user_ids: list[int] = []
    for part in raw[1].replace(",", " ").split():
        try:
            user_ids.append(int(part))
        except ValueError:
            continue
    if not user_ids:
        await update.message.reply_text("Не найдено ни одного user_id.")
        return

    declined, errors = await decline_community_join_requests(
        context.bot, chat_id=gid, user_ids=user_ids
    )
    await update.message.reply_text(
        f"Отклонено: {declined}\nОшибок: {errors}",
    )
