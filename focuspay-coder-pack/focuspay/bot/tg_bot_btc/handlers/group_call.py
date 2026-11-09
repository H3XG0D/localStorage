"""Команда /spam в группе: админ пишет текст, бот зовёт участников чата."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from telegram import MessageEntity, User
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from services.chat_call import (
    BATCH_SIZE,
    CALL_ALLOW_USER_ID,
    QUOTE_MAX_LEN,
    SEND_INTERVAL_SEC,
    CallMessage,
    CallUser,
    build_call_messages,
    quote_from_command,
    user_may_call,
)
from services.chat_roster import (
    clean_username,
    ensure_chat_roster,
    forget_member,
    list_chat_members,
    remember_member,
)

logger = logging.getLogger("group_call")

_GROUP_TYPES = frozenset({"group", "supergroup"})
_running: dict[int, asyncio.Task[None]] = {}
_run_lock = asyncio.Lock()


def _retry_seconds(exc: RetryAfter) -> float:
    value = exc.retry_after
    if isinstance(value, timedelta):
        return float(value.total_seconds())
    return float(value)


def _entities(prepared: CallMessage) -> list[MessageEntity]:
    entities: list[MessageEntity] = []
    for mention in prepared.mentions:
        entities.append(
            MessageEntity(
                type=MessageEntity.TEXT_MENTION,
                offset=mention.offset,
                length=mention.length,
                user=User(
                    id=mention.user_id,
                    is_bot=False,
                    first_name=mention.first_name,
                    username=clean_username(mention.username),
                ),
            )
        )
    return entities


async def _chat_status(bot: object, chat_id: int, user_id: int) -> str | None:
    try:
        member = await bot.get_chat_member(chat_id, user_id)  # type: ignore[attr-defined]
    except Exception:
        logger.warning(
            "call admin check failed chat=%s user=%s",
            chat_id,
            user_id,
            exc_info=True,
        )
        return None
    return str(getattr(member, "status", "") or "")


async def _send_batch(bot: object, chat_id: int, prepared: CallMessage) -> None:
    entities = _entities(prepared)
    delay = 0.0
    for _attempt in range(4):
        if delay:
            await asyncio.sleep(delay)
        try:
            await bot.send_message(  # type: ignore[attr-defined]
                chat_id=chat_id,
                text=prepared.text,
                entities=entities,
                disable_web_page_preview=True,
            )
            return
        except RetryAfter as exc:
            delay = _retry_seconds(exc) + 0.5
            logger.warning("call flood chat=%s wait=%s", chat_id, delay)
    logger.error("call send gave up chat=%s", chat_id)


async def _safe_remember(chat_id: int, user: object) -> None:
    if getattr(user, "is_bot", False):
        return
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        return
    try:
        await remember_member(
            chat_id,
            user_id,
            username=getattr(user, "username", None),
            first_name=getattr(user, "first_name", None),
        )
    except Exception:
        logger.warning(
            "call remember failed chat=%s user=%s",
            chat_id,
            user_id,
            exc_info=True,
        )


async def _safe_forget(chat_id: int, user: object) -> None:
    if getattr(user, "is_bot", False):
        return
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        return
    try:
        await forget_member(chat_id, user_id)
    except Exception:
        logger.warning(
            "call forget failed chat=%s user=%s",
            chat_id,
            user_id,
            exc_info=True,
        )


def _service_users(value: object) -> list[object]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(getattr(item, "id", None), int)]


async def track_group_message(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запомнить автора сообщения и вход/выход, которые бот видит в чате."""
    message = update.effective_message  # type: ignore[attr-defined]
    chat = update.effective_chat  # type: ignore[attr-defined]
    if message is None or chat is None:
        return
    if str(getattr(chat, "type", "") or "") not in _GROUP_TYPES:
        return
    chat_id = int(chat.id)
    user = update.effective_user  # type: ignore[attr-defined]
    if user is not None:
        await _safe_remember(chat_id, user)
    for member in _service_users(getattr(message, "new_chat_members", None)):
        await _safe_remember(chat_id, member)
    left = getattr(message, "left_chat_member", None)
    if isinstance(getattr(left, "id", None), int):
        await _safe_forget(chat_id, left)


async def track_chat_member(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    incoming = update.chat_member  # type: ignore[attr-defined]
    if incoming is None:
        return
    chat = incoming.chat
    member = incoming.new_chat_member
    if chat is None or member is None:
        return
    user = member.user
    status = str(getattr(member, "status", "") or "")
    chat_id = int(chat.id)
    if status in {"left", "kicked"}:
        await _safe_forget(chat_id, user)
        return
    if status in {"creator", "administrator", "member", "restricted"}:
        await _safe_remember(chat_id, user)


async def _run_call(
    bot: object,
    chat_id: int,
    message_id: int,
    quote: str,
) -> None:
    queue: asyncio.Queue[CallUser | None] = asyncio.Queue()
    seen: set[int] = set()
    seen_lock = asyncio.Lock()
    failed = False

    async def emit(user: CallUser) -> None:
        if user.is_bot or user.deleted or int(user.user_id) <= 0:
            return
        async with seen_lock:
            if int(user.user_id) in seen:
                return
            seen.add(int(user.user_id))
        await queue.put(user)

    async def produce() -> None:
        nonlocal failed
        try:
            for member in await list_chat_members(chat_id):
                await emit(member)
            await ensure_chat_roster(bot, chat_id, on_keep=emit)
        except Exception:
            logger.warning("call member list failed chat=%s", chat_id, exc_info=True)
            failed = True
        finally:
            await queue.put(None)

    async def consume() -> None:
        batch: list[CallUser] = []
        posted = False
        total = 0

        async def flush(chunk: list[CallUser]) -> None:
            nonlocal posted
            prepared = build_call_messages(quote, chunk)
            if not prepared:
                return
            if posted:
                await asyncio.sleep(SEND_INTERVAL_SEC)
            await _send_batch(bot, chat_id, prepared[0])
            if not posted:
                posted = True
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)  # type: ignore[attr-defined]
                except Exception:
                    logger.warning("call delete command failed chat=%s", chat_id, exc_info=True)

        while True:
            item = await queue.get()
            if item is None:
                break
            batch.append(item)
            total += 1
            if len(batch) >= BATCH_SIZE:
                await flush(batch)
                batch = []
        if batch:
            await flush(batch)
        if not posted:
            text = (
                "Не удалось прочитать участников чата."
                if failed
                else "В чате некого звать."
            )
            await bot.send_message(chat_id=chat_id, text=text)  # type: ignore[attr-defined]
        logger.info("call done chat=%s users=%s", chat_id, total)

    try:
        await asyncio.gather(produce(), consume())
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("call failed chat=%s", chat_id)
    finally:
        async with _run_lock:
            current = _running.get(chat_id)
            if current is asyncio.current_task():
                _running.pop(chat_id, None)


async def spam_command(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message  # type: ignore[attr-defined]
    chat = update.effective_chat  # type: ignore[attr-defined]
    user = update.effective_user  # type: ignore[attr-defined]
    if message is None or chat is None or user is None:
        return
    if str(getattr(chat, "type", "") or "") not in _GROUP_TYPES:
        return

    text = message.text or ""
    quote = quote_from_command(text)
    if not quote:
        await message.reply_text("Напиши /spam и текст.")
        return
    if len(quote) > QUOTE_MAX_LEN:
        await message.reply_text("Текст длиннее 1000 символов.")
        return

    chat_id = int(chat.id)
    user_id = int(user.id)
    status: str | None = None
    if user_id != CALL_ALLOW_USER_ID:
        status = await _chat_status(context.bot, chat_id, user_id)
    if not user_may_call(user_id, status):
        await message.reply_text("Команда только для админа чата.")
        return
    await _safe_remember(chat_id, user)

    async with _run_lock:
        current = _running.get(chat_id)
        if current is not None and not current.done():
            await message.reply_text("В этом чате зазыв уже идёт.")
            return
        task = asyncio.create_task(
            _run_call(context.bot, chat_id, int(message.message_id), quote)
        )
        _running[chat_id] = task


def register_group_call_handlers(app: Application) -> None:
    app.add_handler(
        CommandHandler("spam", spam_command, filters=filters.ChatType.GROUPS),
        group=-1,
    )
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS, track_group_message),
        group=1,
    )
    app.add_handler(
        ChatMemberHandler(track_chat_member, chat_member_types=ChatMemberHandler.CHAT_MEMBER)
    )
