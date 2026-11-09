"""Telegram entry/delivery checks; never infer DM access from a cached /start flag."""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)
_current_update: contextvars.ContextVar[Any] = contextvars.ContextVar('casino_update', default=None)
operation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar('casino_operation', default=None)


class EntryDenied(RuntimeError):
    pass


def classify_telegram_delivery_error(exc: BaseException) -> tuple[str, int | None]:
    """Classify delivery failures without relying on exception text alone.

    pyTelegramBotAPI exposes Telegram's payload differently across versions, so
    inspect both public attributes and ``result_json``.  Unknown failures stay
    retryable; only explicit Telegram responses mark a DM as unavailable.
    """
    result = getattr(exc, "result_json", None)
    if not isinstance(result, Mapping):
        result = {}
    error_code = getattr(exc, "error_code", None)
    if not isinstance(error_code, int):
        raw_code = result.get("error_code")
        error_code = raw_code if isinstance(raw_code, int) else None
    description = str(getattr(exc, "description", "") or result.get("description") or exc).lower()

    retry_after: int | None = None
    raw_retry = getattr(exc, "retry_after", None)
    parameters = result.get("parameters")
    if raw_retry is None and isinstance(parameters, Mapping):
        raw_retry = parameters.get("retry_after")
    try:
        if raw_retry is not None:
            retry_after = max(1, min(86400, int(raw_retry)))
    except (TypeError, ValueError):
        retry_after = None

    if error_code == 429 or "too many requests" in description:
        return "rate_limited", retry_after or 1
    if error_code == 403 or (
        error_code == 400
        and any(marker in description for marker in ("chat not found", "bot was blocked", "user is deactivated"))
    ):
        return "dm_unavailable", None
    return "temporary", None


def start_markup(username: str) -> str:
    return json.dumps({'inline_keyboard': [[{'text': 'Открыть игрового бота → Старт',
        'url': f'https://t.me/{username}?start=play'}]]})


class TelegramEntryCheck:
    """Run before a new player hold, not before settlement/cancel/recovery.

    A successful real DM proves current reachability (including after a restart).
    No main-bot user row, username guess or old positive cache grants access.
    """
    def __init__(self, bot, client):
        self.bot, self.client = bot, client

    async def __call__(self, user_id: int, *, game_chat_id: int | None = None) -> None:
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise EntryDenied('Не удалось определить Telegram-игрока.')
        me = await self.bot.get_me()
        update = _current_update.get()
        message = getattr(update, 'message', None) or update
        source_chat = getattr(getattr(message, 'chat', None), 'id', None)
        target_chat = game_chat_id if game_chat_id is not None else source_chat
        if isinstance(target_chat, int) and target_chat < 0:
            binding = await self.client.get_active_game_chat_binding()
            if not binding or int(binding.get('chat_id') or 0) != target_chat:
                raise EntryDenied('Этот чат не привязан к играм. Ставка не принята.')
            member = await self.bot.get_chat_member(target_chat, me.id)
            # Group members can send/edit their own game cards. Deleting other
            # users' messages is optional housekeeping, not a betting permission.
            status = member.status
            if status in {'administrator', 'creator'}:
                can_send = True
            elif status == 'restricted':
                can_send = (getattr(member, 'is_member', False) is True
                            and getattr(member, 'can_send_messages', False) is True)
            elif status == 'member':
                chat = await self.bot.get_chat(target_chat)
                can_send = getattr(getattr(chat, 'permissions', None), 'can_send_messages', False) is True
            else:
                can_send = False
            if not can_send:
                raise EntryDenied('Боту запрещено отправлять сообщения в игровой чат. Администратор чата должен разрешить отправку сообщений. Ставка не принята.')
        # Probe immediately before money movement. A chat action is silent but
        # Telegram applies the same blocked/not-started access checks as a DM.
        # Do not retry a failed probe as a bet.
        try:
            await self.bot.send_chat_action(user_id, "typing")
        except Exception as exc:
            error_code = getattr(exc, 'error_code', None)
            description = str(getattr(exc, 'description', '')).lower()
            if error_code != 403 and not (error_code == 400 and 'chat not found' in description):
                raise EntryDenied('Telegram временно не отвечает. Ставка не принята. Повторите попытку позже.') from exc
            chat_id = getattr(getattr(message, 'chat', None), 'id', None)
            if chat_id is not None:
                with contextlib.suppress(Exception):
                    await self.bot.send_message(chat_id,
                        'Перед игрой откройте игрового бота, нажмите «Старт» и затем повторите вход в игру. '
                        'Если бот заблокирован — разблокируйте его. Ставка не принята.',
                        reply_markup=start_markup(me.username))
            raise EntryDenied('Личный чат недоступен. Откройте игрового бота и нажмите «Старт».') from exc


def wrap_callback(bot, handler):
    """Bounded transport replay guard; backend remains the authority on money/CAS.

    Ack early even if the API is slow. Existing handler alerts remain intact.
    Only Telegram update IDs are deduplicated; a later intentional click is new.
    """
    seen: OrderedDict[str, float] = OrderedDict()
    busy: set[int] = set()

    @functools.wraps(handler)
    async def wrapped(call):
        now = time.monotonic()
        while seen and (len(seen) > 2048 or next(iter(seen.values())) < now - 600):
            seen.popitem(last=False)
        actor = getattr(getattr(call, 'from_user', None), 'id', None)
        if call.id in seen or actor in busy:
            with contextlib.suppress(Exception):
                await bot.answer_callback_query(call.id, 'Запрос уже обрабатывается. Проверьте «Мои игры».')
            return
        seen[call.id] = now
        busy.add(actor)
        token = _current_update.set(call)
        op = operation_id.set(str(call.id))
        async def acknowledge():
            await asyncio.sleep(.4)
            with contextlib.suppress(Exception):
                await bot.answer_callback_query(call.id)
        ack = asyncio.create_task(acknowledge())
        try:
            return await handler(call)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not print response/request strings: they can contain credentials.
            logger.warning('Callback failed handler=%s error=%s', handler.__name__, type(exc).__name__)
            text = str(exc) if isinstance(exc, EntryDenied) else (
                'Не удалось подтвердить действие. Откройте «Мои игры» или обновите баланс. '
                'Не создавайте новую ставку, пока статус предыдущей не проверен.')
            chat_id = getattr(getattr(getattr(call, 'message', None), 'chat', None), 'id', actor)
            with contextlib.suppress(Exception):
                await bot.answer_callback_query(call.id, text[:200], show_alert=True)
        finally:
            ack.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ack
            with contextlib.suppress(Exception):
                await bot.answer_callback_query(call.id)
            operation_id.reset(op)
            _current_update.reset(token)
            busy.discard(actor)
    return wrapped


def wrap_message(bot, handler):
    @functools.wraps(handler)
    async def wrapped(message):
        token = _current_update.set(message)
        try:
            return await handler(message)
        except EntryDenied as exc:
            await bot.send_message(message.chat.id, str(exc))
        finally:
            _current_update.reset(token)
    return wrapped


def install_telegram_guards(bot, client) -> None:
    """Install once after all handlers, before polling. No impact on API consumers."""
    client.entry_check = TelegramEntryCheck(bot, client)
    for registry, wrapper in (('callback_query_handlers', wrap_callback), ('message_handlers', wrap_message)):
        for handler in getattr(bot, registry, ()):
            if handler.get('_casino_guarded'):
                continue
            handler['function'] = wrapper(bot, handler['function'])
            handler['_casino_guarded'] = True
