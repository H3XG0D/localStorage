"""Reattach live roulette/jackpot cards after a bot restart."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from games.chat_guard import parse_telegram_chat_id
from games.jackpot_card import upsert as upsert_jackpot
from games.roulette_card import upsert as upsert_roulette

logger = logging.getLogger(__name__)

_LIVE = frozenset({"open", "locked", "spinning", "countdown"})

FetchSnap = Callable[[], Awaitable[Any]]
UpsertFn = Callable[..., Awaitable[None]]


def _binding_chat_id(binding: Any) -> int | None:
    if not isinstance(binding, dict):
        return None
    return parse_telegram_chat_id(binding.get("chat_id"))


def _player_id(snapshot: dict[str, Any]) -> int | None:
    players = snapshot.get("players")
    if not isinstance(players, list):
        return None
    for row in players:
        if not isinstance(row, dict):
            continue
        uid = parse_telegram_chat_id(row.get("user_id"))
        if uid is not None and uid > 0:
            return uid
    return None


def snapshot_needs_card(snapshot: dict[str, Any] | None) -> bool:
    snap = snapshot if isinstance(snapshot, dict) else {}
    status = str(snap.get("status") or "")
    if status not in _LIVE:
        return False
    players = snap.get("players") if isinstance(snap.get("players"), list) else []
    if players:
        return True
    if snap.get("closes_at") and status == "open":
        return True
    return status in {"locked", "spinning", "countdown"}


async def _hydrate_snapshot(
    bot: Any,
    client: Any,
    *,
    name: str,
    fetch: FetchSnap,
    upsert: UpsertFn,
    chat_id: int,
) -> int:
    try:
        snap = await fetch()
    except Exception:
        logger.exception("%s live card hydrate fetch failed", name)
        return 0
    if not isinstance(snap, dict) or not snapshot_needs_card(snap):
        return 0
    telegram_id = _player_id(snap)
    try:
        await upsert(bot, client, chat_id, snap, telegram_id=telegram_id)
    except Exception:
        logger.exception("%s live card hydrate upsert failed chat=%s", name, chat_id)
        return 0
    logger.info(
        "Hydrated %s live card chat=%s round=%s",
        name,
        chat_id,
        snap.get("round_id") or snap.get("room_id"),
    )
    return 1


async def hydrate_live_table_cards(bot: Any, client: Any) -> int:
    getter = getattr(client, "get_active_game_chat_binding", None)
    if not callable(getter):
        return 0
    try:
        binding = await getter()
    except Exception:
        logger.exception("live card hydrate: binding lookup failed")
        return 0
    chat_id = _binding_chat_id(binding)
    if chat_id is None:
        return 0
    hydrated = 0
    roulette_get = getattr(client, "get_roulette_table", None)
    if callable(roulette_get):
        hydrated += await _hydrate_snapshot(
            bot,
            client,
            name="roulette",
            fetch=roulette_get,
            upsert=upsert_roulette,
            chat_id=chat_id,
        )
    jackpot_get = getattr(client, "get_jackpot", None)
    if callable(jackpot_get):
        hydrated += await _hydrate_snapshot(
            bot,
            client,
            name="jackpot",
            fetch=jackpot_get,
            upsert=upsert_jackpot,
            chat_id=chat_id,
        )
    return hydrated
