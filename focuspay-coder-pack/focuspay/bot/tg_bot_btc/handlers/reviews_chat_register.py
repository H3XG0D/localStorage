"""Привязка канала отзывов FocusPay для автоприёма заявок на вступление."""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS, is_reviews_chat, reviews_chat_id
from services.reviews_chat_store import write_reviews_chat_id
from services.reviews_join_sync import (
    decline_reviews_join_requests,
    sync_reviews_join_requests,
)

logger = logging.getLogger("reviews_chat_register")

_ALLOWED_CHAT_TYPES = frozenset({"group", "supergroup", "channel"})
_REVIEWS_TRIGGER_RE = re.compile(r"^/?(reviews|отзывы)(?:@\w+)?$", re.IGNORECASE)


def _is_admin_user(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return int(user_id) in set(int(x) for x in TELEGRAM_ADMIN_IDS)


def _reply_target(update: Update):
    return update.effective_message


async def register_reviews_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = _reply_target(update)
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not msg:
        return

    if chat.type not in _ALLOWED_CHAT_TYPES:
        await msg.reply_text("Команда только для группы или канала с ботом.")
        return

    if user is None:
        if chat.type != "channel" or not is_reviews_chat(
            chat.id, username=getattr(chat, "username", None)
        ):
            await msg.reply_text(
                "Не удалось определить админа. Привязка из канала — только для @focuspayr "
                "или после /reviews от админа."
            )
            return
    elif not _is_admin_user(user.id):
        await msg.reply_text(
            "Только админ может привязать чат. Используйте /reviews в канале отзывов."
        )
        return

    if not is_reviews_chat(chat.id, username=getattr(chat, "username", None)):
        await msg.reply_text(
            "Это не канал отзывов @focuspayr. Автоприём привязывается только к нему."
        )
        return

    try:
        path = write_reviews_chat_id(chat.id)
    except OSError as e:
        logger.error("write reviews chat id: %s", e)
        await msg.reply_text(f"Ошибка записи chat_id: {e}")
        return

    title = chat.title or ""
    sync_note = ""
    try:
        sync = await sync_reviews_join_requests(context.bot, chat_id=chat.id)
        if sync.approved:
            sync_note = f"\n\n🔄 Висящие заявки: одобрено <b>{sync.approved}</b>."
        else:
            sync_note = (
                f"\n\n🔄 Проверено пользователей: {sync.checked}. "
                "Висящих заявок среди них не найдено."
            )
    except Exception as e:
        logger.warning("reviews sync after register failed: %s", e)
        sync_note = f"\n\n⚠️ Синхронизация висящих заявок не удалась: {e}"

    await msg.reply_text(
        f"✅ <b>Канал отзывов привязан</b>\n"
        f"<code>{chat.id}</code> · {title}\n\n"
        "Заявки на вступление: пропускаем только тех, кто нажимал /start в боте.\n"
        "В канале включите «Approve new members».\n"
        f"Файл: <code>{path}</code>"
        f"{sync_note}",
        parse_mode="HTML",
    )
    logger.info(
        "reviews chat registered chat_id=%s title=%r file=%s",
        chat.id,
        title,
        path,
    )


async def reviews_text_register(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Plain text «reviews» / «отзывы» или /reviews в канале."""
    msg = _reply_target(update)
    if not msg:
        return
    text = (msg.text or "").strip()
    if not _REVIEWS_TRIGGER_RE.match(text):
        return
    await register_reviews_chat(update, context)


async def sync_reviews_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Принудительно обработать висящие заявки (approve по bot_users)."""
    if not update.effective_user or not update.message:
        return
    if not _is_admin_user(update.effective_user.id):
        await update.message.reply_text("Только админ.")
        return

    gid = reviews_chat_id()
    if not gid:
        await update.message.reply_text(
            "Чат не привязан. Сначала /reviews в канале отзывов."
        )
        return

    await update.message.reply_text("⏳ Синхронизация висящих заявок…")
    try:
        sync = await sync_reviews_join_requests(context.bot, chat_id=gid)
    except Exception as e:
        logger.exception("reviews sync failed")
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


async def decline_reviews_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Отклонить висящие заявки по user_id из списка в команде."""
    if not update.effective_user or not update.message:
        return
    if not _is_admin_user(update.effective_user.id):
        await update.message.reply_text("Только админ.")
        return

    gid = reviews_chat_id()
    if not gid:
        await update.message.reply_text(
            "Чат не привязан. Сначала /reviews в канале отзывов."
        )
        return

    raw = (update.message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        await update.message.reply_text(
            "Формат: <code>/reviews_decline 123456789 987654321</code>\n"
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

    declined, errors = await decline_reviews_join_requests(
        context.bot, chat_id=gid, user_ids=user_ids
    )
    await update.message.reply_text(
        f"Отклонено: {declined}\nОшибок: {errors}",
    )
