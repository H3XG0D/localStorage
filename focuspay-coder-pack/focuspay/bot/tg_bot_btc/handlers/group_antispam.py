"""Удаление спама и бан автора в публичных чатах FocusPay."""
from __future__ import annotations

import logging
from html import escape

from telegram import Chat, Message, Update, User
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from services.config_rates import (
    TELEGRAM_ADMIN_IDS,
    is_community_chat,
    is_news_chat,
    is_reviews_chat,
    reports_group_id,
)
from services.chat_call import CALL_ALLOW_USER_ID, is_call_command
from services.chat_cleanup import is_clean_command
from services.group_spam_filter import SpamVerdict, check_group_spam
from services.group_spam_phrases_store import extra_phrases as load_extra_phrases

logger = logging.getLogger("group_antispam")

_ADMIN_STATUSES = frozenset({"creator", "administrator"})


def is_watched_public_chat(chat: Chat | None) -> bool:
    if chat is None:
        return False
    cid = int(chat.id or 0)
    uname = getattr(chat, "username", None)
    return bool(
        is_community_chat(cid)
        or is_news_chat(cid)
        or is_reviews_chat(cid, username=uname)
    )


def _entity_urls(message: Message) -> list[str]:
    text = message.text or message.caption or ""
    entities = list(message.entities or ()) + list(message.caption_entities or ())
    urls: list[str] = []
    for ent in entities:
        kind = getattr(ent, "type", None)
        if kind == "url":
            urls.append(text[ent.offset : ent.offset + ent.length])
        elif kind == "text_link" and getattr(ent, "url", None):
            urls.append(ent.url)
    return urls


def _extra_tme_usernames(bot_username: str | None) -> list[str]:
    name = (bot_username or "").strip().lstrip("@")
    return [name] if name else []


def score_message(
    message: Message,
    *,
    bot_username: str | None = None,
    extra_phrases: list[str] | tuple[str, ...] | None = None,
) -> SpamVerdict:
    text = message.text or message.caption or ""
    return check_group_spam(
        text,
        _entity_urls(message),
        extra_tme_usernames=_extra_tme_usernames(bot_username),
        extra_phrases=extra_phrases,
    )


def _should_skip_user(message: Message, user: User | None) -> bool:
    chat = message.chat
    if message.is_automatic_forward:
        return True
    sender = message.sender_chat
    if sender is not None and chat is not None and int(sender.id) == int(chat.id):
        return True
    if user is None:
        return True
    if user.is_bot:
        return True
    if int(user.id) in TELEGRAM_ADMIN_IDS:
        return True
    return False


def _log_text(chat: Chat, user: User, verdict: SpamVerdict, *, banned: bool) -> str:
    uname = f"@{user.username}" if user.username else "—"
    action = "удалено + бан" if banned else "удалено (бан не удался)"
    reasons = ", ".join(verdict.reasons) or "—"
    return (
        f"<b>Антиспам</b>: {escape(action)}\n"
        f"чат: <code>{int(chat.id)}</code> {escape(chat.title or '')}\n"
        f"user_id: <code>{int(user.id)}</code> {escape(uname)}\n"
        f"причины: {escape(reasons)} ({verdict.score})"
    )


async def _is_chat_admin(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int
) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except Exception:
        logger.warning("antispam get_chat_member failed chat=%s user=%s", chat_id, user_id)
        return True
    status = getattr(member, "status", "") or ""
    return status in _ADMIN_STATUSES


async def _notify_reports(
    context: ContextTypes.DEFAULT_TYPE,
    chat: Chat,
    user: User,
    verdict: SpamVerdict,
    *,
    banned: bool,
) -> None:
    gid = reports_group_id()
    if not gid:
        return
    try:
        await context.bot.send_message(
            chat_id=gid,
            text=_log_text(chat, user, verdict, banned=banned),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.warning("antispam reports notify failed chat=%s", gid, exc_info=True)


async def group_antispam_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    if not is_watched_public_chat(chat):
        return

    user = update.effective_user
    text = message.text or ""
    if is_clean_command(text):
        return
    if (
        user is not None
        and int(user.id) == CALL_ALLOW_USER_ID
        and is_call_command(text)
    ):
        return
    if _should_skip_user(message, user):
        return

    bot_username = getattr(context.bot, "username", None)
    phrases = await load_extra_phrases()
    verdict = score_message(
        message, bot_username=bot_username, extra_phrases=phrases
    )
    if not verdict.is_spam:
        return

    assert user is not None
    if await _is_chat_admin(context, int(chat.id), int(user.id)):
        logger.info("antispam skip admin user=%s chat=%s", user.id, chat.id)
        return

    try:
        await message.delete()
    except Exception:
        logger.warning(
            "antispam delete failed chat=%s msg=%s",
            chat.id,
            message.message_id,
            exc_info=True,
        )
        return

    banned = False
    try:
        await context.bot.ban_chat_member(
            chat_id=int(chat.id),
            user_id=int(user.id),
            revoke_messages=True,
        )
        banned = True
    except Exception:
        logger.warning(
            "antispam ban failed chat=%s user=%s",
            chat.id,
            user.id,
            exc_info=True,
        )

    logger.info(
        "antispam hit chat=%s user=%s reasons=%s banned=%s",
        chat.id,
        user.id,
        ",".join(verdict.reasons),
        banned,
    )
    await _notify_reports(context, chat, user, verdict, banned=banned)


def register_group_antispam_handlers(app: Application) -> None:
    # ChatType filters look at effective_message, so this covers message,
    # edited_message, channel_post and edited_channel_post.
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS | filters.ChatType.CHANNEL,
            group_antispam_handler,
        )
    )
