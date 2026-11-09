"""Привязка группы/канала новостей FocusPay для автоприёма заявок на вступление."""
from __future__ import annotations

import asyncio
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS, news_chat_id
from services.news_chat_store import write_news_chat_id
from services.news_join_sync import (
    decline_news_join_requests,
    sync_news_join_requests,
)

logger = logging.getLogger("news_chat_register")

_ALLOWED_CHAT_TYPES = frozenset({"group", "supergroup", "channel"})
_NEWS_TRIGGER_RE = re.compile(r"^/?(news|новости)(?:@\w+)?$", re.IGNORECASE)


def _reply_target(update: Update):
    return update.effective_message


async def _send_bound_notice(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.warning("news bound notice failed chat=%s: %s", chat_id, e)


async def _sync_news_in_background(bot, chat_id: int) -> None:
    try:
        sync = await sync_news_join_requests(
            bot,
            chat_id=chat_id,
            notify_on_channels_limit=False,
        )
        logger.warning(
            "news background sync done chat=%s checked=%s approved=%s "
            "channels_blocked=%s skipped=%s errors=%s",
            chat_id,
            sync.checked,
            sync.approved,
            sync.channels_blocked,
            sync.skipped,
            sync.errors,
        )
    except Exception as e:
        logger.warning("news background sync failed chat=%s: %s", chat_id, e)


async def register_news_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = _reply_target(update)
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not msg:
        logger.warning("news register: no chat/message update=%s", update.update_id)
        return

    logger.info(
        "news register attempt chat=%s type=%s user=%s text=%r",
        chat.id,
        chat.type,
        getattr(user, "id", None),
        (msg.text or "")[:80],
    )

    if chat.type not in _ALLOWED_CHAT_TYPES:
        await msg.reply_text("Команда только для группы или канала с ботом.")
        return

    # В канале пост часто без from_user (анонимный админ) — пропускаем, иначе silent fail.
    if user is not None and user.id not in TELEGRAM_ADMIN_IDS:
        await msg.reply_text(
            "Только админ может привязать чат. Используйте /news в группе/канале новостей."
        )
        return
    if user is None and chat.type != "channel":
        await msg.reply_text("Не удалось определить пользователя.")
        return

    try:
        path = write_news_chat_id(chat.id)
    except OSError as e:
        logger.error("write news chat id: %s", e)
        await msg.reply_text(f"Ошибка записи chat_id: {e}")
        return

    title = chat.title or ""
    text = (
        f"✅ <b>Новости FocusPay привязаны</b>\n"
        f"<code>{chat.id}</code> · {title}\n"
        f"Тип: <code>{chat.type}</code>\n\n"
        "Заявки на вступление: пропускаем только тех, кто нажимал /start в боте.\n"
        "Синхронизация висящих заявок запущена в фоне.\n"
        f"Файл: <code>{path}</code>"
    )

    # Сразу ответ — полный sync по bot_users может идти минуты.
    try:
        await msg.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning("news register reply failed chat=%s: %s", chat.id, e)
        await _send_bound_notice(context.bot, chat.id, text)

    # Дубль админам в ЛС (в канале пост мог не увидеть /news).
    for admin_id in TELEGRAM_ADMIN_IDS:
        await _send_bound_notice(context.bot, int(admin_id), text)

    logger.warning(
        "news chat registered chat_id=%s type=%s title=%r file=%s",
        chat.id,
        chat.type,
        title,
        path,
    )
    asyncio.create_task(_sync_news_in_background(context.bot, chat.id))


async def news_text_register(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Plain text «news» / «новости» (если Privacy Mode выключен) или /news в канале."""
    msg = _reply_target(update)
    if not msg:
        return
    text = (msg.text or "").strip()
    if not _NEWS_TRIGGER_RE.match(text):
        return
    await register_news_chat(update, context)


async def news_bind_private(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Привязка по ID из ЛС: /news_bind -100xxxxxxxxxx"""
    if not update.effective_user or not update.message:
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("Только админ.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Формат: <code>/news_bind -100xxxxxxxxxx</code>\n"
            "ID можно узнать командой /chatid в группе или из ссылки t.me/c/…",
            parse_mode="HTML",
        )
        return
    try:
        chat_id = int(args[0].strip())
    except ValueError:
        await update.message.reply_text("chat_id должен быть числом.")
        return
    if chat_id >= 0:
        await update.message.reply_text(
            "Ожидается отрицательный chat_id группы/канала (например -100…)."
        )
        return

    try:
        path = write_news_chat_id(chat_id)
    except OSError as e:
        await update.message.reply_text(f"Ошибка записи: {e}")
        return

    title = ""
    try:
        chat = await context.bot.get_chat(chat_id)
        title = chat.title or ""
    except Exception as e:
        logger.warning("news_bind get_chat failed chat=%s: %s", chat_id, e)

    text = (
        f"✅ <b>Новости FocusPay привязаны</b>\n"
        f"<code>{chat_id}</code>"
        + (f" · {title}" if title else "")
        + f"\nФайл: <code>{path}</code>\n"
        "Синхронизация висящих заявок запущена в фоне."
    )
    await update.message.reply_text(text, parse_mode="HTML")
    logger.warning("news chat bound via private chat_id=%s title=%r", chat_id, title)
    asyncio.create_task(_sync_news_in_background(context.bot, chat_id))


async def sync_news_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Принудительно обработать висящие заявки (approve/decline по bot_users)."""
    if not update.effective_user or not update.message:
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("Только админ.")
        return

    gid = news_chat_id()
    if not gid:
        await update.message.reply_text(
            "Чат не привязан. Сначала /news в группе/канале или /news_bind <id> в ЛС."
        )
        return

    await update.message.reply_text("⏳ Синхронизация висящих заявок…")
    try:
        sync = await sync_news_join_requests(context.bot, chat_id=gid)
    except Exception as e:
        logger.exception("news sync failed")
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


async def decline_news_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Отклонить висящие заявки по user_id из списка в команде."""
    if not update.effective_user or not update.message:
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("Только админ.")
        return

    gid = news_chat_id()
    if not gid:
        await update.message.reply_text(
            "Чат не привязан. Сначала /news в группе/канале или /news_bind <id> в ЛС."
        )
        return

    raw = (update.message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        await update.message.reply_text(
            "Формат: <code>/news_decline 123456789 987654321</code>\n"
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

    declined, errors = await decline_news_join_requests(
        context.bot, chat_id=gid, user_ids=user_ids
    )
    await update.message.reply_text(
        f"Отклонено: {declined}\nОшибок: {errors}",
    )
