"""One create-table wizard for group commands and the private menu."""
from __future__ import annotations

import contextlib
import logging
import time
import uuid
from decimal import Decimal
from typing import Any

from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from finance import casino_game_policy, validate_game_stake
from focuspay_client import FocusPayClient
from telegram_reliability import EntryDenied
from games.catalog import CARD_GAMES, FAMILIES, FAMILY_LABELS, GAMES_CONFIG, HUB_GAMES, game_key_for, is_card_game
from games.chat_guard import ActiveGameChatGuard, GAME_CHAT_REQUIRED_MESSAGE
from games.chat_reaper import try_delete_user_message
from games.stake_buttons import STAKE_PRESETS, is_private_chat
from games.v2_tables import create_payload

logger = logging.getLogger(__name__)

WIZARD_TTL_SECONDS = 600
_CREATE_ERROR_TEXT = {
    "V2 bot capacity is unavailable": "Нет бота для этой игры. В профиле pvp_robot должна быть эта игра, или создайте стол без ботов.",
    "Game type is disabled": "Эта игра выключена в настройках казино.",
    "Insufficient balance": "Недостаточно средств. Пополните баланс.",
    "V2 house bankroll is insufficient": "Недостаточно банка казино, чтобы посадить ботов.",
    "V2 robot concurrency limit reached": "Боты уже заняты в других играх.",
    "V2 robot exposure limit reached": "Лимит экспозиции ботов исчерпан.",
}
_sessions: dict[str, dict[str, Any]] = {}
_awaiting_custom: dict[int, str] = {}


def _v2_create_error_text(exc: BaseException) -> str:
    if isinstance(exc, EntryDenied):
        return f"❌ {exc}"
    detail = None
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail")
        if isinstance(detail, list) and detail:
            first = detail[0]
            detail = first.get("msg") if isinstance(first, dict) else first
        if isinstance(detail, dict):
            detail = detail.get("msg") or detail.get("detail")
    if isinstance(detail, str) and detail in _CREATE_ERROR_TEXT:
        return f"❌ {_CREATE_ERROR_TEXT[detail]}"
    if isinstance(detail, str) and detail.strip():
        return f"❌ Не удалось создать стол: {detail}"
    return "❌ Не удалось создать стол. Попробуйте позже."


def _prune(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [token for token, entry in _sessions.items() if entry["expires_at"] <= now]
    for token in expired:
        _sessions.pop(token, None)


def _issue(owner_id: int, **fields: Any) -> str:
    _prune()
    token = uuid.uuid4().hex[:12]
    payload = {key: value for key, value in fields.items() if value is not None}
    payload["owner_id"] = owner_id
    payload["expires_at"] = time.monotonic() + WIZARD_TTL_SECONDS
    _sessions[token] = payload
    return token


def _get(token: str, owner_id: int) -> dict[str, Any] | None:
    _prune()
    entry = _sessions.get(token)
    if entry is None or entry["owner_id"] != owner_id:
        return None
    return entry


def _consume(token: str, owner_id: int) -> dict[str, Any] | None:
    entry = _get(token, owner_id)
    if entry is None:
        return None
    _sessions.pop(token, None)
    return entry


def _cb(token: str) -> str:
    return f"tw:{token}"


def _carry(entry: dict[str, Any], *drop: str) -> dict[str, Any]:
    skip = {"owner_id", "expires_at", "step", *drop}
    return {key: value for key, value in entry.items() if key not in skip}


def _fields(entry: dict[str, Any], *drop: str, **override: Any) -> dict[str, Any]:
    return {**_carry(entry, *drop), **override}


class _CommandProxy:
    """Make a callback look like /roulette or /jackpot for existing command handlers."""

    def __init__(self, message: Any, user: Any, text: str) -> None:
        self.chat = getattr(message, "chat", None)
        self.from_user = user
        self.text = text
        self.message_id = getattr(message, "message_id", None)


def _type_keyboard(owner_id: int, *, chat_id: int | None) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for family in FAMILIES:
        emoji, name = FAMILY_LABELS[family]
        token = _issue(owner_id, step="type", family=family, chat_id=chat_id)
        keyboard.add(types.InlineKeyboardButton(f"{emoji} {name}", callback_data=_cb(token)))
    for hub, cfg in HUB_GAMES.items():
        token = _issue(owner_id, step="type", family=hub, chat_id=chat_id)
        keyboard.add(types.InlineKeyboardButton(f"{cfg['emoji']} {cfg['name']}", callback_data=_cb(token)))
    return keyboard


async def _dispatch_hub(bot: AsyncTeleBot, client: FocusPayClient, call: Any, family: str) -> None:
    """Open roulette/jackpot status or the rooms create flow. Never creates a V2 table."""
    user = getattr(call, "from_user", None)
    message = getattr(call, "message", None)
    if user is None or message is None:
        return
    if family == "rooms":
        from games.rooms import start_room_create

        await start_room_create(bot, client, call)
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


def _rolls_keyboard(owner_id: int, family: str, **fields: Any) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for rolls in (1, 2):
        token = _issue(owner_id, **{**fields, "step": "rolls", "family": family, "rolls": rolls})
        keyboard.add(types.InlineKeyboardButton(f"{rolls} броск{'а' if rolls == 2 else ''}", callback_data=_cb(token)))
    return keyboard


def _players_keyboard(owner_id: int, **fields: Any) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    for count in range(2, 7):
        token = _issue(owner_id, **{**fields, "step": "players", "max_players": count})
        keyboard.add(types.InlineKeyboardButton(f"{count}", callback_data=_cb(token)))
    return keyboard


def _bots_keyboard(owner_id: int, max_players: int, **fields: Any) -> types.InlineKeyboardMarkup:
    carried = {key: value for key, value in fields.items() if key != "max_players"}
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    token0 = _issue(owner_id, **{**carried, "step": "bots", "max_players": max_players, "bot_count": 0})
    keyboard.add(types.InlineKeyboardButton("Без ботов", callback_data=_cb(token0)))
    for bot_count in range(1, max_players):
        token = _issue(owner_id, **{**carried, "step": "bots", "max_players": max_players, "bot_count": bot_count})
        keyboard.add(types.InlineKeyboardButton(f"🤖 {bot_count}", callback_data=_cb(token)))
    return keyboard


def _draw_keyboard(owner_id: int, **fields: Any) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    for policy, label in (("tie_break", "Переброс лидеров"), ("tie_split", "Вернуть ставки")):
        token = _issue(owner_id, **{**fields, "step": "draw", "draw_policy": policy})
        keyboard.add(types.InlineKeyboardButton(label, callback_data=_cb(token)))
    return keyboard


def _stake_keyboard(owner_id: int, *, private: bool, **fields: Any) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    min_bet = Decimal(str(config.MIN_BET))
    for stake in STAKE_PRESETS:
        if Decimal(stake) < min_bet:
            continue
        token = _issue(owner_id, **{**fields, "step": "stake", "stake": Decimal(stake)})
        keyboard.add(types.InlineKeyboardButton(f"{stake} ₽", callback_data=_cb(token)))
    if private:
        token = _issue(owner_id, **{**fields, "step": "custom"})
        keyboard.add(types.InlineKeyboardButton("✏️ Своя сумма", callback_data=_cb(token)))
    return keyboard


def _confirm_keyboard(owner_id: int, **fields: Any) -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup()
    token = _issue(owner_id, **{**fields, "step": "confirm"})
    keyboard.add(types.InlineKeyboardButton("✅ Создать стол", callback_data=_cb(token)))
    keyboard.add(types.InlineKeyboardButton("✖️ Отмена", callback_data="tw:cancel"))
    return keyboard


async def _prompt_stake_or_confirm(bot: AsyncTeleBot, call: Any, entry: dict[str, Any]) -> None:
    if isinstance(entry.get("stake"), Decimal):
        await bot.edit_message_text(
            f"{_summary(entry)}\n\nСоздать стол? Ставка будет зарезервирована.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=_confirm_keyboard(call.from_user.id, **_carry(entry)),
        )
        return
    private = is_private_chat(call.message.chat, call.from_user)
    await bot.edit_message_text(
        f"{_summary(entry)}\n\nВыберите ставку:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML",
        reply_markup=_stake_keyboard(call.from_user.id, private=private, **_carry(entry)),
    )


def _summary(entry: dict[str, Any]) -> str:
    game_key = entry.get("game_key") or game_key_for(family=entry["family"], rolls=int(entry.get("rolls") or 0))
    cfg = GAMES_CONFIG[game_key]
    stake = entry.get("stake")
    stake_line = f"\nСтавка: <b>{stake:.2f} ₽</b>" if isinstance(stake, Decimal) else ""
    draw = {"tie_break": "переброс лидеров", "tie_split": "возврат ставок"}.get(entry.get("draw_policy"), "—")
    return (
        f"{cfg['emoji']} <b>{cfg['name']}</b>\n\n"
        f"Мест: {entry.get('max_players', '—')}\n"
        f"Ботов: {entry.get('bot_count', 0)}\n"
        f"Ничья: {draw}"
        f"{stake_line}"
    )


def _parse_command_stake(raw: str | None, *, game_type: str, settings: dict[str, Any]) -> Decimal | None:
    if raw is None:
        return None
    try:
        policy = casino_game_policy(settings, game_key=game_type)
        return validate_game_stake(policy=policy, stake_rub=raw)
    except Exception:
        return None


async def start_wizard(
    bot: AsyncTeleBot,
    client: FocusPayClient,
    message: Any,
    *,
    user: Any | None = None,
) -> None:
    """Open the wizard at game-type selection (private menu or empty command)."""
    actor = user or getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    if actor is None or chat is None:
        return
    guard = ActiveGameChatGuard(client)
    if not await guard.allows_entry(chat, actor):
        if user is None:
            await bot.send_message(chat.id, GAME_CHAT_REQUIRED_MESSAGE)
            await try_delete_user_message(bot, message)
        return
    chat_id = getattr(chat, "id", None)
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        chat_id = None
    await bot.send_message(
        chat.id,
        "🎮 <b>Создание стола</b>\n\nВыберите игру:",
        parse_mode="HTML",
        reply_markup=_type_keyboard(actor.id, chat_id=chat_id),
    )
    if user is None:
        await try_delete_user_message(bot, message)


async def start_wizard_for_command(
    bot: AsyncTeleBot,
    client: FocusPayClient,
    message: Any,
    game_key: str,
    *,
    user: Any | None = None,
) -> None:
    """Slash-command entry: /cub [stake] opens the same wizard at the next missing step."""
    actor = user or getattr(message, "from_user", None)
    guard = ActiveGameChatGuard(client)
    if actor is None or not await guard.allows_entry(getattr(message, "chat", None), actor):
        chat = getattr(message, "chat", None)
        if chat is not None and user is None:
            await bot.send_message(chat.id, GAME_CHAT_REQUIRED_MESSAGE)
            await try_delete_user_message(bot, message)
        return
    if game_key not in GAMES_CONFIG:
        if user is None:
            await try_delete_user_message(bot, message)
        return
    chat = message.chat
    chat_id = getattr(chat, "id", None)
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        chat_id = None
    cfg = GAMES_CONFIG[game_key]
    family = str(cfg["family"])
    rolls = int(cfg["rolls"])
    parts = str(getattr(message, "text", None) or "").split()
    stake = None
    if user is None and len(parts) >= 2:
        try:
            settings = await client.get_casino_settings()
        except Exception:
            settings = {}
        stake = _parse_command_stake(parts[1], game_type=str(cfg["game_type"]), settings=settings if isinstance(settings, dict) else {})
    fields: dict[str, Any] = {"family": family, "game_key": game_key, "chat_id": chat_id}
    if rolls:
        fields["rolls"] = rolls
    if stake is not None:
        fields["stake"] = stake
    prompt = (
        f"{cfg['emoji']} <b>{cfg['name']}</b>\n\nНа сколько игроков?"
        if is_card_game(game_key) or game_key.startswith("2")
        else f"{cfg['emoji']} <b>{cfg['name']}</b>\n\nСколько бросков?"
    )
    markup = (
        _players_keyboard(actor.id, **fields)
        if is_card_game(game_key) or game_key.startswith("2")
        else _rolls_keyboard(actor.id, family, chat_id=chat_id, **({"stake": stake} if stake is not None else {}))
    )
    if user is None:
        await bot.send_message(chat.id, prompt, parse_mode="HTML", reply_markup=markup)
        await try_delete_user_message(bot, message)
        return
    await bot.send_message(chat.id, prompt, parse_mode="HTML", reply_markup=markup)


async def _finalize(bot: AsyncTeleBot, client: FocusPayClient, call, entry: dict[str, Any]) -> bool:
    game_key = entry.get("game_key") or game_key_for(family=entry["family"], rolls=int(entry.get("rolls") or 0))
    stake = entry.get("stake")
    max_players = int(entry["max_players"])
    bot_count = int(entry["bot_count"])
    draw_policy = str(entry["draw_policy"])
    if not isinstance(stake, Decimal):
        await bot.answer_callback_query(call.id, "❌ Ставка не задана.", show_alert=True)
        return False
    from games.v2_runtime import publish_created_table
    game_chat_id = entry.get("chat_id")
    if not isinstance(game_chat_id, int) or isinstance(game_chat_id, bool):
        game_chat_id = getattr(getattr(call, "message", None), "chat", None)
        game_chat_id = getattr(game_chat_id, "id", None)
    if isinstance(game_chat_id, bool) or not isinstance(game_chat_id, int):
        game_chat_id = None
    rounds = 1 if is_card_game(game_key) else max(1, int(GAMES_CONFIG[game_key]["rolls"] or 1))
    try:
        # Freeze the confirmed request before the first network await. A lost
        # response (or a second click) must replay the same table/hold, not create
        # another game. The wizard entry belongs to this confirmation token.
        payload = entry.get("create_payload")
        if payload is None:
            payload = create_payload(
                game_key=game_key, creator_id=call.from_user.id, stake=float(stake),
                max_players=max_players, bot_count=bot_count, draw_policy=draw_policy,
                game_chat_id=game_chat_id, rounds=rounds,
            )
            entry["create_payload"] = payload
        result = await client.create_v2_table(**payload)
    except Exception as exc:
        logger.exception("V2 table create via wizard failed")
        await bot.answer_callback_query(call.id, _v2_create_error_text(exc)[:200], show_alert=True)
        return False
    table = result.get("table") if isinstance(result, dict) else None
    wizard_chat_id = getattr(getattr(call, "message", None), "chat", None)
    wizard_chat_id = getattr(wizard_chat_id, "id", None)
    wizard_msg_id = getattr(getattr(call, "message", None), "message_id", None)
    existing_message = None
    if (
        isinstance(game_chat_id, int)
        and wizard_chat_id == game_chat_id
        and isinstance(wizard_msg_id, int)
        and not isinstance(wizard_msg_id, bool)
    ):
        existing_message = (game_chat_id, wizard_msg_id)
    if isinstance(table, dict):
        await publish_created_table(
            bot, client, table, result=result, actor=call.from_user,
            existing_message=existing_message,
        )
    if existing_message is None and isinstance(wizard_chat_id, int) and isinstance(wizard_msg_id, int):
        with contextlib.suppress(Exception):
            await bot.delete_message(wizard_chat_id, wizard_msg_id)
    return True


def register_table_wizard_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    guard = ActiveGameChatGuard(client)

    @bot.callback_query_handler(func=lambda c: c.data == "tw:cancel")
    async def cancel(call):
        await bot.answer_callback_query(call.id)
        with contextlib.suppress(Exception):
            await bot.edit_message_text("❌ Создание стола отменено.", call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("tw:") and c.data != "tw:cancel")
    async def wizard_step(call):
        if not await guard.require_callback(bot, call):
            return
        token = str(call.data).split(":", 1)[1]
        entry = _get(token, call.from_user.id)
        if entry is None:
            await bot.answer_callback_query(call.id, "⌛ Мастер устарел. Начните заново.", show_alert=True)
            return
        step = entry.get("step")
        family = entry.get("family")
        if step == "type":
            if family in HUB_GAMES:
                await _dispatch_hub(bot, client, call, str(family))
                await bot.answer_callback_query(call.id)
                return
            if family in CARD_GAMES:
                await bot.edit_message_text(
                    f"{FAMILY_LABELS[family][0]} <b>{FAMILY_LABELS[family][1]}</b>\n\nНа сколько игроков?",
                    call.message.chat.id, call.message.message_id, parse_mode="HTML",
                    reply_markup=_players_keyboard(call.from_user.id, family=family, rolls=0, game_key=family, chat_id=entry.get("chat_id")),
                )
            else:
                await bot.edit_message_text(
                    f"{FAMILY_LABELS[family][0]} <b>{FAMILY_LABELS[family][1]}</b>\n\nСколько бросков?",
                    call.message.chat.id, call.message.message_id, parse_mode="HTML",
                    reply_markup=_rolls_keyboard(call.from_user.id, family, chat_id=entry.get("chat_id")),
                )
            await bot.answer_callback_query(call.id)
            return
        if step == "rolls":
            rolls = int(entry["rolls"])
            game_key = game_key_for(family=family, rolls=rolls)
            await bot.edit_message_text(
                f"{GAMES_CONFIG[game_key]['emoji']} <b>{GAMES_CONFIG[game_key]['name']}</b>\n\nНа сколько игроков?",
                call.message.chat.id, call.message.message_id, parse_mode="HTML",
                reply_markup=_players_keyboard(
                    call.from_user.id,
                    **_fields(entry, family=family, rolls=rolls, game_key=game_key),
                ),
            )
            await bot.answer_callback_query(call.id)
            return
        if step == "players":
            filled = _fields(entry, bot_count=0)
            if str(family) == "baccara":
                await _prompt_stake_or_confirm(bot, call, {**filled, "draw_policy": "tie_break"})
                await bot.answer_callback_query(call.id)
                return
            await bot.edit_message_text(
                f"{_summary({**entry, 'bot_count': 0})}\n\nЧто делать при ничьей?",
                call.message.chat.id, call.message.message_id, parse_mode="HTML",
                reply_markup=_draw_keyboard(call.from_user.id, **filled),
            )
            await bot.answer_callback_query(call.id)
            return
        if step == "bots":
            if str(family) == "baccara":
                await _prompt_stake_or_confirm(bot, call, {**_carry(entry), "draw_policy": "tie_break"})
                await bot.answer_callback_query(call.id)
                return
            await bot.edit_message_text(
                f"{_summary(entry)}\n\nЧто делать при ничьей?",
                call.message.chat.id, call.message.message_id, parse_mode="HTML",
                reply_markup=_draw_keyboard(call.from_user.id, **_carry(entry)),
            )
            await bot.answer_callback_query(call.id)
            return
        if step == "draw":
            await _prompt_stake_or_confirm(bot, call, entry)
            await bot.answer_callback_query(call.id)
            return
        if step == "custom":
            if not is_private_chat(call.message.chat, call.from_user):
                await bot.answer_callback_query(call.id, "Свою сумму можно ввести только в личке.", show_alert=True)
                return
            token = _issue(call.from_user.id, **{**_carry(entry), "step": "await_stake"})
            _awaiting_custom[call.from_user.id] = token
            await bot.send_message(call.message.chat.id, f"✏️ Отправьте сумму ставки (минимум {config.MIN_BET:.0f} ₽).")
            await bot.answer_callback_query(call.id)
            return
        if step == "stake":
            await bot.edit_message_text(
                f"{_summary(entry)}\n\nСоздать стол? Ставка будет зарезервирована.",
                call.message.chat.id, call.message.message_id, parse_mode="HTML",
                reply_markup=_confirm_keyboard(call.from_user.id, **_carry(entry)),
            )
            await bot.answer_callback_query(call.id)
            return
        if step != "confirm":
            await bot.answer_callback_query(call.id, "❌ Некорректный шаг.", show_alert=True)
            return
        # Consume the confirmation first: the payload stays frozen for the
        # retry path, but a second click after success must not publish a
        # second board for the same committed hold.
        confirmed = _consume(token, call.from_user.id)
        if confirmed is None:
            await bot.answer_callback_query(call.id, "⌛ Подтверждение уже использовано. Проверьте «Мои игры».", show_alert=True)
            return
        if await _finalize(bot, client, call, confirmed):
            await bot.answer_callback_query(call.id)

    @bot.message_handler(
        func=lambda m: is_private_chat(getattr(m, "chat", None), getattr(m, "from_user", None))
        and getattr(getattr(m, "from_user", None), "id", None) in _awaiting_custom
        and isinstance(getattr(m, "text", None), str)
        and not str(m.text).startswith("/"),
        content_types=["text"],
    )
    async def custom_stake_text(message):
        token = _awaiting_custom.pop(message.from_user.id, None)
        entry = _get(token, message.from_user.id) if token else None
        if entry is None or entry.get("step") != "await_stake":
            await bot.reply_to(message, "⌛ Ввод ставки устарел. Начните заново.")
            return
        try:
            game_key = entry.get("game_key") or game_key_for(family=entry["family"], rolls=int(entry.get("rolls") or 0))
            policy = casino_game_policy(await client.get_casino_settings(), game_key=GAMES_CONFIG[game_key]["game_type"])
            stake = validate_game_stake(policy=policy, stake_rub=str(message.text).replace(",", ".").replace(" ", ""))
        except Exception:
            await bot.reply_to(message, "❌ Неверная ставка. Начните заново.")
            return
        entry["stake"] = stake
        await bot.reply_to(
            message, f"{_summary(entry)}\n\nСоздать стол?", parse_mode="HTML",
            reply_markup=_confirm_keyboard(message.from_user.id, **_fields(entry, stake=stake)),
        )
