"""Durable PVP emoji games for FocusPay Casino.

The backend owns the game and all funds. ``active_games`` is only a UI cache;
every state transition is written through the game-level lifecycle first.
"""
import asyncio
import contextlib
import logging
import secrets
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict

from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from finance import casino_game_policy, settlement_payout_rub, validate_game_stake
from focuspay_client import FocusPayClient
from games.catalog import CARD_GAMES, EMOJI_GAMES, GAMES_CONFIG, fmt_id
from games.chat_guard import ActiveGameChatGuard
from games.house_cub import try_handle_house_cub_dice
from games.dice_timing import wait_dice_landed
from games.site_links import add_watch_button, append_watch_line, duel_url, watch_keyboard
from games.table_wizard import start_wizard, start_wizard_for_command
from games.v2_runtime import try_handle_v2_dice

active_games: Dict[str, dict] = {}
_roll_game_ids: Dict[tuple[int, int], str] = {}
_game_locks: Dict[str, asyncio.Lock] = {}
_private_lobby_tokens: Dict[str, dict] = {}
_private_create_tokens: Dict[str, dict] = {}
_private_create_amount_inputs: Dict[int, dict] = {}
MAX_ACTIVE_PER_USER = 3
PRIVATE_LOBBY_PAGE_SIZE = 5
PRIVATE_LOBBY_TOKEN_TTL_SECONDS = 300
logger = logging.getLogger(__name__)


def _is_group_chat_id(chat_id: object) -> bool:
    return isinstance(chat_id, int) and not isinstance(chat_id, bool) and chat_id < 0


def _play_chat_id(game: dict | None, *, prefer: object = None) -> int | None:
    """Prefer a Telegram group over a DM user id."""
    game = game or {}
    candidates = (prefer, game.get("game_chat_id"), game.get("chat_id"))
    for candidate in candidates:
        if _is_group_chat_id(candidate):
            return int(candidate)
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return int(candidate)
    return None


def _bind_play_chat(game: dict, *, prefer: object = None) -> int | None:
    play = _play_chat_id(game, prefer=prefer)
    if isinstance(play, int):
        game["chat_id"] = play
        if _is_group_chat_id(play):
            game["game_chat_id"] = play
    return play


def get_game_lock(game_id: str) -> asyncio.Lock:
    return _game_locks.setdefault(game_id, asyncio.Lock())


def _index_roll_message(game_id: str, game: dict) -> None:
    """Index every permitted roll prompt, including one prompt per DM player."""
    prompts = game.get("dm_roll_prompts")
    if isinstance(prompts, dict):
        for raw_player_id, raw_message_id in prompts.items():
            try:
                player_id, message_id = int(raw_player_id), int(raw_message_id)
            except (TypeError, ValueError):
                continue
            _roll_game_ids[(player_id, message_id)] = game_id
        return
    chat_id = game.get("chat_id")
    roll_msg_id = game.get("roll_msg_id")
    if isinstance(chat_id, int) and isinstance(roll_msg_id, int):
        _roll_game_ids[(chat_id, roll_msg_id)] = game_id


def _unindex_roll_messages(game_id: str, game: dict) -> None:
    _roll_game_ids_keys = [key for key, value in _roll_game_ids.items() if value == game_id]
    for key in _roll_game_ids_keys:
        _roll_game_ids.pop(key, None)


def _rolling_game_for_thrower(
    chat_id: int,
    actor_id: int,
    emoji: str | None,
    *,
    require_same_chat: bool = True,
) -> tuple[str, dict] | tuple[None, None]:
    found: list[tuple[str, dict]] = []
    for game_id, game in active_games.items():
        if game.get("status") != "rolling":
            continue
        if require_same_chat and game.get("chat_id") != chat_id:
            continue
        if actor_id not in {game.get("creator_id"), game.get("opponent_id")}:
            continue
        game_type = game.get("game_type")
        if game_type not in GAMES_CONFIG:
            continue
        if emoji and GAMES_CONFIG[game_type]["emoji"] != emoji:
            continue
        found.append((game_id, game))
    needing: list[tuple[str, dict]] = []
    for game_id, game in found:
        side = "creator" if actor_id == game.get("creator_id") else "opponent"
        needed = GAMES_CONFIG[game["game_type"]]["rolls"]
        if len(game.get(f"{side}_rolls") or []) < needed:
            needing.append((game_id, game))
    pool = needing or found
    return pool[0] if pool else (None, None)


async def _record_private_dice_via_api(client, actor_id: int, value: int) -> dict | None:
    """Backend-owned active duel: accept a DM dice even if the UI cache is cold."""
    getter = getattr(client, "get_active_pvp_games", None)
    record_fn = getattr(client, "record_pvp_dice_roll", None)
    if not callable(getter) or not callable(record_fn):
        return None
    try:
        durable_games = await getter()
    except Exception:
        logger.exception("PVP private dice lookup failed actor_id=%s", actor_id)
        return None
    if not isinstance(durable_games, list):
        return None
    for durable in durable_games:
        if not isinstance(durable, dict):
            continue
        if str(durable.get("game_type") or "") != "pvp_dice":
            continue
        if str(durable.get("status") or "") != "active":
            continue
        if actor_id not in {durable.get("creator_id"), durable.get("opponent_id")}:
            continue
        game_id = durable.get("game_id")
        if not isinstance(game_id, str):
            continue
        state = durable.get("game_state") if isinstance(durable.get("game_state"), dict) else {}
        if _is_group_chat_id(durable.get("game_chat_id")) or _is_group_chat_id(state.get("chat_id")):
            continue
        try:
            return await record_fn(game_id=game_id, telegram_id=int(actor_id), value=int(value))
        except Exception:
            logger.exception("PVP private dice record-roll failed game_id=%s", game_id)
            continue
    return None


def _hydrate_game(durable: dict) -> tuple[str, dict] | None:
    """Validate a stored UI snapshot against the authoritative lifecycle row."""
    game_id = durable.get("game_id")
    state = durable.get("game_state")
    canonical_type = durable.get("game_type")
    durable_status = durable.get("status")
    if not isinstance(game_id, str) or not isinstance(state, dict):
        return None
    if canonical_type in CARD_GAMES:
        return None
    if canonical_type not in {cfg["game_type"] for cfg in EMOJI_GAMES.values()}:
        return None
    game_type = state.get("game_type")
    if game_type not in GAMES_CONFIG or GAMES_CONFIG[game_type]["game_type"] != canonical_type:
        return None
    chat_id = _play_chat_id(
        {"chat_id": state.get("chat_id"), "game_chat_id": durable.get("game_chat_id")},
    )
    message_id = state.get("message_id")
    roll_msg_id = state.get("roll_msg_id")
    if not isinstance(chat_id, int):
        return None
    try:
        stake = Decimal(str(durable.get("stake_rub")))
    except Exception:
        return None
    game = {**state}
    game.update(
        game_id=game_id,
        game_type=game_type,
        creator_id=durable.get("creator_id"),
        opponent_id=durable.get("opponent_id"),
        counterparty_kind=durable.get("counterparty_kind", "player"),
        bet=stake,
        state_version=durable.get("state_version"),
        durable_status=durable_status,
    )
    if not isinstance(game["creator_id"], int) or not isinstance(game["state_version"], int):
        return None
    creator_rolls = game.get("creator_rolls")
    opponent_rolls = game.get("opponent_rolls")
    if not all(isinstance(rolls, list) and all(isinstance(value, int) for value in rolls) for rolls in (creator_rolls, opponent_rolls)):
        return None
    rolls_needed = GAMES_CONFIG[game_type]["rolls"]
    if len(creator_rolls) > rolls_needed or len(opponent_rolls) > rolls_needed:
        return None
    if durable_status == "waiting":
        if not isinstance(message_id, int):
            return None
        game["status"] = "waiting"
    elif durable_status == "active":
        robot = str(durable.get("counterparty_kind") or game.get("counterparty_kind") or "player") == "pvp_robot"
        if not robot and not isinstance(game["opponent_id"], int):
            return None
        game["status"] = "rolling"
    else:
        return None
    game["chat_id"] = chat_id
    _bind_play_chat(game)
    return game_id, game


async def hydrate_active_pvp_games(client: FocusPayClient) -> int:
    """Restore only complete, authoritative PVP snapshots before polling starts."""
    durable_games = await client.get_active_pvp_games()
    active_games.clear()
    _roll_game_ids.clear()
    _game_locks.clear()
    _private_lobby_tokens.clear()
    _private_create_tokens.clear()
    _private_create_amount_inputs.clear()
    hydrated = 0
    for durable in durable_games:
        if str(durable.get("game_type") or "") in CARD_GAMES:
            continue
        restored = _hydrate_game(durable)
        if restored is None:
            logger.warning("Skipping incomplete PVP snapshot game_id=%s", durable.get("game_id"))
            continue
        game_id, game = restored
        active_games[game_id] = game
        if game["status"] == "rolling":
            _index_roll_message(game_id, game)
        hydrated += 1
    logger.info("Hydrated %s active PVP game(s)", hydrated)
    return hydrated


def adopt_waiting_dice_from_durable(durable: dict, *, chat_id: int | None = None) -> tuple[str, dict] | None:
    """Put a waiting backend dice duel into the UI cache even without a group card."""
    game_id = durable.get("game_id")
    if not isinstance(game_id, str) or str(durable.get("status") or "") != "waiting":
        return None
    if str(durable.get("game_type") or "") != "pvp_dice":
        return None
    key = _pvp_key_for_canonical_type("pvp_dice", durable.get("rounds") or 1)
    if key is None:
        return None
    cached = active_games.get(game_id)
    if isinstance(cached, dict) and cached.get("status") == "waiting":
        _bind_play_chat(cached, prefer=chat_id)
        return game_id, cached
    try:
        stake = Decimal(str(durable.get("stake_rub")))
        version = int(durable.get("state_version"))
        creator_id = int(durable.get("creator_id"))
    except Exception:
        return None
    if creator_id <= 0:
        return None
    pinned = durable.get("game_chat_id")
    game = {
        "game_id": game_id,
        "game_type": key,
        "creator_id": creator_id,
        "creator_name": f"Игрок {creator_id}",
        "opponent_id": None,
        "opponent_name": "Ожидание...",
        "bet": stake,
        "chat_id": chat_id if isinstance(chat_id, int) else (pinned if isinstance(pinned, int) else None),
        "message_id": None,
        "roll_msg_id": None,
        "creator_rolls": [],
        "opponent_rolls": [],
        "status": "waiting",
        "state_version": version,
        "durable_status": "waiting",
        "game_chat_id": pinned if isinstance(pinned, int) else None,
        "game_chat_binding_id": durable.get("game_chat_binding_id"),
    }
    _bind_play_chat(game, prefer=chat_id)
    active_games[game_id] = game
    return game_id, game


def _watch_send_kwargs(game_id: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"parse_mode": "HTML"}
    markup = watch_keyboard(duel_url(game_id))
    if markup is not None:
        kwargs["reply_markup"] = markup
    return kwargs


async def join_waiting_dice_from_dm(bot: AsyncTeleBot, client: FocusPayClient, call, game_id: str) -> None:
    """Join a waiting 1x1 dice duel from the player's DM lobby."""
    chat = getattr(getattr(call, "message", None), "chat", None)
    user = getattr(call, "from_user", None)
    chat_id = getattr(chat, "id", None)
    user_id = getattr(user, "id", None)
    if getattr(chat, "type", None) != "private" or chat_id != user_id or not isinstance(user_id, int):
        raise ValueError("dice duel join is only available in the player's DM")
    durable = next(
        (item for item in await client.get_active_pvp_games() if str(item.get("game_id")) == game_id),
        None,
    )
    if not isinstance(durable, dict):
        raise ValueError("duel is no longer waiting")
    adopted = adopt_waiting_dice_from_durable(durable, chat_id=chat_id)
    if adopted is None:
        raise ValueError("duel is no longer waiting")
    game_id, game = adopted
    if user_id == game.get("creator_id"):
        raise ValueError("cannot join own duel")
    async with get_game_lock(game_id):
        game = active_games.get(game_id) or game
        if game.get("status") != "waiting" or game.get("opponent_id") is not None:
            raise ValueError("duel is no longer waiting")
        play_chat = _bind_play_chat(game, prefer=chat_id)
        game.update(status="joining", joining_opponent_id=user_id, chat_id=play_chat)
        join_completed = False
        try:
            await _persist(client, game_id, game)
            response = await client.join_and_hold_game(game_id=game_id, opponent_id=user_id)
            _apply_response(game, response)
            join_completed = True
            game.update(
                opponent_id=user_id,
                opponent_name=uname(user),
                status="rolling",
                joining_opponent_id=None,
                chat_id=play_chat,
            )
            await _persist(client, game_id, game)
        except Exception:
            if not join_completed:
                game["status"] = "waiting"
                game.pop("joining_opponent_id", None)
            else:
                game["status"] = "recovery_pending"
            raise
        await ensure_roll_prompt(bot, client, game_id, game)
    prompt = (
        "✅ Вы в игре! Киньте 🎲 в игровом чате."
        if _is_group_chat_id(play_chat)
        else "✅ Вы в игре! Киньте 🎲 в этот чат."
    )
    await bot.send_message(
        chat_id,
        append_watch_line(prompt, duel_url(game_id)),
        **_watch_send_kwargs(game_id),
    )


async def ensure_roll_prompt(bot: AsyncTeleBot, client: FocusPayClient, game_id: str, game: dict) -> None:
    if game.get("status") != "rolling" or isinstance(game.get("roll_msg_id"), int):
        return
    chat_id = game.get("chat_id")
    if not isinstance(chat_id, int):
        return
    try:
        roll_message = await bot.send_message(
            chat_id, build_roll_text(game, game_id), **_watch_send_kwargs(game_id)
        )
        game["roll_msg_id"] = roll_message.message_id
        await _persist(client, game_id, game)
        _index_roll_message(game_id, game)
    except Exception:
        logger.exception("PVP roll prompt after web join failed game_id=%s", game_id)


async def sync_active_pvp_from_backend(bot: AsyncTeleBot, client: FocusPayClient) -> int:
    """Pick up web joins the in-memory cache never saw."""
    durable_games = await client.get_active_pvp_games()
    if not isinstance(durable_games, list):
        return 0
    synced = 0
    for durable in durable_games:
        if str(durable.get("status") or "") != "active":
            continue
        restored = _hydrate_game(durable)
        if restored is None:
            continue
        game_id, game = restored
        cached = active_games.get(game_id)
        if cached is None or cached.get("status") == "waiting":
            active_games[game_id] = game
            await ensure_roll_prompt(bot, client, game_id, game)
            synced += 1
            continue
        state = durable.get("game_state") if isinstance(durable.get("game_state"), dict) else {}
        for key in ("creator_rolls", "opponent_rolls"):
            incoming = state.get(key)
            if isinstance(incoming, list) and len(incoming) >= len(cached.get(key) or []):
                cached[key] = incoming
        version = durable.get("state_version")
        if isinstance(version, int):
            cached["state_version"] = version
        if not isinstance(cached.get("roll_msg_id"), int):
            await ensure_roll_prompt(bot, client, game_id, cached)
            synced += 1
    return synced


def _drop_cache(game_id: str) -> None:
    """Forget only terminal games; authoritative state remains on the backend."""
    game = active_games.pop(game_id, None)
    if game:
        chat_id = game.get("chat_id")
        roll_msg_id = game.get("roll_msg_id")
        if isinstance(chat_id, int) and isinstance(roll_msg_id, int):
            _roll_game_ids.pop((chat_id, roll_msg_id), None)
    _game_locks.pop(game_id, None)


def _prune_private_lobby_tokens(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [token for token, entry in _private_lobby_tokens.items() if entry["expires_at"] <= now]
    for token in expired:
        _private_lobby_tokens.pop(token, None)


def _issue_private_lobby_token(*, owner_id: int, game_id: str, page: int) -> str:
    _prune_private_lobby_tokens()
    token = secrets.token_urlsafe(12)
    _private_lobby_tokens[token] = {
        "owner_id": owner_id,
        "game_id": game_id,
        "page": page,
        "expires_at": time.monotonic() + PRIVATE_LOBBY_TOKEN_TTL_SECONDS,
    }
    return token


def _get_private_lobby_token(token: str, *, owner_id: int) -> dict | None:
    _prune_private_lobby_tokens()
    entry = _private_lobby_tokens.get(token)
    if entry is None or entry["owner_id"] != owner_id:
        return None
    return entry


def _waiting_pvp_games(*, owner_id: int | None = None) -> list[tuple[str, dict]]:
    supported_types = set(GAMES_CONFIG)
    rows: list[tuple[str, dict]] = []
    for game_id, game in active_games.items():
        if game.get("status") != "waiting":
            continue
        if game.get("opponent_id") is not None:
            continue
        if game.get("game_type") not in supported_types:
            continue
        if owner_id is not None and game.get("creator_id") == owner_id:
            continue
        rows.append((game_id, game))
    return rows


def _private_waiting_games(owner_id: int) -> list[tuple[str, dict]]:
    return _waiting_pvp_games(owner_id=owner_id)


def _lobby_page_slice(total: int, page: int) -> tuple[int, int]:
    if total <= 0:
        return 0, 0
    last = (total - 1) // PRIVATE_LOBBY_PAGE_SIZE
    page = max(0, min(int(page), last))
    start = page * PRIVATE_LOBBY_PAGE_SIZE
    return page, start


def _lobby_button_label(index: int, game: dict) -> str:
    cfg = GAMES_CONFIG.get(game.get("game_type"), {"emoji": "🎮", "name": "Игра"})
    try:
        stake = Decimal(str(game.get("bet") or "0"))
    except Exception:
        stake = Decimal("0")
    stake_text = f"{stake:.0f} ₽" if stake == stake.to_integral() else f"{stake:.2f} ₽"
    who = " ".join(str(game.get("creator_name") or "Игрок").split()) or "Игрок"
    if len(who) > 16:
        who = who[:15] + "…"
    return f"{index}. {cfg['emoji']} {cfg['name']} · {stake_text} · {who}"[:64]


def _add_lobby_nav(
    keyboard: types.InlineKeyboardMarkup,
    *,
    total: int,
    page: int,
    start: int,
    previous_data: str | None,
    next_data: str | None,
    refresh_data: str | None,
) -> None:
    if page > 0 and previous_data:
        keyboard.add(types.InlineKeyboardButton("◀️ Назад", callback_data=previous_data))
    if start + PRIVATE_LOBBY_PAGE_SIZE < total and next_data:
        keyboard.add(types.InlineKeyboardButton("Далее ▶️", callback_data=next_data))
    if refresh_data:
        keyboard.add(types.InlineKeyboardButton("🔄 Обновить", callback_data=refresh_data))


def _is_unchanged_telegram_message(exc: BaseException) -> bool:
    return "message is not modified" in str(exc).lower()


def _lobby_caption(*, empty_text: str, waiting: list, page: int) -> str:
    if not waiting:
        return empty_text
    pages = max(1, (len(waiting) + PRIVATE_LOBBY_PAGE_SIZE - 1) // PRIVATE_LOBBY_PAGE_SIZE)
    page, _start = _lobby_page_slice(len(waiting), page)
    lines = [
        "🎮 <b>Ожидающие игры</b>",
        "Нажмите на игру, чтобы войти.",
    ]
    if pages > 1:
        lines.append(f"Стр. {page + 1}/{pages}")
    return "\n".join(lines)


def _private_lobby_keyboard(owner_id: int, page: int) -> types.InlineKeyboardMarkup | None:
    waiting = _private_waiting_games(owner_id)
    page, start = _lobby_page_slice(len(waiting), page)
    page_games = waiting[start:start + PRIVATE_LOBBY_PAGE_SIZE]
    if not page_games:
        return None
    keyboard = types.InlineKeyboardMarkup()
    for offset, (game_id, game) in enumerate(page_games, start=1):
        token = _issue_private_lobby_token(owner_id=owner_id, game_id=game_id, page=page)
        keyboard.add(types.InlineKeyboardButton(
            _lobby_button_label(start + offset, game),
            callback_data=f"dmjoin:{token}",
        ))
    next_token = _issue_private_lobby_token(owner_id=owner_id, game_id="", page=page + 1)
    previous_token = _issue_private_lobby_token(owner_id=owner_id, game_id="", page=page - 1)
    refresh_token = _issue_private_lobby_token(owner_id=owner_id, game_id="", page=page)
    _add_lobby_nav(
        keyboard,
        total=len(waiting),
        page=page,
        start=start,
        previous_data=f"dmpage:{previous_token}",
        next_data=f"dmpage:{next_token}",
        refresh_data=f"dmpage:{refresh_token}",
    )
    return keyboard


def _private_lobby_text(owner_id: int, page: int) -> str:
    return _lobby_caption(
        empty_text="📭 Сейчас нет доступных ожидающих игр. Обновите список чуть позже.",
        waiting=_private_waiting_games(owner_id),
        page=page,
    )


def _group_lobby_keyboard(owner_id: int, page: int) -> types.InlineKeyboardMarkup | None:
    waiting = _waiting_pvp_games(owner_id=owner_id)
    page, start = _lobby_page_slice(len(waiting), page)
    page_games = waiting[start:start + PRIVATE_LOBBY_PAGE_SIZE]
    if not page_games:
        return None
    keyboard = types.InlineKeyboardMarkup()
    for offset, (game_id, game) in enumerate(page_games, start=1):
        keyboard.add(types.InlineKeyboardButton(
            _lobby_button_label(start + offset, game),
            callback_data=f"join_{game_id}",
        ))
    _add_lobby_nav(
        keyboard,
        total=len(waiting),
        page=page,
        start=start,
        previous_data=f"agpage:{page - 1}",
        next_data=f"agpage:{page + 1}",
        refresh_data=f"agpage:{page}",
    )
    return keyboard


def _group_lobby_text(owner_id: int, page: int) -> str:
    return _lobby_caption(
        empty_text="📭 Нет активных игр. Создайте новую командой из списка /help.",
        waiting=_waiting_pvp_games(owner_id=owner_id),
        page=page,
    )


async def send_private_lobby(bot: AsyncTeleBot, chat_id: int, owner_id: int, *, page: int = 0) -> None:
    """Публичная точка входа: показать лобби ожидающих игр в личном чате.

    Лобби едино для DM- и групповых игр: ``active_games`` содержит оба контекста.
    """
    await bot.send_message(
        chat_id,
        _private_lobby_text(owner_id, page=page),
        parse_mode="HTML",
        reply_markup=_private_lobby_keyboard(owner_id, page=page),
    )


def private_waiting_games_count(owner_id: int) -> int:
    """Сколько ожидающих игр доступно игроку для входа."""
    return len(_private_waiting_games(owner_id))


def own_active_games(owner_id: int) -> list[tuple[str, dict]]:
    """Игры, где пользователь участвует и которые ещё не завершены."""
    return [
        (game_id, game)
        for game_id, game in active_games.items()
        if game.get("status") in {"waiting", "playing", "running", "rolling"}
        and owner_id in {game.get("creator_id"), game.get("opponent_id")}
    ]


def own_active_games_text(owner_id: int) -> str:
    """Текст со списком своих активных игр."""
    games = own_active_games(owner_id)
    if not games:
        return "📭 У вас нет активных игр. Создайте новую или найдите игру в лобби."
    lines = ["🎲 <b>Ваши активные игры</b>"]
    for game_id, game in games:
        cfg = GAMES_CONFIG.get(game.get("game_type"), {})
        status = game.get("status")
        label = {
            "waiting": "ждёт оппонента",
            "playing": "идёт игра",
            "running": "идёт игра",
        }.get(status, str(status))
        lines.append(
            f"• #{fmt_id(game_id)} {cfg.get('emoji', '🎮')} {cfg.get('name', game.get('game_type'))}"
            f" — {game.get('bet', 0):.2f} ₽ — {label}"
        )
    return "\n".join(lines)


def _safe_game_error(exc: Exception) -> str:
    logger.exception("Casino game action failed", exc_info=exc)
    return "❌ Действие временно недоступно. Попробуйте ещё раз позже."


def _pvp_key_for_canonical_type(canonical_type: str, rounds) -> str | None:
    canonical = str(canonical_type or "")
    if canonical in CARD_GAMES:
        return canonical
    try:
        rolls = int(rounds)
    except (TypeError, ValueError):
        rolls = 1
    return next(
        (
            key for key, cfg in GAMES_CONFIG.items()
            if cfg["game_type"] == canonical and cfg["rolls"] == rolls
        ),
        None,
    )


async def _hydrate_invited_game(client: FocusPayClient, payload: dict, telegram_message_id: int) -> dict:
    game_id = str(payload["game_id"])
    durable = next(
        (item for item in await client.get_active_pvp_games() if str(item.get("game_id")) == game_id),
        None,
    )
    if not isinstance(durable, dict) or durable.get("status") != "waiting":
        raise ValueError("Invitation game is no longer a waiting game")
    rounds = payload.get("rounds")
    key = _pvp_key_for_canonical_type(str(payload.get("game_type")), rounds)
    chat_id = payload.get("chat_id")
    if key is None or not isinstance(chat_id, int) or not isinstance(durable.get("state_version"), int):
        raise ValueError("Invitation payload or lifecycle game is invalid")
    stake = Decimal(str(payload.get("stake_rub")))
    game = {
        "game_id": game_id, "game_type": key, "creator_id": durable.get("creator_id"),
        "creator_name": f"Игрок {durable.get('creator_id')}", "opponent_id": None,
        "opponent_name": "Ожидание...", "bet": stake, "chat_id": chat_id,
        "message_id": telegram_message_id, "roll_msg_id": None, "creator_rolls": [],
        "opponent_rolls": [], "status": "waiting", "state_version": durable["state_version"],
        "durable_status": "waiting", "game_chat_id": durable.get("game_chat_id"),
        "game_chat_binding_id": durable.get("game_chat_binding_id"),
    }
    await _persist(client, game_id, game)
    active_games[game_id] = game
    return game


async def run_pvp_invitation_pass(bot: AsyncTeleBot, client: FocusPayClient, *, worker_id: str, limit: int = 50, lease_seconds: int = 60) -> int:
    response = await client.claim_pvp_invitations(worker_id=worker_id, limit=limit, lease_seconds=lease_seconds)
    if not isinstance(response, dict) or response.get("success") is not True or not isinstance(response.get("items"), list):
        raise ValueError("PVP invitation claim response is invalid")
    processed = 0
    for item in response["items"]:
        outbox_id, claim_token, payload = item.get("outbox_id"), item.get("claim_token"), item.get("payload")
        if not isinstance(outbox_id, int) or not isinstance(claim_token, str) or not isinstance(payload, dict):
            raise ValueError("PVP invitation item is invalid")
        try:
            game_id, chat_id = str(payload["game_id"]), payload["chat_id"]
            key = _pvp_key_for_canonical_type(str(payload.get("game_type")), payload.get("rounds"))
            if key is None or not isinstance(chat_id, int):
                raise ValueError("PVP invitation has unsupported game configuration")
            cfg = GAMES_CONFIG[key]
            stake = Decimal(str(payload["stake_rub"]))
            if key in CARD_GAMES:
                from games.card_invite import join_callback_data
                callback_data = join_callback_data(key, game_id)
            else:
                callback_data = f"join_{game_id}"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("✅ Принять игру", callback_data=callback_data))
            add_watch_button(keyboard, duel_url(game_id))
            message = await bot.send_message(
                chat_id,
                append_watch_line(
                    f"{cfg['emoji']} <b>GAME #{fmt_id(game_id)}</b> — {cfg['name']}\n\n"
                    f"Игроки:\n  • Игрок {payload['creator_id']} [✅]\n  • Ожидание...\n\n💰 Ставка: {stake:.2f} ₽",
                    duel_url(game_id),
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            await client.complete_pvp_invitation(
                outbox_id=outbox_id, claim_token=claim_token, telegram_message_id=message.message_id
            )
            if key in CARD_GAMES:
                import importlib
                from games.card_invite import hydrate_invited_card_game
                await hydrate_invited_card_game(
                    client, payload, message.message_id,
                    module=importlib.import_module(f"games.{key}"),
                )
            else:
                await _hydrate_invited_game(client, payload, message.message_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("PVP invitation delivery failed for %s", outbox_id, exc_info=True)
            await client.fail_pvp_invitation(outbox_id=outbox_id, claim_token=claim_token, error=str(exc))
        processed += 1
    return processed


async def pvp_invitation_loop(bot: AsyncTeleBot, client: FocusPayClient, *, worker_id: str) -> None:
    while True:
        try:
            await run_pvp_invitation_pass(bot, client, worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("PVP invitation pass failed; work remains retryable")
        await asyncio.sleep(15)


def uname(user) -> str:
    return f"@{user.username}" if user.username else user.first_name or f"User{user.id}"


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items() if key != "state_version"}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _snapshot(game: dict) -> dict:
    """A complete, JSON-safe recovery snapshot, including the Telegram UI mapping."""
    return _json_value(game)


def _apply_response(game: dict, response: dict) -> dict:
    durable = response.get("game", response)
    version = durable.get("state_version", response.get("state_version"))
    if version is None:
        raise RuntimeError("lifecycle response has no state_version")
    game["state_version"] = version
    if "financial_state" in durable:
        game["financial_state"] = durable["financial_state"]
    if "status" in durable:
        game["durable_status"] = durable["status"]
    return durable


async def _persist(client: FocusPayClient, game_id: str, game: dict) -> dict:
    response = await client.persist_game_state(
        game_id=game_id,
        expected_state_version=game["state_version"],
        game_state=_snapshot(game),
    )
    return _apply_response(game, response)


_TERMINAL_STATUSES = frozenset({
    "settled", "finished", "released", "cancelled", "canceled", "expired", "closed", "completed",
})


def _terminal_response(response: dict) -> bool:
    durable = response.get("game", response)
    return str(durable.get("status", "")).lower() in _TERMINAL_STATUSES


async def _settle_committed_outcome(client: FocusPayClient, game_id: str, game: dict) -> dict:
    settlement = await client.settle_committed_outcome(game_id=game_id)
    _apply_response(game, settlement)
    if not _terminal_response(settlement):
        raise RuntimeError("committed outcome settlement is not terminal")
    return settlement


async def _commit_and_settle(
    client: FocusPayClient,
    game_id: str,
    game: dict,
    *,
    kind: str,
    reason: str,
    outcome: dict | None = None,
) -> dict:
    """Commit every outcome before the backend performs terminal accounting."""
    response = await client.commit_game_outcome(
        game_id=game_id,
        winner_id=None,
        expected_state_version=game["state_version"],
        outcome={"kind": kind, "reason": reason, **(outcome or {})},
    )
    _apply_response(game, response)
    return await _settle_committed_outcome(client, game_id, game)


def build_roll_text(game: dict, game_id: str) -> str:
    cfg = GAMES_CONFIG[game["game_type"]]
    rolls_needed = cfg["rolls"]
    creator_rolls = game.get("creator_rolls", [])
    opponent_rolls = game.get("opponent_rolls", [])
    c_status = f"{len(creator_rolls)}/{rolls_needed}" if len(creator_rolls) < rolls_needed else "✅"
    o_status = f"{len(opponent_rolls)}/{rolls_needed}" if len(opponent_rolls) < rolls_needed else "✅"
    c_rolls_str = " ".join(str(r) for r in creator_rolls) if creator_rolls else "—"
    o_rolls_str = " ".join(str(r) for r in opponent_rolls) if opponent_rolls else "—"
    body = (
        f"{cfg['emoji']} <b>GAME #{fmt_id(game_id)}</b> — {cfg['name']}\n\n"
        f"Игроки:\n  • {game['creator_name']} [{c_status}]: {c_rolls_str}\n"
        f"  • {game['opponent_name']} [{o_status}]: {o_rolls_str}\n\n"
        f"💰 Ставка: {game['bet']:.2f} ₽\n\n"
        f"🎲 Киньте {cfg['emoji']} в этот чат — реплай не нужен. "
        f"Если не кинете за 30 с — казино кинет за вас."
    )
    return append_watch_line(body, duel_url(game_id))


def register_pvp_handlers(bot: AsyncTeleBot, client: FocusPayClient):
    from games.table_wizard import register_table_wizard_handlers

    guard = ActiveGameChatGuard(client)
    register_table_wizard_handlers(bot, client)

    async def allows_game_chat(game: dict | None, chat_id: object) -> bool:
        pinned_chat_id = game.get("game_chat_id") if game else None
        if isinstance(pinned_chat_id, int) and not isinstance(pinned_chat_id, bool):
            return pinned_chat_id == chat_id
        return await guard.allows_chat(chat_id)

    async def refresh_private_lobby(call, page: int) -> None:
        message = call.message
        try:
            await bot.edit_message_text(
                _private_lobby_text(call.from_user.id, page),
                chat_id=message.chat.id,
                message_id=message.message_id,
                parse_mode="HTML",
                reply_markup=_private_lobby_keyboard(call.from_user.id, page),
            )
        except Exception:
            logger.info("Private lobby refresh skipped", exc_info=True)

    for gt in EMOJI_GAMES:
        if gt == "cub":
            continue

        async def handler(message, game_type=gt):
            await start_wizard_for_command(bot, client, message, game_type)

        bot.register_message_handler(handler, commands=[gt])

    @bot.message_handler(commands=["cub"])
    async def cub_router(message):
        await start_wizard_for_command(bot, client, message, "cub")

    @bot.message_handler(commands=["newgame"])
    async def cmd_newgame(message):
        await start_wizard(bot, client, message)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("dmjoin:") or c.data.startswith("dmpage:"))
    async def cb_private_lobby(call):
        message = getattr(call, "message", None)
        chat = getattr(message, "chat", None)
        if getattr(chat, "type", None) != "private" or getattr(chat, "id", None) != call.from_user.id:
            await bot.answer_callback_query(call.id, "❌ Действие доступно только владельцу в личном чате.", show_alert=True)
            return
        action, separator, token = (call.data or "").partition(":")
        if not separator or not token:
            await bot.answer_callback_query(call.id, "❌ Некорректная кнопка.", show_alert=True)
            return
        entry = _get_private_lobby_token(token, owner_id=call.from_user.id)
        if entry is None:
            await bot.answer_callback_query(call.id, "⌛ Список устарел. Откройте /allgames ещё раз.", show_alert=True)
            return
        if action == "dmpage":
            page = entry["page"]
            try:
                await bot.edit_message_text(
                    _private_lobby_text(call.from_user.id, page),
                    chat_id=chat.id,
                    message_id=message.message_id,
                    parse_mode="HTML",
                    reply_markup=_private_lobby_keyboard(call.from_user.id, page),
                )
            except Exception as exc:
                if not _is_unchanged_telegram_message(exc):
                    await bot.answer_callback_query(call.id, "❌ Не удалось обновить список.", show_alert=True)
                    return
            await bot.answer_callback_query(call.id)
            return
        if action != "dmjoin" or not entry["game_id"]:
            await bot.answer_callback_query(call.id, "❌ Некорректная кнопка.", show_alert=True)
            return
        game_id = entry["game_id"]
        async with get_game_lock(game_id):
            game = active_games.get(game_id)
            if (
                not game
                or game.get("status") != "waiting"
                or game.get("opponent_id") is not None
                or game.get("creator_id") == call.from_user.id
                or game.get("game_type") not in GAMES_CONFIG
            ):
                await bot.answer_callback_query(call.id, "❌ Игра уже недоступна. Обновите /allgames.", show_alert=True)
                return
            _bind_play_chat(game)
            game.update(status="joining", joining_opponent_id=call.from_user.id)
            join_completed = False
            try:
                await _persist(client, game_id, game)
                response = await client.join_and_hold_game(game_id=game_id, opponent_id=call.from_user.id)
                _apply_response(game, response)
                join_completed = True
                game.update(
                    opponent_id=call.from_user.id,
                    opponent_name=uname(call.from_user),
                    status="rolling",
                    joining_opponent_id=None,
                )
                await _persist(client, game_id, game)
            except Exception as exc:
                if not join_completed:
                    game["status"] = "waiting"
                    game.pop("joining_opponent_id", None)
                else:
                    game["status"] = "recovery_pending"
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code == 409:
                    await bot.answer_callback_query(call.id, "❌ Игра уже недоступна. Обновляю список.", show_alert=True)
                    await refresh_private_lobby(call, entry["page"])
                else:
                    await bot.answer_callback_query(call.id, _safe_game_error(exc), show_alert=True)
                return
            try:
                await bot.delete_message(game["chat_id"], game["message_id"])
            except Exception:
                try:
                    await bot.edit_message_reply_markup(game["chat_id"], game["message_id"], reply_markup=None)
                except Exception:
                    pass
            try:
                roll_message = await bot.send_message(
                    game["chat_id"], build_roll_text(game, game_id), **_watch_send_kwargs(game_id)
                )
                game["roll_msg_id"] = roll_message.message_id
                await _persist(client, game_id, game)
                _index_roll_message(game_id, game)
            except Exception as exc:
                game["status"] = "recovery_pending"
                try:
                    await _persist(client, game_id, game)
                except Exception:
                    pass
                await bot.answer_callback_query(call.id, _safe_game_error(exc), show_alert=True)
                return
        try:
            await bot.edit_message_reply_markup(chat.id, message.message_id, reply_markup=None)
        except Exception:
            pass
        await bot.answer_callback_query(call.id, "✅ Вы в игре! Бросайте эмодзи в игровом чате.")

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("agpage:"))
    async def cb_group_lobby_page(call):
        if not await guard.require_callback(bot, call):
            return
        try:
            page = int((call.data or "").removeprefix("agpage:"))
        except ValueError:
            await bot.answer_callback_query(call.id, "❌ Некорректная кнопка.", show_alert=True)
            return
        message = getattr(call, "message", None)
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        message_id = getattr(message, "message_id", None)
        if not isinstance(chat_id, int) or not isinstance(message_id, int):
            await bot.answer_callback_query(call.id, "❌ Не удалось обновить список.", show_alert=True)
            return
        try:
            await bot.edit_message_text(
                _group_lobby_text(call.from_user.id, page),
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
                reply_markup=_group_lobby_keyboard(call.from_user.id, page),
            )
        except Exception as exc:
            if not _is_unchanged_telegram_message(exc):
                await bot.answer_callback_query(call.id, "❌ Не удалось обновить список.", show_alert=True)
                return
        await bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("join_robot_"))
    async def cb_join_robot(call):
        if not await guard.require_callback(bot, call):
            return
        game_id = call.data.removeprefix("join_robot_")
        async with get_game_lock(game_id):
            game = active_games.get(game_id)
            if not game or game["status"] != "waiting":
                await bot.answer_callback_query(call.id, "❌ Игра уже началась.")
                return
            if call.from_user.id != game["creator_id"]:
                await bot.answer_callback_query(call.id, "❌ Только создатель может выбрать робота казино.", show_alert=True)
                return
            try:
                policy = casino_game_policy(
                    await client.get_casino_settings(),
                    game_key=GAMES_CONFIG[game["game_type"]]["game_type"],
                    local_min_bet_rub=config.MIN_BET,
                )
                validate_game_stake(policy=policy, stake_rub=game["bet"])
            except Exception:
                await bot.answer_callback_query(call.id, "❌ Ставка больше не соответствует настройкам.", show_alert=True)
                return
            game.update(status="joining_robot", joining_robot=True)
            joined = False
            try:
                await _persist(client, game_id, game)
                response = await client.join_pvp_robot(game_id=game_id)
                _apply_response(game, response)
                joined = True
                robot = response.get("robot") or {}
                display_name = str(robot.get("display_name") or "Робот казино")
                game.update(
                    status="rolling", counterparty_kind="pvp_robot", opponent_id=None,
                    opponent_name=f"{display_name} (казино)",
                    robot_profile_key=robot.get("profile_key"), joining_robot=None,
                )
                await _persist(client, game_id, game)
            except Exception as exc:
                if not joined:
                    game["status"] = "waiting"
                    game.pop("joining_robot", None)
                else:
                    game["status"] = "recovery_pending"
                await bot.answer_callback_query(call.id, _safe_game_error(exc), show_alert=True)
                return
            try:
                await bot.delete_message(game["chat_id"], game["message_id"])
            except Exception:
                try:
                    await bot.edit_message_reply_markup(game["chat_id"], game["message_id"], reply_markup=None)
                except Exception:
                    pass
            rm = await bot.send_message(
                game["chat_id"], build_roll_text(game, game_id), **_watch_send_kwargs(game_id)
            )
            game["roll_msg_id"] = rm.message_id
            await _persist(client, game_id, game)
            _index_roll_message(game_id, game)
        await bot.answer_callback_query(call.id, "✅ Робот казино в игре! Бросайте эмодзи.")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("join_"))
    async def cb_join(call):
        game_id = call.data.removeprefix("join_")
        game = active_games.get(game_id)
        chat_id = getattr(getattr(getattr(call, "message", None), "chat", None), "id", None)
        if not await allows_game_chat(game, chat_id):
            await bot.answer_callback_query(call.id, "❌ Игра недоступна в этом чате.", show_alert=True)
            return
        if not game:
            await bot.answer_callback_query(call.id, "❌ Игра не найдена.")
            return
        async with get_game_lock(game_id):
            game = active_games.get(game_id)
            if not game or game["status"] != "waiting":
                await bot.answer_callback_query(call.id, "❌ Игра уже началась.")
                return
            if call.from_user.id == game["creator_id"]:
                await bot.answer_callback_query(call.id, "❌ Нельзя играть с самим собой.")
                return
            try:
                policy = casino_game_policy(await client.get_casino_settings(), game_key=GAMES_CONFIG[game["game_type"]]["game_type"], local_min_bet_rub=config.MIN_BET)
                validate_game_stake(policy=policy, stake_rub=game["bet"])
            except Exception:
                await bot.answer_callback_query(call.id, "❌ Ставка больше не соответствует настройкам.", show_alert=True)
                return
            # Snapshot the in-progress join before its monetary lifecycle call.
            _bind_play_chat(game, prefer=chat_id)
            game.update(status="joining", joining_opponent_id=call.from_user.id)
            join_completed = False
            try:
                await _persist(client, game_id, game)
                response = await client.join_and_hold_game(
                    game_id=game_id,
                    opponent_id=call.from_user.id,
                )
                _apply_response(game, response)
                join_completed = True
                game.update(
                    opponent_id=call.from_user.id, opponent_name=uname(call.from_user), status="rolling",
                    joining_opponent_id=None,
                )
                await _persist(client, game_id, game)
            except Exception as exc:
                if not join_completed:
                    game["status"] = "waiting"
                    game.pop("joining_opponent_id", None)
                else:
                    game["status"] = "recovery_pending"
                await bot.answer_callback_query(call.id, _safe_game_error(exc), show_alert=True)
                return

            try:
                await bot.delete_message(game["chat_id"], game["message_id"])
            except Exception:
                try:
                    await bot.edit_message_reply_markup(game["chat_id"], game["message_id"], reply_markup=None)
                except Exception:
                    pass
            rm = await bot.send_message(
                game["chat_id"], build_roll_text(game, game_id), **_watch_send_kwargs(game_id)
            )
            game["roll_msg_id"] = rm.message_id
            await _persist(client, game_id, game)
            _index_roll_message(game_id, game)
        await bot.answer_callback_query(call.id, "✅ Вы в игре! Отправьте эмодзи")

    async def record_roll(game_id: str, game: dict, side: str, value: int) -> bool:
        if game["status"] != "rolling" or len(game[f"{side}_rolls"]) >= GAMES_CONFIG[game["game_type"]]["rolls"]:
            return False
        actor_id = game.get("creator_id") if side == "creator" else game.get("opponent_id")
        record_fn = getattr(client, "record_pvp_dice_roll", None)
        use_roll_api = callable(record_fn) and isinstance(actor_id, int)
        if use_roll_api:
            try:
                response = await client.record_pvp_dice_roll(
                    game_id=game_id, telegram_id=int(actor_id), value=int(value),
                )
            except Exception:
                logger.exception("PVP dice record-roll failed game_id=%s side=%s", game_id, side)
                return False
            durable = response.get("game") if isinstance(response, dict) else None
            if not isinstance(durable, dict):
                return False
            _apply_response(game, response)
            state = durable.get("game_state") if isinstance(durable.get("game_state"), dict) else {}
            if isinstance(state.get("creator_rolls"), list):
                game["creator_rolls"] = state["creator_rolls"]
            if isinstance(state.get("opponent_rolls"), list):
                game["opponent_rolls"] = state["opponent_rolls"]
            durable_status = str(durable.get("status") or "")
            try:
                await bot.edit_message_text(
                    build_roll_text(game, game_id),
                    chat_id=game["chat_id"],
                    message_id=game["roll_msg_id"],
                    parse_mode="HTML",
                )
            except Exception:
                pass
            if durable_status in _TERMINAL_STATUSES:
                _drop_cache(game_id)
                return True
            needed = GAMES_CONFIG[game["game_type"]]["rolls"]
            if len(game["creator_rolls"]) >= needed and len(game["opponent_rolls"]) >= needed:
                game["status"] = "finalizing"
                asyncio.create_task(resolve_game_results(bot, client, game_id))
            return True
        game[f"{side}_rolls"].append(value)
        try:
            await _persist(client, game_id, game)
        except Exception:
            game[f"{side}_rolls"].pop()
            return False
        try:
            await bot.edit_message_text(build_roll_text(game, game_id), chat_id=game["chat_id"], message_id=game["roll_msg_id"], parse_mode="HTML")
        except Exception:
            pass
        needed = GAMES_CONFIG[game["game_type"]]["rolls"]
        if len(game["creator_rolls"]) >= needed and len(game["opponent_rolls"]) >= needed:
            game["status"] = "finalizing"
            try:
                await _persist(client, game_id, game)
            except Exception:
                game["status"] = "rolling"
                return False
            asyncio.create_task(resolve_game_results(bot, client, game_id))
        return True

    @bot.message_handler(content_types=["dice"])
    async def on_dice(message):
        actor = getattr(message, "from_user", None)
        if getattr(actor, "is_bot", False):
            return
        if await try_handle_house_cub_dice(bot, client, message):
            return
        if await try_handle_v2_dice(bot, client, message):
            return
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        chat_type = getattr(getattr(message, "chat", None), "type", None)
        reply = getattr(message, "reply_to_message", None)
        reply_id = getattr(reply, "message_id", None)
        dice = getattr(message, "dice", None)
        actor_id = getattr(actor, "id", None)
        dice_emoji = getattr(dice, "emoji", None)
        private_chat = chat_type == "private"
        game_id = _roll_game_ids.get((chat_id, reply_id)) if isinstance(chat_id, int) and isinstance(reply_id, int) else None
        game = active_games.get(game_id) if game_id else None
        if game is None and isinstance(chat_id, int) and isinstance(actor_id, int):
            game_id, game = _rolling_game_for_thrower(chat_id, actor_id, dice_emoji if isinstance(dice_emoji, str) else None)
        if game is None and private_chat and isinstance(actor_id, int):
            game_id, game = _rolling_game_for_thrower(
                chat_id, actor_id, dice_emoji if isinstance(dice_emoji, str) else None, require_same_chat=False,
            )
        if game is None and private_chat and isinstance(actor_id, int):
            pip = getattr(dice, "value", None)
            if isinstance(pip, int) and 1 <= pip <= 6:
                recorded = await _record_private_dice_via_api(client, actor_id, pip)
                if recorded:
                    return
        if game is None or not game_id:
            if private_chat:
                await bot.reply_to(
                    message,
                    "Стол с людьми — /cub. Кидай куб в игровом чате, не в личке.",
                )
            return
        grouped_play = _is_group_chat_id(_play_chat_id(game))
        if private_chat and grouped_play:
            await bot.reply_to(message, "Кинь 🎲 в игровом чате.")
            return
        private_player = (
            private_chat
            and not grouped_play
            and isinstance(actor_id, int)
            and actor_id in {game.get("creator_id"), game.get("opponent_id")}
        )
        if not private_player and not await allows_game_chat(game, chat_id):
            logger.info("Dice rejected reason=chat_guard chat_id=%s reply_id=%s actor_id=%s emoji=%s", chat_id, reply_id, actor_id, dice_emoji)
            await bot.reply_to(message, "❌ Бросок можно сделать только в подтверждённом игровом чате.")
            return
        async with get_game_lock(game_id):
            game = active_games.get(game_id)
            if not game or game["status"] != "rolling":
                logger.info("Dice rejected reason=inactive_game game_id=%s chat_id=%s reply_id=%s", game_id, chat_id, reply_id)
                return
            if game.get("chat_id") != chat_id and not private_player:
                logger.info("Dice rejected reason=inactive_game game_id=%s chat_id=%s reply_id=%s", game_id, chat_id, reply_id)
                return
            expected_emoji = GAMES_CONFIG[game["game_type"]]["emoji"]
            if dice_emoji != expected_emoji:
                logger.info("Dice rejected reason=wrong_emoji game_id=%s actor_id=%s expected=%s actual=%s", game_id, actor_id, expected_emoji, dice_emoji)
                await bot.reply_to(message, f"❌ Для этой игры нужен бросок {expected_emoji}.")
                return
            side = "creator" if actor_id == game["creator_id"] else "opponent" if actor_id == game["opponent_id"] else None
            if not side:
                logger.info("Dice rejected reason=not_player game_id=%s actor_id=%s", game_id, actor_id)
                await bot.reply_to(message, "❌ Бросок могут сделать только участники этой игры.")
                return
            recorded = await record_roll(game_id, game, side, dice.value)
            if not recorded:
                logger.warning("Dice rejected reason=persist_failed game_id=%s actor_id=%s", game_id, actor_id)
                await bot.reply_to(message, "❌ Не удалось сохранить бросок. Попробуйте ещё раз этим же эмодзи.")
                return
            if side != "creator" or game.get("counterparty_kind") != "pvp_robot" or game["status"] != "rolling":
                return
            try:
                await wait_dice_landed()
                send_kwargs: dict[str, Any] = {"chat_id": game["chat_id"], "emoji": expected_emoji}
                roll_msg_id = game.get("roll_msg_id")
                if isinstance(roll_msg_id, int):
                    send_kwargs["reply_to_message_id"] = roll_msg_id
                robot_roll = await bot.send_dice(**send_kwargs)
                await wait_dice_landed()
                await record_roll(game_id, game, "opponent", robot_roll.dice.value)
            except Exception:
                logger.exception("Robot dice delivery failed game_id=%s", game_id)
                game["status"] = "recovery_pending"
                try:
                    await _persist(client, game_id, game)
                except Exception:
                    logger.exception("Unable to persist robot Dice recovery state game_id=%s", game_id)

    async def cmd_allgames(message):
        if message.chat.type == "private":
            owner_id = getattr(getattr(message, "from_user", None), "id", None)
            if not isinstance(owner_id, int) or owner_id <= 0:
                await bot.reply_to(message, "❌ Не удалось определить пользователя.")
                return
            keyboard = _private_lobby_keyboard(owner_id, page=0)
            await bot.reply_to(
                message,
                _private_lobby_text(owner_id, page=0),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return
        if not await guard.require_message(bot, message):
            return
        owner_id = getattr(getattr(message, "from_user", None), "id", None)
        if not isinstance(owner_id, int) or owner_id <= 0:
            await bot.reply_to(message, "❌ Не удалось определить пользователя.")
            return
        await bot.reply_to(
            message,
            _group_lobby_text(owner_id, 0),
            parse_mode="HTML",
            reply_markup=_group_lobby_keyboard(owner_id, 0),
        )

    bot.register_message_handler(cmd_allgames, commands=["allgames"])

    @bot.message_handler(commands=["del"])
    async def cmd_del(message):
        if not await guard.require_message(bot, message):
            return
        if not message.reply_to_message:
            await bot.reply_to(message, "❌ Ответьте на сообщение с игрой.")
            return
        match = next(((gid, g) for gid, g in active_games.items() if g.get("message_id") == message.reply_to_message.message_id and g["creator_id"] == message.from_user.id and g["status"] == "waiting"), None)
        if not match:
            await bot.reply_to(message, "❌ Игра не найдена или уже началась.")
            return
        game_id, game = match
        async with get_game_lock(game_id):
            game["status"] = "cancelling"
            try:
                await _persist(client, game_id, game)
                await _commit_and_settle(
                    client,
                    game_id,
                    game,
                    kind="cancel",
                    reason="creator_cancelled",
                    outcome={"creator_id": game["creator_id"]},
                )
            except Exception as exc:
                await bot.reply_to(message, _safe_game_error(exc))
                return
            _drop_cache(game_id)
        try:
            await bot.delete_message(game["chat_id"], game["message_id"])
        except Exception:
            pass
        await bot.reply_to(message, "✅ Игра удалена, ставка возвращена.")


async def resolve_game_results(bot: AsyncTeleBot, client: FocusPayClient, game_id: str):
    """Commit an immutable outcome before the backend performs terminal accounting."""
    await asyncio.sleep(3)
    async with get_game_lock(game_id):
        game = active_games.get(game_id)
        if not game or game["status"] != "finalizing":
            return
        cfg = GAMES_CONFIG[game["game_type"]]
        creator_sum, opponent_sum = sum(game["creator_rolls"]), sum(game["opponent_rolls"])
        c_rolls = "+".join(map(str, game["creator_rolls"]))
        o_rolls = "+".join(map(str, game["opponent_rolls"]))
        c_display = f"{c_rolls} = {creator_sum}" if cfg["rolls"] > 1 else str(creator_sum)
        o_display = f"{o_rolls} = {opponent_sum}" if cfg["rolls"] > 1 else str(opponent_sum)
        try:
            if creator_sum == opponent_sum:
                game["status"] = "draw_releasing"
                await _persist(client, game_id, game)
                await _commit_and_settle(
                    client,
                    game_id,
                    game,
                    kind="draw",
                    reason="draw",
                    outcome={
                        "creator_score": creator_sum,
                        "opponent_score": opponent_sum,
                        "creator_rolls": game["creator_rolls"],
                        "opponent_rolls": game["opponent_rolls"],
                    },
                )
                text = f"📊 <b>Результаты #{fmt_id(game_id)}</b> {cfg['emoji']}\n\n  • {game['creator_name']} [{c_display}]\n  • {game['opponent_name']} [{o_display}]\n\n🤝 Ничья! Ставки возвращены."
            else:
                robot_game = game.get("counterparty_kind") == "pvp_robot"
                if robot_game and creator_sum < opponent_sum:
                    winner_id = None
                    winner_name = game["opponent_name"]
                    outcome_kind = "house_win"
                else:
                    winner_id = game["creator_id"] if creator_sum > opponent_sum else game["opponent_id"]
                    winner_name = game["creator_name"] if winner_id == game["creator_id"] else game["opponent_name"]
                    outcome_kind = "winner"
                outcome = {"kind": outcome_kind, "winner_id": winner_id, "creator_score": creator_sum, "opponent_score": opponent_sum, "creator_rolls": game["creator_rolls"], "opponent_rolls": game["opponent_rolls"]}
                response = await client.commit_game_outcome(
                    game_id=game_id,
                    winner_id=winner_id,
                    expected_state_version=game["state_version"],
                    outcome=outcome,
                )
                _apply_response(game, response)
                settlement = await _settle_committed_outcome(client, game_id, game)
                payout = settlement_payout_rub(settlement)
                payout_text = f"\n💰 Выигрыш: {payout:.2f} ₽"
                text = f"📊 <b>Результаты #{fmt_id(game_id)}</b> {cfg['emoji']}\n\n  • {game['creator_name']} [{c_display}]\n  • {game['opponent_name']} [{o_display}]\n\n🏆 Победитель: {winner_name}{payout_text}"
        except Exception as exc:
            game["status"] = "finalization_failed"
            try:
                await _persist(client, game_id, game)
            except Exception:
                pass
            logger.exception("Game settlement requires review game_id=%s", game_id)
            await bot.send_message(game["chat_id"], f"❌ Расчёт игры #{fmt_id(game_id)} требует проверки.\nИдентификатор: <code>{game_id}</code>", parse_mode="HTML")
            return
        _drop_cache(game_id)
    sent = await bot.send_message(game["chat_id"], text, parse_mode="HTML")
    from games.chat_reaper import track_group_result

    track_group_result(game.get("chat_id"), sent)
