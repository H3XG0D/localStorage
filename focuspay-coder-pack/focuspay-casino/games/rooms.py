"""Equal-stake rooms from Telegram: list, create, join, leave, cancel, bot."""
from __future__ import annotations

import contextlib
import logging
import re
from decimal import Decimal
from typing import Any

import httpx
from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from finance import money
from focuspay_client import FocusPayClient
from games.board_style import PHASE_LABELS, render_board, seconds_until
from games.catalog import fmt_id
from games.chat_guard import ActiveGameChatGuard, callback_chat, telegram_user_id
from games.chat_reaper import try_delete_user_message
from games.site_links import add_watch_button, append_watch_line, room_url
from games.stake_buttons import STAKE_PRESETS, is_private_chat

logger = logging.getLogger(__name__)

PREFIX = "rm:"
MIN_SEATS = 2
MAX_SEATS = 6
_AMOUNT = re.compile(
    r"^(?P<body>\d+(?:[.,]\d{1,2})?)(?P<suf>р|₽|руб|rub)?$",
    re.IGNORECASE,
)
_ROOM_ID = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
_awaiting_stake: dict[int, bool] = {}


class _CommandProxy:
    def __init__(self, message: Any, user: Any, text: str) -> None:
        self.chat = getattr(message, "chat", None)
        self.from_user = user
        self.text = text
        self.message_id = getattr(message, "message_id", None)


def parse_amount_token(token: str) -> Decimal | None:
    raw = token.strip()
    match = _AMOUNT.fullmatch(raw)
    if not match:
        return None
    body = match.group("body").replace(",", ".")
    try:
        amount = money(body)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


def encode_stake(amount: Decimal) -> str:
    text = format(money(amount), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def parse_room_callback(data: str) -> tuple[str, ...] | None:
    raw = str(data or "")
    if not raw.startswith(PREFIX):
        return None
    parts = raw.split(":")
    if len(parts) < 2:
        return None
    action = parts[1]
    if action in {"list", "new"} and len(parts) == 2:
        return (action,)
    if action == "st" and len(parts) == 3:
        return ("st", parts[2])
    if action == "mk" and len(parts) == 4:
        return ("mk", parts[2], parts[3])
    if action in {"join", "leave", "cxl", "bot", "see"} and len(parts) == 3:
        token = parts[2]
        if not _ROOM_ID.fullmatch(token):
            return None
        return (action, token)
    return None


def _fmt_money(value: object) -> str:
    try:
        amount = money(value)
    except (TypeError, ValueError):
        return "0"
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _api_detail(exc: Exception, fallback: str) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        with contextlib.suppress(Exception):
            detail = exc.response.json().get("detail")
            if detail:
                return str(detail)
    return fallback


def room_play_url(room_id: object) -> str | None:
    return room_url(room_id)


def room_card_text(
    snapshot: dict[str, Any] | None,
    *,
    viewer_id: int | None = None,
    phase: str | None = None,
) -> str:
    snap = snapshot if isinstance(snapshot, dict) else {}
    room_id = str(snap.get("room_id") or "")
    status = str(snap.get("status") or "—")
    stake = _fmt_money(snap.get("stake_rub") or 0)
    filled = snap.get("filled") or 0
    seats = snap.get("seat_count") or 0
    rake = _fmt_money(snap.get("rake_percent") or 0)
    pot = _fmt_money(snap.get("pot_rub") or 0)
    players = snap.get("players") if isinstance(snap.get("players"), list) else []
    hide_winner = status in {"locked", "settled"} and phase not in {None, "reveal"} and phase is not None
    if phase is None and status in {"locked"}:
        hide_winner = True
    roster: list[str] = []
    ranked = [row for row in players[:8] if isinstance(row, dict)]
    if phase == "finalists":
        ranked = ranked[:3]
    for row in ranked:
        name = str(row.get("display_name") or row.get("user_id") or "игрок")[:40]
        kind = "бот" if row.get("participant_kind") == "bot" else "игрок"
        roster.append(f"• {name} ({kind})")
    extra: list[str] = []
    if viewer_id and snap.get("my_seat") is not None:
        extra.append("Вы за столом.")
    elif status == "open":
        extra.append("Равная ставка на всех. Колесо выбирает одного.")
    if not hide_winner and status == "settled" and snap.get("winner_id") is not None:
        winner = next(
            (row for row in players if isinstance(row, dict) and int(row.get("user_id") or 0) == int(snap["winner_id"])),
            None,
        )
        payout = _fmt_money(snap.get("payout_rub") or pot)
        if winner:
            extra.append(f"Победитель: {winner.get('display_name') or winner.get('user_id')} · {payout} ₽")
        else:
            extra.append(f"Выплата: {payout} ₽")
    now = PHASE_LABELS.get(phase or "", "")
    if not now:
        if status == "countdown":
            now = PHASE_LABELS["countdown"]
        elif status == "locked":
            now = PHASE_LABELS["reel"]
        elif status == "settled" and not hide_winner:
            now = PHASE_LABELS["settled"]
        elif status == "open":
            now = PHASE_LABELS["collect"]
        else:
            now = status
    nxt = "Равная ставка. Пустое место — бот." if status == "open" else ""
    left = seconds_until(snap.get("countdown_ends_at"))
    if status == "countdown" and left is not None:
        timer = f"⏳ Старт через {left} с"
    elif status == "open":
        wait = seconds_until(snap.get("closes_at"))
        timer = f"⏳ До закрытия {wait} с" if wait is not None else f"Статус: {status}. Рейк {rake}%. Банк {pot} ₽."
    else:
        timer = f"Статус: {status}. Рейк {rake}%. Банк {pot} ₽."
        if hide_winner:
            timer = "Крутится, ставки закрыты."
    return append_watch_line(
        render_board(
            header="🎯 <b>Комната</b>",
            subtitle=f"#{fmt_id(room_id)} · {stake} ₽ · {filled}/{seats} мест",
            roster=roster,
            now=now,
            nxt=nxt,
            timer=timer,
            extra=extra,
        ),
        room_play_url(room_id),
    )


def rooms_list_text(payload: dict[str, Any] | None) -> str:
    data = payload if isinstance(payload, dict) else {}
    rooms = [row for row in (data.get("rooms") or []) if isinstance(row, dict)]
    lines = [
        "🎯 <b>Комнаты</b>",
        "Равная ставка, 2–6 мест, колесо. Пустое место можно заполнить ботом.",
    ]
    open_rooms = [row for row in rooms if str(row.get("status") or "") == "open"]
    if not open_rooms:
        lines.append("Открытых комнат нет. Создайте новую.")
    for row in open_rooms[:8]:
        room_id = str(row.get("room_id") or "")
        filled = row.get("filled") or 0
        seats = row.get("seat_count") or 0
        lines.append(
            f"• #{fmt_id(room_id)} — {_fmt_money(row.get('stake_rub'))} ₽, {filled}/{seats}"
        )
    return "\n".join(lines)


def _create_stake_keyboard(*, private: bool) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    min_bet = Decimal(str(getattr(config, "MIN_BET", 10)))
    for stake in STAKE_PRESETS:
        if Decimal(stake) < min_bet:
            continue
        keyboard.add(
            types.InlineKeyboardButton(f"{stake} ₽", callback_data=f"{PREFIX}st:{stake}")
        )
    if private:
        keyboard.add(types.InlineKeyboardButton("✏️ Своя сумма", callback_data=f"{PREFIX}st:custom"))
    keyboard.add(types.InlineKeyboardButton("📋 Список", callback_data=f"{PREFIX}list"))
    return keyboard


def _seats_keyboard(stake: Decimal) -> types.InlineKeyboardMarkup:
    encoded = encode_stake(stake)
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    for count in range(MIN_SEATS, MAX_SEATS + 1):
        keyboard.add(
            types.InlineKeyboardButton(f"{count} мест", callback_data=f"{PREFIX}mk:{encoded}:{count}")
        )
    keyboard.add(types.InlineKeyboardButton("↩️ Ставка", callback_data=f"{PREFIX}new"))
    return keyboard


def _list_keyboard(payload: dict[str, Any] | None) -> types.InlineKeyboardMarkup:
    data = payload if isinstance(payload, dict) else {}
    rooms = [row for row in (data.get("rooms") or []) if isinstance(row, dict)]
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("➕ Создать", callback_data=f"{PREFIX}new"))
    for row in rooms:
        if str(row.get("status") or "") != "open":
            continue
        if row.get("my_seat") is not None:
            continue
        room_id = str(row.get("room_id") or "")
        if not _ROOM_ID.fullmatch(room_id):
            continue
        filled = row.get("filled") or 0
        seats = row.get("seat_count") or 0
        keyboard.add(
            types.InlineKeyboardButton(
                f"✅ Сесть {filled}/{seats} · {_fmt_money(row.get('stake_rub'))} ₽",
                callback_data=f"{PREFIX}join:{room_id}",
            )
        )
    keyboard.add(types.InlineKeyboardButton("🔄 Обновить", callback_data=f"{PREFIX}list"))
    return keyboard


def _card_keyboard(snapshot: dict[str, Any] | None) -> types.InlineKeyboardMarkup:
    snap = snapshot if isinstance(snapshot, dict) else {}
    room_id = str(snap.get("room_id") or "")
    keyboard = types.InlineKeyboardMarkup()
    if _ROOM_ID.fullmatch(room_id):
        if str(snap.get("status") or "") == "open" and snap.get("my_seat") is None:
            keyboard.add(types.InlineKeyboardButton("✅ Сесть", callback_data=f"{PREFIX}join:{room_id}"))
        if snap.get("can_leave"):
            keyboard.add(types.InlineKeyboardButton("↩️ Выйти", callback_data=f"{PREFIX}leave:{room_id}"))
        if snap.get("can_cancel"):
            keyboard.add(types.InlineKeyboardButton("❌ Отменить", callback_data=f"{PREFIX}cxl:{room_id}"))
        if snap.get("can_add_bot"):
            keyboard.add(types.InlineKeyboardButton("🤖 Бот", callback_data=f"{PREFIX}bot:{room_id}"))
        keyboard.add(types.InlineKeyboardButton("🔄 Обновить", callback_data=f"{PREFIX}see:{room_id}"))
    add_watch_button(keyboard, room_play_url(room_id))
    keyboard.add(types.InlineKeyboardButton("📋 Список", callback_data=f"{PREFIX}list"))
    return keyboard


async def _edit_or_send(bot: Any, call: Any, text: str, markup: Any | None = None) -> None:
    chat = getattr(getattr(call, "message", None), "chat", None)
    chat_id = getattr(chat, "id", None)
    message_id = getattr(getattr(call, "message", None), "message_id", None)
    if chat_id is None:
        return
    try:
        await bot.edit_message_text(
            text, chat_id, message_id, parse_mode="HTML", reply_markup=markup
        )
        return
    except Exception:
        logger.debug("rooms edit failed, sending new message", exc_info=True)
    await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


async def start_room_create(bot: AsyncTeleBot, client: FocusPayClient, call: Any) -> None:
    _ = client
    user = getattr(call, "from_user", None)
    message = getattr(call, "message", None)
    private = is_private_chat(getattr(message, "chat", None), user)
    text = (
        "🎯 <b>Комната</b>\n"
        "Равная ставка, 2–6 мест, колесо выбирает одного.\n\n"
        "Выберите ставку:"
    )
    await _edit_or_send(bot, call, text, _create_stake_keyboard(private=private))


async def send_rooms_list(
    bot: Any, client: FocusPayClient, *, chat_id: int, telegram_id: int
) -> None:
    payload = await _list_payload(client, telegram_id)
    await bot.send_message(
        chat_id,
        rooms_list_text(payload),
        parse_mode="HTML",
        reply_markup=_list_keyboard(payload),
    )


async def _list_payload(client: FocusPayClient, telegram_id: int) -> dict[str, Any]:
    try:
        data = await client.list_fixed_rooms(telegram_id=telegram_id)
    except Exception:
        logger.exception("rooms list failed telegram_id=%s", telegram_id)
        return {}
    return data if isinstance(data, dict) else {}


async def _show_card(
    bot: Any,
    call: Any,
    snapshot: dict[str, Any],
    *,
    viewer_id: int | None,
    client: Any = None,
) -> None:
    from games.rooms_card import upsert as upsert_room_card

    chat = getattr(getattr(call, "message", None), "chat", None)
    chat_id = getattr(chat, "id", None)
    message_id = getattr(getattr(call, "message", None), "message_id", None)
    if isinstance(chat_id, int) and not isinstance(chat_id, bool):
        try:
            await upsert_room_card(
                bot,
                client,
                chat_id,
                snapshot,
                telegram_id=viewer_id,
                message_id=message_id if isinstance(message_id, int) else None,
            )
            return
        except Exception:
            logger.debug("rooms live card upsert failed, falling back", exc_info=True)
    await _edit_or_send(
        bot,
        call,
        room_card_text(snapshot, viewer_id=viewer_id),
        _card_keyboard(snapshot),
    )


async def handle_rooms_command(
    bot: Any, client: FocusPayClient, message: Any, *, guard: ActiveGameChatGuard
) -> None:
    if not await guard.require_message(bot, message):
        return
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    user_id = telegram_user_id(user)
    chat_id = getattr(chat, "id", None)
    if user_id is None or chat_id is None:
        return
    await send_rooms_list(bot, client, chat_id=chat_id, telegram_id=user_id)
    await try_delete_user_message(bot, message)


async def _open_live_table(bot: Any, client: FocusPayClient, call: Any, family: str) -> None:
    user = getattr(call, "from_user", None)
    message = getattr(call, "message", None)
    if user is None or message is None:
        return
    proxy = _CommandProxy(message, user, f"/{family}")
    guard = ActiveGameChatGuard(client)
    if family == "roulette":
        from games.roulette_table import handle_roulette_command

        await handle_roulette_command(bot, client, proxy, guard=guard)
        return
    if family == "jackpot":
        from games.jackpot import handle_jackpot_command

        await handle_jackpot_command(bot, client, proxy, guard=guard)


async def handle_rooms_callback(
    bot: Any, client: FocusPayClient, call: Any, *, guard: ActiveGameChatGuard
) -> None:
    if not await guard.require_callback(bot, call):
        return
    parsed = parse_room_callback(str(getattr(call, "data", "") or ""))
    if parsed is None:
        with contextlib.suppress(Exception):
            await bot.answer_callback_query(call.id)
        return
    user = getattr(call, "from_user", None)
    user_id = telegram_user_id(user)
    chat = callback_chat(call)
    with contextlib.suppress(Exception):
        await bot.answer_callback_query(call.id)
    if user_id is None or chat is None:
        return
    action = parsed[0]
    try:
        if action == "list":
            payload = await _list_payload(client, user_id)
            await _edit_or_send(bot, call, rooms_list_text(payload), _list_keyboard(payload))
            return
        if action == "new":
            await start_room_create(bot, client, call)
            return
        if action == "st":
            token = parsed[1]
            private = is_private_chat(chat, user)
            if token == "custom":
                if not private:
                    await bot.answer_callback_query(
                        call.id, "Свою сумму можно ввести только в личке.", show_alert=True
                    )
                    return
                _awaiting_stake[user_id] = True
                await bot.send_message(
                    getattr(chat, "id"),
                    f"✏️ Отправьте сумму ставки (минимум {getattr(config, 'MIN_BET', 10):.0f} ₽).",
                )
                return
            amount = parse_amount_token(token)
            if amount is None:
                return
            await _edit_or_send(
                bot,
                call,
                f"🎯 Ставка {encode_stake(amount)} ₽. Сколько мест (2–6)?",
                _seats_keyboard(amount),
            )
            return
        if action == "mk":
            amount = parse_amount_token(parsed[1])
            try:
                seats = int(parsed[2])
            except (TypeError, ValueError):
                return
            if amount is None or seats < MIN_SEATS or seats > MAX_SEATS:
                return
            snap = await client.create_fixed_room(
                telegram_id=user_id, stake_rub=amount, seat_count=seats
            )
            await _show_card(bot, call, snap if isinstance(snap, dict) else {}, viewer_id=user_id, client=client)
            return
        room_id = parsed[1]
        if action == "join":
            snap = await client.join_fixed_room(room_id, telegram_id=user_id)
        elif action == "leave":
            snap = await client.leave_fixed_room(room_id, telegram_id=user_id)
        elif action == "cxl":
            snap = await client.cancel_fixed_room(room_id, telegram_id=user_id)
        elif action == "bot":
            snap = await client.add_fixed_room_bot(room_id, telegram_id=user_id)
        else:
            snap = await client.get_fixed_room(room_id, telegram_id=user_id)
        await _show_card(bot, call, snap if isinstance(snap, dict) else {}, viewer_id=user_id, client=client)
    except Exception as exc:
        await _edit_or_send(
            bot, call, f"❌ {_api_detail(exc, 'Не удалось. Попробуйте позже.')}"
        )


def register_rooms_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    guard = ActiveGameChatGuard(client)

    @bot.message_handler(commands=["rooms", "комнаты"])
    async def cmd_rooms(message):
        try:
            await handle_rooms_command(bot, client, message, guard=guard)
        except Exception:
            logger.exception("rooms command failed")
            with contextlib.suppress(Exception):
                await bot.reply_to(message, "❌ Не удалось открыть комнаты. Попробуйте позже.")

    @bot.message_handler(
        func=lambda m: getattr(getattr(m, "from_user", None), "id", None) in _awaiting_stake
    )
    async def custom_room_stake(message):
        user = getattr(message, "from_user", None)
        user_id = telegram_user_id(user)
        if user_id is None or user_id not in _awaiting_stake:
            return
        if not await guard.require_message(bot, message):
            return
        _awaiting_stake.pop(user_id, None)
        amount = parse_amount_token(str(getattr(message, "text", "") or ""))
        if amount is None:
            await bot.reply_to(message, "❌ Неверная сумма. Пример: 100")
            return
        await bot.reply_to(
            message,
            f"🎯 Ставка {encode_stake(amount)} ₽. Сколько мест (2–6)?",
            parse_mode="HTML",
            reply_markup=_seats_keyboard(amount),
        )

    @bot.callback_query_handler(func=lambda c: str(getattr(c, "data", "")).startswith(PREFIX))
    async def cb_rooms(call):
        try:
            await handle_rooms_callback(bot, client, call, guard=guard)
        except Exception:
            logger.exception("rooms callback failed")
            with contextlib.suppress(Exception):
                await bot.answer_callback_query(call.id, "Не удалось.", show_alert=True)

    @bot.callback_query_handler(func=lambda c: str(getattr(c, "data", "")).startswith("hub:"))
    async def cb_hub(call):
        data = str(getattr(call, "data", "") or "")
        try:
            await bot.answer_callback_query(call.id)
            if data == "hub:rooms":
                if not await guard.require_callback(bot, call):
                    return
                await start_room_create(bot, client, call)
                return
            if data in {"hub:roulette", "hub:jackpot"}:
                if not await guard.require_callback(bot, call):
                    return
                await _open_live_table(bot, client, call, data.split(":", 1)[1])
        except Exception:
            logger.exception("hub callback failed")
            with contextlib.suppress(Exception):
                await bot.answer_callback_query(call.id, "Не удалось открыть.", show_alert=True)
