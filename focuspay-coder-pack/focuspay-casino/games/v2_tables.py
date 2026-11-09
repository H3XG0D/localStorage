"""Telegram lobby for durable multiplayer V2 casino tables.

The backend owns seats, holds, automatic start and settlement. This module only
renders data returned by the internal V2 API and sends authenticated lifecycle
requests.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from focuspay_client import FocusPayClient
from games.card_invite import JOIN_PREFIX
from games.catalog import CARD_GAMES, EMOJI_GAMES, GAMES_CONFIG, fmt_id
from games.site_links import WATCH_LABEL, duel_url, table_url

logger = logging.getLogger(__name__)

V2_GAME_TYPE_TO_KEY: dict[str, str] = {}
for _key, _config in GAMES_CONFIG.items():
    game_type = str(_config["game_type"])
    if game_type not in V2_GAME_TYPE_TO_KEY or not _key.startswith("2"):
        V2_GAME_TYPE_TO_KEY[game_type] = _key


def _table_seats(table: dict[str, Any]) -> list[dict[str, Any]]:
    roster = table.get("roster")
    return roster if isinstance(roster, list) else []


def _seat_counts(table: dict[str, Any]) -> tuple[int, int, int]:
    seats = _table_seats(table)
    people = sum(1 for seat in seats if isinstance(seat, dict) and seat.get("participant_kind") == "player")
    bots = sum(1 for seat in seats if isinstance(seat, dict) and seat.get("participant_kind") == "bot")
    free_seats = table.get("free_seats")
    if isinstance(free_seats, list):
        return people, bots, len(free_seats)
    try:
        max_seats = int(table.get("max_seats", table.get("max_players", 0)))
    except (TypeError, ValueError):
        max_seats = 0
    return people, bots, max(0, max_seats - people - bots)


def _game_config(table: dict[str, Any]) -> dict[str, Any]:
    key = V2_GAME_TYPE_TO_KEY.get(str(table.get("game_type")))
    return GAMES_CONFIG.get(key or "", {"name": str(table.get("game_type", "Игра")), "emoji": "🎮"})


def _is_joinable(table: dict[str, Any], owner_id: int) -> bool:
    if table.get("status") != "open":
        return False
    return all(seat.get("telegram_id") != owner_id for seat in _table_seats(table) if isinstance(seat, dict))


def _duel_config(game: dict[str, Any]) -> dict[str, Any]:
    game_type = str(game.get("game_type") or "")
    if game_type in CARD_GAMES:
        return CARD_GAMES[game_type]
    try:
        rounds = int(game.get("rounds") or 1)
    except (TypeError, ValueError):
        rounds = 1
    for config_row in EMOJI_GAMES.values():
        if config_row["game_type"] == game_type and int(config_row["rolls"]) == rounds:
            return config_row
    return {"name": game_type or "Игра", "emoji": "🎮"}


def _duel_id(game: dict[str, Any]) -> str:
    return str(game.get("game_id") or "")


def _is_joinable_duel(game: dict[str, Any], owner_id: int) -> bool:
    if str(game.get("status") or "") != "waiting":
        return False
    if game.get("opponent_id") is not None:
        return False
    try:
        creator_id = int(game.get("creator_id") or 0)
    except (TypeError, ValueError):
        return False
    return creator_id > 0 and creator_id != owner_id and bool(_duel_id(game))


def _is_mine_duel(game: dict[str, Any], owner_id: int) -> bool:
    try:
        creator_id = int(game.get("creator_id") or 0)
    except (TypeError, ValueError):
        creator_id = 0
    try:
        opponent_id = int(game["opponent_id"]) if game.get("opponent_id") is not None else 0
    except (TypeError, ValueError):
        opponent_id = 0
    return owner_id in {creator_id, opponent_id} and bool(_duel_id(game))


def _duel_join_callback(game: dict[str, Any]) -> str | None:
    game_id = _duel_id(game)
    game_type = str(game.get("game_type") or "")
    if not game_id:
        return None
    prefix = JOIN_PREFIX.get(game_type)
    if prefix:
        return f"{prefix}{game_id}"
    if game_type == "pvp_dice":
        return f"dueljoin:{game_id}"
    return None


def _duel_site_url(game_id: str) -> str | None:
    return duel_url(game_id)


def _duel_line(game: dict[str, Any], *, own: bool = False) -> str:
    config_row = _duel_config(game)
    status = {
        "waiting": "ваша игра, ждёт соперника" if own else "ждёт соперника",
        "active": "идёт игра",
    }.get(str(game.get("status") or ""), str(game.get("status") or "—"))
    suffix = f" — {status}" if own or str(game.get("status") or "") != "waiting" else ""
    return (
        f"• #{fmt_id(_duel_id(game))} {config_row['emoji']} {config_row['name']} — "
        f"{game.get('stake_rub', '—')} ₽{suffix}"
    )


def _is_joinable_room(room: dict[str, Any], owner_id: int) -> bool:
    if str(room.get("status") or "") != "open":
        return False
    if room.get("my_seat") is not None:
        return False
    free = room.get("free_seats")
    if isinstance(free, list):
        return bool(free)
    try:
        filled = int(room.get("filled") or 0)
        seats = int(room.get("seat_count") or 0)
    except (TypeError, ValueError):
        return False
    return seats > filled


def _room_line(room: dict[str, Any]) -> str:
    room_id = str(room.get("room_id") or "")
    filled = room.get("filled") or 0
    seats = room.get("seat_count") or 0
    rake = room.get("rake_percent")
    rake_bit = f", рейк {rake}%" if rake is not None else ""
    return (
        f"• #{fmt_id(room_id)} 🎯 {room.get('stake_rub', '—')} ₽ — "
        f"{filled}/{seats} мест{rake_bit}"
    )


def _lobby_text(
    tables: list[dict[str, Any]],
    owner_id: int,
    duels: list[dict[str, Any]] | None = None,
    rooms: list[dict[str, Any]] | None = None,
) -> str:
    duels = duels or []
    rooms = rooms or []
    own_waiting = [game for game in duels if _is_mine_duel(game, owner_id) and str(game.get("status") or "") == "waiting"]
    joinable_duels = [game for game in duels if _is_joinable_duel(game, owner_id)]
    available_tables = [table for table in tables if _is_joinable(table, owner_id)]
    joinable_rooms = [room for room in rooms if _is_joinable_room(room, owner_id)]
    lines = [
        "🎮 <b>Активные игры</b>",
        "Рулетка и джекпот — общие столы. Комнаты — равная ставка, колесо.",
    ]
    if joinable_rooms:
        lines.append("")
        lines.append("<b>Комнаты</b>")
        for room in joinable_rooms[:6]:
            lines.append(_room_line(room))
    if own_waiting or joinable_duels or available_tables:
        lines.append("")
        lines.append("Дуэли 1×1 и столы 2–6. Ставка резервируется при входе.")
    for game in own_waiting:
        lines.append(_duel_line(game, own=True))
    for game in joinable_duels[:8]:
        lines.append(_duel_line(game))
    remaining = max(0, 8 - len(joinable_duels[:8]))
    for table in available_tables[:remaining]:
        config_row = _game_config(table)
        people, bots, free = _seat_counts(table)
        lines.append(
            f"• #{fmt_id(str(table.get('table_id', '')))} {config_row['emoji']} {config_row['name']} — "
            f"{table.get('stake_rub', '—')} ₽\n  Людей: {people}, ботов: {bots}, свободно: {free}"
        )
    if not joinable_rooms and not own_waiting and not joinable_duels and not available_tables:
        lines.append("Нет открытых комнат и столов. Рулетка и джекпот — кнопки ниже.")
    return "\n".join(lines)


def _add_url_or_skip(keyboard: types.InlineKeyboardMarkup, text: str, url: str | None) -> bool:
    if not url:
        return False
    keyboard.add(types.InlineKeyboardButton(text, url=url))
    return True


def _lobby_keyboard(
    tables: list[dict[str, Any]],
    owner_id: int,
    duels: list[dict[str, Any]] | None = None,
    rooms: list[dict[str, Any]] | None = None,
) -> types.InlineKeyboardMarkup | None:
    duels = duels or []
    rooms = rooms or []
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🎡 Рулетка", callback_data="hub:roulette"))
    keyboard.add(types.InlineKeyboardButton("🎡 Джекпот", callback_data="hub:jackpot"))
    for room in rooms:
        if not _is_joinable_room(room, owner_id):
            continue
        room_id = str(room.get("room_id") or "")
        if not room_id:
            continue
        filled = room.get("filled") or 0
        seats = room.get("seat_count") or 0
        keyboard.add(
            types.InlineKeyboardButton(
                f"✅ Комната {filled}/{seats} · {room.get('stake_rub', '—')} ₽",
                callback_data=f"rm:join:{room_id}",
            )
        )
    count = 0
    for game in duels:
        if _is_mine_duel(game, owner_id) and str(game.get("status") or "") == "waiting":
            config_row = _duel_config(game)
            if _add_url_or_skip(
                keyboard,
                f"🌐 На сайте: {config_row['emoji']} #{fmt_id(_duel_id(game))}",
                _duel_site_url(_duel_id(game)),
            ):
                count += 1
        if not _is_joinable_duel(game, owner_id):
            continue
        callback = _duel_join_callback(game)
        if not callback:
            continue
        config_row = _duel_config(game)
        keyboard.add(
            types.InlineKeyboardButton(
                f"✅ Войти: {config_row['emoji']} #{fmt_id(_duel_id(game))}",
                callback_data=callback,
            )
        )
        count += 1
        if count >= 8:
            break
    if count < 8:
        for table in tables:
            if not _is_joinable(table, owner_id):
                continue
            table_id = str(table.get("table_id", ""))
            if not table_id:
                continue
            config_row = _game_config(table)
            keyboard.add(
                types.InlineKeyboardButton(
                    f"✅ Войти: {config_row['emoji']} #{fmt_id(table_id)}",
                    callback_data=f"v2join:{table_id}",
                )
            )
            count += 1
            if count >= 8:
                break
    keyboard.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="v2lobby:refresh"))
    return keyboard


async def active_tables(client: FocusPayClient) -> list[dict[str, Any]]:
    response = await client.v2_tables_get("/v2/tables/active")
    tables = response.get("tables") if isinstance(response, dict) else None
    if not isinstance(tables, list):
        raise ValueError("V2 active tables response is invalid")
    return [table for table in tables if isinstance(table, dict)]


async def active_duels(client: FocusPayClient) -> list[dict[str, Any]]:
    getter = getattr(client, "get_active_pvp_games", None)
    if not callable(getter):
        return []
    games = await getter()
    if not isinstance(games, list):
        raise ValueError("Active PVP games response is invalid")
    return [game for game in games if isinstance(game, dict) and _duel_id(game)]


async def active_rooms(client: FocusPayClient, owner_id: int) -> list[dict[str, Any]]:
    getter = getattr(client, "list_fixed_rooms", None)
    if not callable(getter):
        return []
    try:
        payload = await getter(telegram_id=owner_id)
    except Exception:
        logger.exception("fixed rooms lobby list failed owner=%s", owner_id)
        return []
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    if not isinstance(rooms, list):
        return []
    return [room for room in rooms if isinstance(room, dict) and room.get("room_id")]


async def _warm_duel_caches(client: FocusPayClient, duels: list[dict[str, Any]]) -> None:
    try:
        from games.card_invite import hydrate_waiting_card_games

        await hydrate_waiting_card_games(client)
    except Exception:
        logger.exception("Card duel hydrate for DM lobby failed")
    try:
        from games.pvp import adopt_waiting_dice_from_durable

        for game in duels:
            if str(game.get("game_type") or "") == "pvp_dice" and str(game.get("status") or "") == "waiting":
                adopt_waiting_dice_from_durable(game)
    except Exception:
        logger.exception("Dice duel hydrate for DM lobby failed")


async def send_v2_lobby(bot: AsyncTeleBot, client: FocusPayClient, chat_id: int, owner_id: int) -> None:
    tables = await active_tables(client)
    duels = await active_duels(client)
    rooms = await active_rooms(client, owner_id)
    await _warm_duel_caches(client, duels)
    await bot.send_message(
        chat_id,
        _lobby_text(tables, owner_id, duels, rooms),
        parse_mode="HTML",
        reply_markup=_lobby_keyboard(tables, owner_id, duels, rooms),
    )


async def send_v2_my_tables(bot: AsyncTeleBot, client: FocusPayClient, chat_id: int, owner_id: int) -> None:
    tables = await active_tables(client)
    duels = await active_duels(client)
    await _warm_duel_caches(client, duels)
    mine = [
        table for table in tables
        if int(table.get("creator_id", 0) or 0) == owner_id
        or any(seat.get("telegram_id") == owner_id for seat in _table_seats(table) if isinstance(seat, dict))
    ]
    mine_duels = [game for game in duels if _is_mine_duel(game, owner_id)]
    if not mine and not mine_duels:
        await bot.send_message(chat_id, "📭 У вас нет активных игр. Создайте новую или найдите игру в лобби.")
        return
    lines = ["🎲 <b>Ваши активные игры</b>"]
    keyboard = types.InlineKeyboardMarkup()
    for game in mine_duels:
        lines.append(_duel_line(game, own=True))
        config_row = _duel_config(game)
        _add_url_or_skip(
            keyboard,
            f"🌐 На сайте: {config_row['emoji']} #{fmt_id(_duel_id(game))}",
            _duel_site_url(_duel_id(game)),
        )
        if _is_joinable_duel(game, owner_id):
            callback = _duel_join_callback(game)
            if callback:
                keyboard.add(
                    types.InlineKeyboardButton(
                        f"✅ Войти: {config_row['emoji']} #{fmt_id(_duel_id(game))}",
                        callback_data=callback,
                    )
                )
    for table in mine:
        table_id = str(table.get("table_id", ""))
        config_row = _game_config(table)
        people, bots, free = _seat_counts(table)
        status = {"open": "ожидает игроков", "running": "идёт игра", "ready": "готова к старту"}.get(str(table.get("status")), str(table.get("status", "—")))
        lines.append(f"• #{fmt_id(table_id)} {config_row['emoji']} {config_row['name']} — {table.get('stake_rub', '—')} ₽ — {status}\n  Людей: {people}, ботов: {bots}, свободно: {free}")
        _add_url_or_skip(
            keyboard,
            f"{WATCH_LABEL}: {config_row['emoji']} #{fmt_id(table_id)}",
            table_url(table_id),
        )
        if table.get("status") == "open":
            action = "v2cancel" if int(table.get("creator_id", 0) or 0) == owner_id else "v2leave"
            keyboard.add(types.InlineKeyboardButton("❌ Отменить стол" if action == "v2cancel" else "↩️ Выйти", callback_data=f"{action}:{table_id}"))
    has_buttons = bool(getattr(keyboard, "keyboard", None))
    await bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML", reply_markup=keyboard if has_buttons else None)


def _callback_origin(call) -> tuple[int, int] | None:
    message = getattr(call, "message", None)
    chat = getattr(message, "chat", None) if message is not None else None
    chat_id = getattr(chat, "id", None)
    msg_id = getattr(message, "message_id", None)
    if isinstance(chat_id, int) and not isinstance(chat_id, bool) and isinstance(msg_id, int) and not isinstance(msg_id, bool):
        return (chat_id, msg_id)
    return None


async def _discard_callback_card(bot: AsyncTeleBot, call, table_id: str, table: dict[str, Any] | None = None) -> None:
    from games.v2_runtime import discard_table_cards

    await discard_table_cards(bot, table, origin=_callback_origin(call), table_id=table_id)


def _expected_version(table: dict[str, Any]) -> int:
    try:
        return int(table["state_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("V2 table state version is invalid") from exc


async def _find_table(client: FocusPayClient, table_id: str) -> dict[str, Any] | None:
    return next((table for table in await active_tables(client) if str(table.get("table_id")) == table_id), None)


def _idempotency(operation: str, table_id: str, owner_id: int) -> str:
    return f"tg-{operation}-{table_id}-{owner_id}-{uuid.uuid4().hex}"


def register_v2_table_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    @bot.callback_query_handler(func=lambda call: isinstance(call.data, str) and call.data == "v2lobby:refresh")
    async def refresh_v2_lobby(call):
        await bot.answer_callback_query(call.id)
        await send_v2_lobby(bot, client, call.message.chat.id, call.from_user.id)

    @bot.callback_query_handler(func=lambda call: isinstance(call.data, str) and call.data.startswith("dueljoin:"))
    async def join_waiting_duel(call):
        game_id = call.data.split(":", 1)[1]
        try:
            from games.pvp import join_waiting_dice_from_dm

            await join_waiting_dice_from_dm(bot, client, call, game_id)
        except (httpx.HTTPStatusError, ValueError):
            await bot.answer_callback_query(
                call.id,
                "❌ Не удалось войти: дуэль уже занята, началась или ставка недоступна.",
                show_alert=True,
            )
            return
        except Exception:
            logger.exception("DM duel join failed game=%s user=%s", game_id, call.from_user.id)
            await bot.answer_callback_query(
                call.id,
                "❌ Не удалось войти в игру. Попробуйте позже.",
                show_alert=True,
            )
            return
        await bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: isinstance(call.data, str) and call.data.startswith("v2join:"))
    async def join_v2_table(call):
        table_id = call.data.split(":", 1)[1]
        try:
            table = await _find_table(client, table_id)
            if table is None:
                raise ValueError("Стол уже недоступен")
            result = await client.v2_table_operation(table_id, "seats", telegram_id=call.from_user.id, expected_state_version=_expected_version(table), idempotency_key=_idempotency("join", table_id, call.from_user.id))
            from games.v2_runtime import after_table_join
            join_chat_id = getattr(getattr(call, "message", None), "chat", None)
            join_chat_id = getattr(join_chat_id, "id", None)
            await after_table_join(
                bot, client, result if isinstance(result, dict) else {},
                join_chat_id=join_chat_id if isinstance(join_chat_id, int) and not isinstance(join_chat_id, bool) else None,
                user=call.from_user,
            )
        except httpx.HTTPStatusError:
            await bot.answer_callback_query(
                call.id,
                "❌ Не удалось войти: стол уже заполнен, начался или ставка недоступна.",
                show_alert=True,
            )
            return
        except ValueError:
            await _discard_callback_card(bot, call, table_id)
            await bot.answer_callback_query(
                call.id,
                "❌ Стол уже отменён или истёк. Если ставили — ставка вернулась на баланс.",
                show_alert=True,
            )
            return
        except Exception:
            logger.exception("V2 table join failed table=%s user=%s", table_id, call.from_user.id)
            await bot.answer_callback_query(
                call.id,
                "❌ Не удалось войти в игру. Попробуйте позже.",
                show_alert=True,
            )
            return
        await bot.answer_callback_query(call.id, "✅ Вы заняли место.")

    @bot.callback_query_handler(func=lambda call: isinstance(call.data, str) and call.data.startswith("v2bot:"))
    async def add_v2_bot(call):
        table_id = call.data.split(":", 1)[1]
        try:
            table = await _find_table(client, table_id)
            if table is None:
                raise ValueError("Стол уже недоступен")
            result = await client.v2_table_operation(
                table_id,
                "bots",
                telegram_id=call.from_user.id,
                expected_state_version=_expected_version(table),
                idempotency_key=_idempotency("add-bot", table_id, call.from_user.id),
            )
            from games.v2_runtime import after_table_join

            join_chat_id = getattr(getattr(call, "message", None), "chat", None)
            join_chat_id = getattr(join_chat_id, "id", None)
            await after_table_join(
                bot,
                client,
                result if isinstance(result, dict) else {},
                join_chat_id=join_chat_id if isinstance(join_chat_id, int) and not isinstance(join_chat_id, bool) else None,
                user=call.from_user,
            )
        except (httpx.HTTPStatusError, ValueError):
            await bot.answer_callback_query(
                call.id,
                "❌ Не удалось посадить бота. Нужно сидеть за столом, и должно быть свободное место.",
                show_alert=True,
            )
            return
        except Exception:
            logger.exception("V2 add bot failed table=%s user=%s", table_id, call.from_user.id)
            await bot.answer_callback_query(
                call.id,
                "❌ Не удалось посадить бота. Попробуйте позже.",
                show_alert=True,
            )
            return
        await bot.answer_callback_query(call.id, "✅ Бот сел за стол.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: isinstance(call.data, str) and call.data.startswith(("v2cancel:", "v2leave:")))
    async def leave_v2_table(call):
        operation, table_id = call.data.split(":", 1)
        table: dict[str, Any] | None = None
        try:
            table = await _find_table(client, table_id)
            if table is None:
                raise ValueError("Стол уже недоступен")
            endpoint = "cancel" if operation == "v2cancel" else "leave"
            await client.v2_table_operation(table_id, endpoint, telegram_id=call.from_user.id, expected_state_version=_expected_version(table), idempotency_key=_idempotency(endpoint, table_id, call.from_user.id))
        except (httpx.HTTPStatusError, ValueError):
            # A rejected cancellation is not proof that the table is terminal.
            # Keep its cards and recovery watcher until the backend confirms it.
            await bot.answer_callback_query(call.id, "❌ Это действие уже недоступно.", show_alert=True)
            return
        except Exception:
            logger.exception("V2 table leave failed table=%s user=%s", table_id, call.from_user.id)
            await bot.answer_callback_query(
                call.id,
                "❌ Не удалось выполнить действие. Попробуйте позже.",
                show_alert=True,
            )
            return
        if operation == "v2cancel":
            from games.v2_runtime import after_table_cancelled
            await after_table_cancelled(bot, client, table, origin=_callback_origin(call), table_id=table_id)
        text = "✅ Стол отменён, ставки освобождены." if operation == "v2cancel" else "✅ Вы вышли из стола, ставка освобождена."
        await bot.answer_callback_query(call.id, text, show_alert=True)


def create_payload(
    *,
    game_key: str,
    creator_id: int,
    stake: float,
    max_players: int,
    bot_count: int,
    draw_policy: str = "tie_break",
    game_chat_id: int | None = None,
    rounds: int = 1,
) -> dict[str, Any]:
    if game_key not in GAMES_CONFIG:
        raise ValueError("Unknown game type")
    if not 2 <= max_players <= 6 or not 0 <= bot_count < max_players:
        raise ValueError("Invalid V2 table setup")
    if draw_policy not in {"tie_break", "tie_split"}:
        raise ValueError("Invalid draw policy")
    if rounds not in {1, 2}:
        raise ValueError("Invalid roll count")
    try:
        amount = Decimal(str(stake))
    except InvalidOperation as exc:
        raise ValueError("Invalid stake") from exc
    if amount <= 0:
        raise ValueError("Invalid stake")
    payload = {
        "table_id": str(uuid.uuid4()), "game_type": GAMES_CONFIG[game_key]["game_type"],
        "creator_id": creator_id, "stake_rub": format(amount, ".2f"), "max_players": max_players,
        "bot_count": bot_count, "expected_state_version": 0,
        "idempotency_key": f"tg-create-{creator_id}-{uuid.uuid4().hex}",
        "draw_policy": draw_policy, "rounds": rounds,
    }
    if game_chat_id is not None:
        payload["game_chat_id"] = game_chat_id
    return payload
