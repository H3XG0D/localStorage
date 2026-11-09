"""Hydrate site-created baccarat/blackjack waiting games into the Telegram UI cache."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Awaitable, Callable, Mapping

from games.catalog import CARD_GAMES

logger = logging.getLogger(__name__)

SITE_DUEL_ID_RE = re.compile(r"^web-[0-9a-f]{12}$")
JOIN_PREFIX = {
    "baccara": "bak_wjoin_",
    "blackjack": "bj_wjoin_",
}

PersistFn = Callable[..., Awaitable[dict]]
NextGidFn = Callable[[], Awaitable[int]]


def is_site_duel_id(game_id: object) -> bool:
    return bool(SITE_DUEL_ID_RE.fullmatch(str(game_id or "")))


def join_callback_data(game_type: str, game_id: str) -> str:
    prefix = JOIN_PREFIX.get(game_type)
    if not prefix:
        raise ValueError(f"unsupported card game_type {game_type}")
    return f"{prefix}{game_id}"


def find_gid(cache: Mapping[int, dict], settlement_game_id: str) -> int | None:
    target = str(settlement_game_id)
    for gid, game in cache.items():
        if str(game.get("settlement_game_id") or "") == target:
            return int(gid)
    return None


def _parse_created_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.utcnow()


def _waiting_template(
    *,
    gid: int,
    durable: dict,
    chat_id: int | None,
    telegram_message_id: int | None,
    creator_name: str,
) -> dict:
    stake = Decimal(str(durable.get("stake_rub") or "0"))
    game_type = str(durable.get("game_type"))
    game = {
        "game_id": gid,
        "settlement_game_id": str(durable["game_id"]),
        "creator_id": durable.get("creator_id"),
        "creator_name": creator_name,
        "opponent_id": None,
        "opponent_name": None,
        "bet": stake,
        "deck_creator": [],
        "deck_opponent": [],
        "cards_creator": [],
        "cards_opponent": [],
        "decision_creator": None,
        "decision_opponent": None,
        "msg_id_creator": None,
        "msg_id_opponent": None,
        "chat_id_creator": chat_id,
        "chat_id_opponent": None,
        "status": "waiting",
        "created_at": _parse_created_at(durable.get("created_at")),
        "started_at": None,
        "rng_commit": durable.get("rng_commit"),
        "state_version": durable.get("state_version"),
        "durable_status": "waiting",
        "invitation_message_id": telegram_message_id,
        "game_chat_id": durable.get("game_chat_id") if durable.get("game_chat_id") is not None else chat_id,
    }
    if game_type == "blackjack":
        game.update(
            ace_values_creator=[],
            ace_values_opponent=[],
            status_creator=None,
            status_opponent=None,
            pending_ace_creator=False,
            pending_ace_opponent=False,
        )
    return game


def restore_persisted(cache: dict, durable: dict, *, bump_counter) -> int | None:
    state = durable.get("game_state")
    durable_id = str(durable.get("game_id") or "")
    if not isinstance(state, dict) or not isinstance(state.get("game_id"), int):
        return None
    if str(state.get("settlement_game_id") or "") != durable_id:
        return None
    gid = int(state["game_id"])
    game = {**state}
    game["settlement_game_id"] = durable_id
    version = durable.get("state_version")
    if isinstance(version, int):
        game["state_version"] = version
    if durable.get("status") == "waiting":
        game["status"] = "waiting"
    game["created_at"] = _parse_created_at(game.get("created_at") or durable.get("created_at"))
    try:
        game["bet"] = Decimal(str(game.get("bet") or durable.get("stake_rub") or "0"))
    except Exception:
        game["bet"] = Decimal("0")
    cache[gid] = game
    bump_counter(gid)
    return gid


async def _fill_waiting(
    client,
    *,
    durable: dict,
    chat_id: int | None,
    telegram_message_id: int | None,
    cache: dict,
    persist: PersistFn,
    next_gid: NextGidFn,
) -> dict:
    existing = find_gid(cache, str(durable["game_id"]))
    gid = existing if existing is not None else await next_gid()
    game = _waiting_template(
        gid=gid,
        durable=durable,
        chat_id=chat_id,
        telegram_message_id=telegram_message_id,
        creator_name=f"Игрок {durable.get('creator_id')}",
    )
    try:
        await persist(client, game)
    except Exception:
        logger.warning("Card waiting persist failed game_id=%s", durable.get("game_id"), exc_info=True)
    cache[gid] = game
    return game


def _card_module(game_type: str):
    import importlib
    return importlib.import_module(f"games.{game_type}")


async def _next_gid(module) -> int:
    async with module.game_counter_lock:
        module.game_counter += 1
        return module.game_counter


def _bump_counter(module, gid: int) -> None:
    if gid > module.game_counter:
        module.game_counter = gid


async def hydrate_invited_card_game(client, payload: dict, telegram_message_id: int, *, module=None) -> dict:
    game_id = str(payload["game_id"])
    game_type = str(payload.get("game_type") or "")
    if game_type not in CARD_GAMES:
        raise ValueError("Invitation is not a card game")
    module = module or _card_module(game_type)
    durable = next(
        (item for item in await client.get_active_pvp_games() if str(item.get("game_id")) == game_id),
        None,
    )
    if not isinstance(durable, dict) or durable.get("status") != "waiting":
        raise ValueError("Invitation game is no longer a waiting game")
    if not isinstance(durable.get("state_version"), int):
        raise ValueError("Invitation lifecycle game is invalid")
    chat_id = payload.get("chat_id")
    if not isinstance(chat_id, int):
        raise ValueError("Invitation payload chat_id is invalid")
    return await _fill_waiting(
        client,
        durable=durable,
        chat_id=chat_id,
        telegram_message_id=telegram_message_id,
        cache=module.active_games,
        persist=module._persist,
        next_gid=lambda: _next_gid(module),
    )


async def adopt_waiting_card_game(
    client,
    *,
    game_id: str,
    game_type: str,
    chat_id: int | None = None,
    module=None,
    cache: dict | None = None,
    persist: PersistFn | None = None,
    next_gid: NextGidFn | None = None,
    bump_counter=None,
) -> int | None:
    module = module or _card_module(game_type)
    cache = cache if cache is not None else module.active_games
    persist = persist or module._persist
    next_gid = next_gid or (lambda: _next_gid(module))
    bump = bump_counter or (lambda gid: _bump_counter(module, gid))
    existing = find_gid(cache, game_id)
    if existing is not None:
        return existing
    durable = next(
        (item for item in await client.get_active_pvp_games() if str(item.get("game_id")) == game_id),
        None,
    )
    if not isinstance(durable, dict) or durable.get("status") != "waiting":
        return None
    restored = restore_persisted(cache, durable, bump_counter=bump)
    if restored is not None:
        return restored
    game = await _fill_waiting(
        client,
        durable=durable,
        chat_id=chat_id if isinstance(chat_id, int) else durable.get("game_chat_id"),
        telegram_message_id=None,
        cache=cache,
        persist=persist,
        next_gid=next_gid,
    )
    return int(game["game_id"])


async def hydrate_waiting_card_games(client, *, modules: dict | None = None) -> int:
    """Restore waiting/active card 1x1 games after a bot restart."""
    getter = getattr(client, "get_active_pvp_games", None)
    if not callable(getter):
        return 0
    try:
        durable_games = await getter()
    except Exception:
        logger.exception("Card game hydrate lookup failed")
        return 0
    if not isinstance(durable_games, list):
        return 0
    resolved = modules or {key: _card_module(key) for key in CARD_GAMES}
    hydrated = 0
    for durable in durable_games:
        if not isinstance(durable, dict):
            continue
        game_type = str(durable.get("game_type") or "")
        if game_type not in CARD_GAMES:
            continue
        module = resolved[game_type]
        cache = module.active_games
        if find_gid(cache, str(durable.get("game_id"))) is not None:
            continue
        restored = restore_persisted(
            cache, durable, bump_counter=lambda gid, mod=module: _bump_counter(mod, gid)
        )
        if restored is not None:
            hydrated += 1
            continue
        if durable.get("status") != "waiting":
            continue
        game = _waiting_template(
            gid=await _next_gid(module),
            durable=durable,
            chat_id=durable.get("game_chat_id"),
            telegram_message_id=None,
            creator_name=f"Игрок {durable.get('creator_id')}",
        )
        cache[game["game_id"]] = game
        hydrated += 1
    logger.info("Hydrated %s waiting card game(s)", hydrated)
    return hydrated
