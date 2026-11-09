"""Привязка группы/канала новостей FocusPay для автоприёма заявок на вступление.

Только TELEGRAM_ADMIN_IDS. chat_id подтверждается allowlist / env.
Логи — через псевдонимы (без сырых chat_id в application logger).
"""
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
from services.news_privacy import pseudo_chat, pseudo_user, security_log

logger = logging.getLogger("news_chat_register")

_ALLOWED_CHAT_TYPES = frozenset({"group", "supergroup", "channel"})
_NEWS_TRIGGER_RE = re.compile(r"^/?(news|новости)(?:@\w+)?$", re.IGNORECASE)


def _is_admin_user(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return int(user_id) in set(int(x) for x in TELEGRAM_ADMIN_IDS)


async def _chat_allowed(chat_id: int) -> bool:
    """Env TELEGRAM_NEWS_CHAT_ID или подтверждённый allowlist."""
    from services.config_rates import TELEGRAM_NEWS_CHAT_ID

    if TELEGRAM_NEWS_CHAT_ID and int(TELEGRAM_NEWS_CHAT_ID) == int(chat_id):
        return True
    try:
        from services.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT chat_id FROM news_chat_allowlist
                WHERE chat_id = $1 AND active = TRUE
                """,
                int(chat_id),
            )
        return row is not None
    except Exception as e:
        logger.warning("news allowlist check failed: %s", type(e).__name__)
        return False


async def _confirm_allowlist(chat_id: int, *, admin_id: int, title: str = "") -> None:
    try:
        from services.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO news_chat_allowlist (chat_id, title, confirmed_by, active)
                VALUES ($1, $2, $3, TRUE)
                ON CONFLICT (chat_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    confirmed_by = EXCLUDED.confirmed_by,
                    confirmed_at = now(),
                    active = TRUE
                """,
                int(chat_id),
                (title or "")[:200],
                int(admin_id),
            )
        security_log.info(
            "news_allowlist_confirm chat=%s by=%s",
            pseudo_chat(chat_id),
            pseudo_user(admin_id),
        )
    except Exception as e:
        logger.warning("news allowlist write failed: %s", type(e).__name__)


def _reply_target(update: Update):
    return update.effective_message


async def _send_bound_notice(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.warning(
            "news bound notice failed chat=%s: %s",
            pseudo_chat(chat_id),
            type(e).__name__,
        )


async def _sync_news_in_background(bot, chat_id: int) -> None:
    try:
        sync = await sync_news_join_requests(
            bot,
            chat_id=chat_id,
            notify_on_channels_limit=False,
        )
        security_log.info(
            "news background sync done chat=%s checked=%s approved=%s "
            "channels_blocked=%s skipped=%s errors=%s",
            pseudo_chat(chat_id),
            sync.checked,
            sync.approved,
            sync.channels_blocked,
            sync.skipped,
            sync.errors,
        )
    except Exception as e:
        logger.warning(
            "news background sync failed chat=%s: %s",
            pseudo_chat(chat_id),
            type(e).__name__,
        )


async def register_news_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = _reply_target(update)
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not msg:
        logger.warning("news register: no chat/message update=%s", update.update_id)
        return

    security_log.info(
        "news register attempt chat=%s type=%s user=%s",
        pseudo_chat(chat.id),
        chat.type,
        pseudo_user(getattr(user, "id", None)),
    )

    if chat.type not in _ALLOWED_CHAT_TYPES:
        await msg.reply_text("Команда только для группы или канала с ботом.")
        return

    # Канал без from_user: только если chat уже в env/allowlist (не даём чужой пост привязать).
    if user is None:
        if chat.type != "channel" or not await _chat_allowed(chat.id):
            await msg.reply_text(
                "Не удалось определить админа. Привязка из канала — только для "
                "chat_id из TELEGRAM_NEWS_CHAT_ID / allowlist, либо /news_bind в ЛС."
            )
            return
        admin_id = int(TELEGRAM_ADMIN_IDS[0]) if TELEGRAM_ADMIN_IDS else 0
    else:
        if not _is_admin_user(user.id):
            await msg.reply_text(
                "Только админ может привязать чат. Используйте /news в группе/канале новостей."
            )
            return
        admin_id = int(user.id)

    # Для новой привязки из группы: админ OK; для channel anonymous — allowlist уже проверен.
    if user is not None and chat.type == "channel":
        # Первый bind канала от админа разрешён; пишем allowlist.
        pass
    elif user is None and not await _chat_allowed(chat.id):
        await msg.reply_text("Чат не в allowlist.")
        return

    try:
        path = write_news_chat_id(chat.id)
    except OSError as e:
        logger.error("write news chat id: %s", type(e).__name__)
        await msg.reply_text(f"Ошибка записи chat_id: {e}")
        return

    title = chat.title or ""
    if admin_id:
        await _confirm_allowlist(chat.id, admin_id=admin_id, title=title)

    text = (
        f"✅ <b>Новости FocusPay привязаны</b>\n"
        f"<code>{chat.id}</code> · {title}\n"
        f"Тип: <code>{chat.type}</code>\n\n"
        "Заявки на вступление: пропускаем только тех, кто нажимал /start в боте.\n"
        "Синхронизация висящих заявок запущена в фоне.\n"
        f"Файл: <code>{path}</code>"
    )

    try:
        await msg.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning(
            "news register reply failed chat=%s: %s",
            pseudo_chat(chat.id),
            type(e).__name__,
        )
        await _send_bound_notice(context.bot, chat.id, text)

    for admin_id in TELEGRAM_ADMIN_IDS:
        await _send_bound_notice(context.bot, int(admin_id), text)

    security_log.warning(
        "news chat registered chat=%s type=%s",
        pseudo_chat(chat.id),
        chat.type,
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
    if not _is_admin_user(update.effective_user.id):
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

    # Проверяем, что бот видит чат (иначе произвольный id не подтверждаем).
    title = ""
    try:
        chat = await context.bot.get_chat(chat_id)
        title = chat.title or ""
        if getattr(chat, "type", None) not in _ALLOWED_CHAT_TYPES:
            await update.message.reply_text("Это не группа/канал.")
            return
    except Exception as e:
        logger.warning(
            "news_bind get_chat failed chat=%s: %s",
            pseudo_chat(chat_id),
            type(e).__name__,
        )
        await update.message.reply_text(
            "Не удалось получить чат. Добавьте бота в группу/канал и повторите."
        )
        return

    try:
        path = write_news_chat_id(chat_id)
    except OSError as e:
        await update.message.reply_text(f"Ошибка записи: {e}")
        return

    await _confirm_allowlist(
        chat_id, admin_id=int(update.effective_user.id), title=title
    )

    text = (
        f"✅ <b>Новости FocusPay привязаны</b>\n"
        f"<code>{chat_id}</code>"
        + (f" · {title}" if title else "")
        + f"\nФайл: <code>{path}</code>\n"
        "Синхронизация висящих заявок запущена в фоне."
    )
    await update.message.reply_text(text, parse_mode="HTML")
    security_log.warning(
        "news chat bound via private chat=%s",
        pseudo_chat(chat_id),
    )
    asyncio.create_task(_sync_news_in_background(context.bot, chat_id))


async def sync_news_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Принудительно обработать висящие заявки (approve/decline по bot_users)."""
    if not update.effective_user or not update.message:
        return
    if not _is_admin_user(update.effective_user.id):
        await update.message.reply_text("Только админ.")
        return

    gid = news_chat_id()
    if not gid:
        await update.message.reply_text(
            "Чат не привязан. Сначала /news в группе/канале или /news_bind <id> в ЛС."
        )
        return
    if not await _chat_allowed(int(gid)):
        await update.message.reply_text(
            "Привязанный chat_id не подтверждён в allowlist. Повторите /news_bind."
        )
        return

    await update.message.reply_text("⏳ Синхронизация висящих заявок…")
    try:
        sync = await sync_news_join_requests(context.bot, chat_id=gid)
    except Exception as e:
        logger.exception("news sync failed")
        await update.message.reply_text(f"Ошибка синхронизации: {type(e).__name__}")
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
    if not _is_admin_user(update.effective_user.id):
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
