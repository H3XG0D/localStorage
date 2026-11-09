"""Clan vs clan wars. Stakes come from player wallets; clans have no bank."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import uuid4

from fastapi import HTTPException

from casino_clans import active_membership
from casino_finance import (
    casino_ledger_order_ref,
    casino_operation_ref,
    confirm_unified_hold,
    load_casino_settings,
    money,
    reserve_unified_funds,
)
from casino_fixed_rooms import (
    HMAC_ALGORITHM,
    commit_seed,
    hmac_index,
    make_server_seed,
    rake_split,
    split_even,
)
from casino_settings_registry import REGISTRY, default_numeric

logger = logging.getLogger("casino_clan_wars")

GAME_TYPE = "clan_war"
_subscribers: set[asyncio.Queue] = set()
_closer_started = False


@dataclass(frozen=True)
class WarConfig:
    enabled: bool
    clans_enabled: bool
    max_fighters: int
    collect_seconds: int
    rake_percent: Decimal
    min_bet: Decimal
    max_bet: Decimal


def war_message(
    war_id: str,
    challenger_clan_id: int,
    opponent_clan_id: int,
    challenger_ids: Sequence[int],
    opponent_ids: Sequence[int],
) -> str:
    left = ",".join(str(int(uid)) for uid in sorted(challenger_ids))
    right = ",".join(str(int(uid)) for uid in sorted(opponent_ids))
    return f"{war_id}:{int(challenger_clan_id)}:{int(opponent_clan_id)}:{left}|{right}"


def _setting_int(values: Mapping[str, object], key: str) -> int:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("value") is not None:
        return int(raw["value"])
    spec = REGISTRY.get(key)
    return int(spec.default) if spec is not None else 0  # type: ignore[arg-type]


def _setting_percent(values: Mapping[str, object], key: str) -> Decimal:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("percent") is not None:
        return money(raw["percent"])
    spec = REGISTRY.get(key)
    return money(spec.default) if spec is not None else money(0)  # type: ignore[arg-type]


def _setting_bool(values: Mapping[str, object], key: str, default: bool = True) -> bool:
    raw = values.get(key)
    if isinstance(raw, Mapping) and isinstance(raw.get("enabled"), bool):
        return bool(raw["enabled"])
    spec = REGISTRY.get(key)
    if spec is not None and isinstance(spec.default, bool):
        return bool(spec.default)
    return default


async def load_war_config(conn) -> WarConfig:
    settings = await load_casino_settings(conn)
    rows = {str(row["key"]): row["value"] for row in await conn.fetch("/* war:settings */ SELECT key, value FROM casino_settings")}
    max_fighters = _setting_int(rows, "clan_war_max_fighters") or 5
    collect = _setting_int(rows, "clan_war_collect_seconds") or 1800
    rake = _setting_percent(rows, "clan_war_rake_percent")
    if rake == 0 and "clan_war_rake_percent" not in rows:
        rake = money(default_numeric("clan_war_rake_percent"))
    return WarConfig(
        enabled=bool(settings.enabled_games.get(GAME_TYPE, False)),
        clans_enabled=_setting_bool(rows, "clans_enabled", True),
        max_fighters=max(1, min(max_fighters, 20)),
        collect_seconds=max(60, min(collect, 86400)),
        rake_percent=rake,
        min_bet=settings.min_bet_rub,
        max_bet=settings.max_bet_rub,
    )


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def publish(payload: Mapping[str, object]) -> None:
    for queue in list(_subscribers):
        try:
            queue.put_nowait(dict(payload))
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(dict(payload))
            except asyncio.QueueFull:
                pass


def ensure_closer() -> None:
    global _closer_started
    if _closer_started:
        return
    _closer_started = True
    asyncio.create_task(_closer_loop())


async def _closer_loop() -> None:
    from db import get_pool

    while True:
        await asyncio.sleep(1)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await maybe_close_due(conn)
        except Exception:
            logger.exception("clan-war closer")


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


async def _fighters(conn, war_pk: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        /* war:fighters */
        SELECT clan_id, user_id, hold_order_ref, created_at
        FROM casino_clan_war_fighters
        WHERE war_pk = $1
        ORDER BY id
        """,
        war_pk,
    )
    return [dict(row) for row in rows]


async def _clan_brief(conn, clan_id: int | None) -> dict[str, object] | None:
    if not clan_id:
        return None
    row = await conn.fetchrow(
        "/* war:clan */ SELECT id, tag, name FROM casino_clans WHERE id = $1 AND disbanded_at IS NULL",
        int(clan_id),
    )
    if not row:
        return None
    return {"clan_id": int(row["id"]), "tag": str(row["tag"]), "name": str(row["name"])}


async def _live_fight(conn, user_id: int):
    return await conn.fetchrow(
        """
        /* war:live-fight */
        SELECT f.war_pk, w.war_id
        FROM casino_clan_war_fighters f
        JOIN casino_clan_wars w ON w.id = f.war_pk
        WHERE f.user_id = $1 AND w.status IN ('open', 'accepted', 'locked')
        LIMIT 1
        """,
        int(user_id),
    )


def _side_ids(fighters: Sequence[Mapping[str, Any]], clan_id: int | None) -> list[int]:
    if not clan_id:
        return []
    return [int(row["user_id"]) for row in fighters if int(row["clan_id"]) == int(clan_id)]


async def _named_public(conn, row: Mapping[str, Any], cfg: WarConfig, viewer_id: int | None) -> dict[str, object]:
    from casino_chat import actor_chip, public_actors

    fighters = await _fighters(conn, int(row["id"]))
    actors = await public_actors(conn, [int(item["user_id"]) for item in fighters])
    challenger = await _clan_brief(conn, int(row["challenger_clan_id"]))
    opponent = await _clan_brief(conn, int(row["opponent_clan_id"]) if row.get("opponent_clan_id") else None)
    locked = str(row["status"]) in {"locked", "settled"}
    chall_id = int(row["challenger_clan_id"])
    opp_id = int(row["opponent_clan_id"]) if row.get("opponent_clan_id") else None
    chall_ids = _side_ids(fighters, chall_id)
    opp_ids = _side_ids(fighters, opp_id)
    message = None
    if opp_id and chall_ids and opp_ids:
        message = war_message(str(row["war_id"]), chall_id, opp_id, chall_ids, opp_ids)

    def pack(clan: dict[str, object] | None, ids: Sequence[int]) -> dict[str, object] | None:
        if not clan:
            return None
        people = [actor_chip(actors, uid) for uid in ids]
        return {**clan, "fighters": people, "filled": len(people)}

    my_side = None
    if viewer_id:
        mine = next((item for item in fighters if int(item["user_id"]) == int(viewer_id)), None)
        if mine:
            my_side = "challenger" if int(mine["clan_id"]) == chall_id else "opponent"
    pot = money(row["pot_rub"]) if row.get("pot_rub") else money(money(row["stake_rub"]) * Decimal(len(fighters)))
    return {
        "war_id": str(row["war_id"]),
        "status": str(row["status"]),
        "creator_id": int(row["creator_id"]),
        "commit_hash": str(row["commit_hash"]),
        "server_seed": str(row["server_seed"]) if locked else None,
        "hmac_message": message,
        "algorithm": HMAC_ALGORITHM,
        "closes_at": _iso(row.get("closes_at")),
        "stake_rub": float(money(row["stake_rub"])),
        "fighters_needed": int(row["fighters_needed"]),
        "pot_rub": float(pot),
        "rake_percent": float(cfg.rake_percent),
        "rake_rub": float(money(row["rake_rub"])) if locked else None,
        "payout_per_winner_rub": float(money(row["payout_per_winner_rub"])) if str(row["status"]) == "settled" else None,
        "winner_clan_id": int(row["winner_clan_id"]) if row.get("winner_clan_id") else None,
        "winner_index": int(row["winner_index"]) if row.get("winner_index") is not None else None,
        "challenger": pack(challenger, chall_ids),
        "opponent": pack(opponent, opp_ids),
        "my_side": my_side,
        "min_bet_rub": float(cfg.min_bet),
        "max_bet_rub": float(cfg.max_bet),
        "max_fighters": cfg.max_fighters,
        "collect_seconds": cfg.collect_seconds,
        "enabled": cfg.enabled,
        "clans_enabled": cfg.clans_enabled,
    }


async def snapshot(conn, war_id: str, *, viewer_id: int | None = None) -> dict[str, object]:
    cfg = await load_war_config(conn)
    await maybe_close_due(conn)
    row = await conn.fetchrow("/* war:get */ SELECT * FROM casino_clan_wars WHERE war_id = $1", war_id)
    if not row:
        raise HTTPException(status_code=404, detail="Война не найдена")
    return await _named_public(conn, row, cfg, viewer_id)


async def list_open(conn, *, viewer_id: int | None = None, limit: int = 30) -> dict[str, object]:
    cfg = await load_war_config(conn)
    await maybe_close_due(conn)
    rows = await conn.fetch(
        """
        /* war:list-open */
        SELECT * FROM casino_clan_wars
        WHERE status IN ('open', 'accepted')
        ORDER BY created_at DESC
        LIMIT $1
        """,
        max(1, min(int(limit), 50)),
    )
    wars = [await _named_public(conn, row, cfg, viewer_id) for row in rows]
    return {
        "enabled": cfg.enabled,
        "clans_enabled": cfg.clans_enabled,
        "rake_percent": float(cfg.rake_percent),
        "max_fighters": cfg.max_fighters,
        "min_bet_rub": float(cfg.min_bet),
        "max_bet_rub": float(cfg.max_bet),
        "wars": wars,
    }


async def _require_member(conn, user_id: int):
    membership = await active_membership(conn, user_id)
    if not membership:
        raise HTTPException(status_code=409, detail="Нужно быть в команде")
    return membership


async def _hold_stake(conn, *, user_id: int, war_id: str, amount: Decimal) -> str:
    hold_id = f"cwar-{war_id}-{user_id}-{uuid4().hex[:8]}"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=amount)
        await confirm_unified_hold(
            conn,
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=amount,
            note=f"Clan war {war_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось списать ставку") from exc
    return order_ref


async def _credit(conn, *, war_id: str, user_id: int, amount: Decimal, kind: str) -> None:
    payout = money(amount)
    if payout <= 0:
        return
    order_id = casino_operation_ref(kind, war_id, str(user_id))
    inserted = await conn.fetchrow(
        """
        /* war:credit */
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING user_id, amount_rub
        """,
        user_id,
        payout,
        order_id,
        f"Clan war {kind} {war_id}",
    )
    existing = inserted or await conn.fetchrow(
        "/* war:credit-get */ SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1",
        order_id,
    )
    if not existing or int(existing["user_id"]) != user_id or money(existing["amount_rub"]) != payout:
        raise HTTPException(status_code=409, detail="Clan war payout conflicts")


async def _credit_house(conn, *, amount: Decimal) -> None:
    rake = money(amount)
    if rake <= 0:
        return
    await conn.execute(
        """
        /* war:house */
        UPDATE casino_house_accounts
        SET balance_rub = balance_rub + $1, updated_at = now()
        WHERE account_key = 'main'
        """,
        rake,
    )


async def create_war(conn, *, user_id: int, stake_rub: Decimal, fighters_needed: int) -> dict[str, object]:
    cfg = await load_war_config(conn)
    if not cfg.clans_enabled:
        raise HTTPException(status_code=409, detail="Кланы выключены")
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Войны кланов выключены")
    stake = money(stake_rub)
    needed = int(fighters_needed)
    if stake < cfg.min_bet or stake > cfg.max_bet:
        raise HTTPException(status_code=400, detail="Ставка вне лимита")
    if needed < 1 or needed > cfg.max_fighters:
        raise HTTPException(status_code=400, detail=f"Бойцов с стороны: от 1 до {cfg.max_fighters}")
    membership = await _require_member(conn, user_id)
    if await _live_fight(conn, user_id):
        raise HTTPException(status_code=409, detail="Вы уже в другой войне")
    seed = make_server_seed()
    war_id = f"cw-{uuid4().hex[:12]}"
    closes_at = datetime.now(timezone.utc) + timedelta(seconds=cfg.collect_seconds)
    created = await conn.fetchrow(
        """
        /* war:insert */
        INSERT INTO casino_clan_wars (
            war_id, status, creator_id, challenger_clan_id, stake_rub, fighters_needed,
            commit_hash, server_seed, closes_at, pot_rub
        )
        VALUES ($1, 'open', $2, $3, $4, $5, $6, $7, $8, $4)
        RETURNING *
        """,
        war_id,
        int(user_id),
        int(membership["clan_id"]),
        stake,
        needed,
        commit_seed(seed),
        seed,
        closes_at,
    )
    order_ref = await _hold_stake(conn, user_id=user_id, war_id=war_id, amount=stake)
    await conn.execute(
        """
        /* war:insert-fighter */
        INSERT INTO casino_clan_war_fighters (war_pk, clan_id, user_id, hold_order_ref)
        VALUES ($1, $2, $3, $4)
        """,
        int(created["id"]),
        int(membership["clan_id"]),
        int(user_id),
        order_ref,
    )
    live = await conn.fetchrow("/* war:get-pk */ SELECT * FROM casino_clan_wars WHERE id = $1", int(created["id"]))
    snap = await _named_public(conn, live, cfg, user_id)
    publish({"type": "create", "war_id": war_id})
    return snap


async def accept_war(conn, *, user_id: int, war_id: str) -> dict[str, object]:
    cfg = await load_war_config(conn)
    if not cfg.enabled or not cfg.clans_enabled:
        raise HTTPException(status_code=409, detail="Войны кланов выключены")
    membership = await _require_member(conn, user_id)
    row = await conn.fetchrow(
        "/* war:lock */ SELECT * FROM casino_clan_wars WHERE war_id = $1 FOR UPDATE",
        war_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Война не найдена")
    if str(row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Вызов уже принят или закрыт")
    if int(membership["clan_id"]) == int(row["challenger_clan_id"]):
        raise HTTPException(status_code=409, detail="Нельзя принять вызов своей команды")
    if await _live_fight(conn, user_id):
        raise HTTPException(status_code=409, detail="Вы уже в другой войне")
    stake = money(row["stake_rub"])
    order_ref = await _hold_stake(conn, user_id=user_id, war_id=str(row["war_id"]), amount=stake)
    await conn.execute(
        """
        /* war:accept */
        UPDATE casino_clan_wars
        SET status = 'accepted', opponent_clan_id = $2, accepted_at = now(), pot_rub = pot_rub + $3
        WHERE id = $1
        """,
        int(row["id"]),
        int(membership["clan_id"]),
        stake,
    )
    await conn.execute(
        """
        /* war:insert-fighter */
        INSERT INTO casino_clan_war_fighters (war_pk, clan_id, user_id, hold_order_ref)
        VALUES ($1, $2, $3, $4)
        """,
        int(row["id"]),
        int(membership["clan_id"]),
        int(user_id),
        order_ref,
    )
    publish({"type": "accept", "war_id": str(row["war_id"])})
    from casino_inbox import notify_player_joined

    await notify_player_joined(
        conn,
        joiner_id=int(user_id),
        other_ids=[int(row["creator_id"])],
        kind="war",
        game_id=str(row["war_id"]),
        game_type="clan_war",
        stake_rub=stake,
    )
    live = await conn.fetchrow("/* war:get-pk */ SELECT * FROM casino_clan_wars WHERE id = $1", int(row["id"]))
    if await _both_full(conn, live):
        await _lock_and_settle(conn, war_pk=int(row["id"]), cfg=cfg)
        live = await conn.fetchrow("/* war:get-pk */ SELECT * FROM casino_clan_wars WHERE id = $1", int(row["id"]))
    return await _named_public(conn, live, cfg, user_id)


async def join_war(conn, *, user_id: int, war_id: str) -> dict[str, object]:
    cfg = await load_war_config(conn)
    if not cfg.enabled or not cfg.clans_enabled:
        raise HTTPException(status_code=409, detail="Войны кланов выключены")
    await maybe_close_due(conn)
    membership = await _require_member(conn, user_id)
    row = await conn.fetchrow(
        "/* war:lock */ SELECT * FROM casino_clan_wars WHERE war_id = $1 FOR UPDATE",
        war_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Война не найдена")
    if str(row["status"]) not in {"open", "accepted"}:
        raise HTTPException(status_code=409, detail="Набор закрыт")
    clan_id = int(membership["clan_id"])
    chall_id = int(row["challenger_clan_id"])
    opp_id = int(row["opponent_clan_id"]) if row.get("opponent_clan_id") else None
    if clan_id != chall_id and clan_id != opp_id:
        raise HTTPException(status_code=409, detail="Ваша команда не в этой войне")
    fighters = await _fighters(conn, int(row["id"]))
    if any(int(item["user_id"]) == int(user_id) for item in fighters):
        return await _named_public(conn, row, cfg, user_id)
    needed = int(row["fighters_needed"])
    side_count = len(_side_ids(fighters, clan_id))
    if side_count >= needed:
        raise HTTPException(status_code=409, detail="Состав вашей команды уже полный")
    if await _live_fight(conn, user_id):
        raise HTTPException(status_code=409, detail="Вы уже в другой войне")
    stake = money(row["stake_rub"])
    order_ref = await _hold_stake(conn, user_id=user_id, war_id=str(row["war_id"]), amount=stake)
    await conn.execute(
        """
        /* war:insert-fighter */
        INSERT INTO casino_clan_war_fighters (war_pk, clan_id, user_id, hold_order_ref)
        VALUES ($1, $2, $3, $4)
        """,
        int(row["id"]),
        clan_id,
        int(user_id),
        order_ref,
    )
    await conn.execute(
        "/* war:set-pot */ UPDATE casino_clan_wars SET pot_rub = pot_rub + $2 WHERE id = $1",
        int(row["id"]),
        stake,
    )
    publish({"type": "join", "war_id": str(row["war_id"])})
    from casino_inbox import notify_player_joined

    other_ids = [int(item["user_id"]) for item in fighters]
    creator = int(row["creator_id"])
    if creator not in other_ids and creator != int(user_id):
        other_ids.append(creator)
    await notify_player_joined(
        conn,
        joiner_id=int(user_id),
        other_ids=other_ids,
        kind="war",
        game_id=str(row["war_id"]),
        game_type="clan_war",
        stake_rub=stake,
    )
    live = await conn.fetchrow("/* war:get-pk */ SELECT * FROM casino_clan_wars WHERE id = $1", int(row["id"]))
    if await _both_full(conn, live):
        await _lock_and_settle(conn, war_pk=int(row["id"]), cfg=cfg)
        live = await conn.fetchrow("/* war:get-pk */ SELECT * FROM casino_clan_wars WHERE id = $1", int(row["id"]))
    return await _named_public(conn, live, cfg, user_id)


async def _both_full(conn, row: Mapping[str, Any]) -> bool:
    if str(row["status"]) not in {"accepted", "open"}:
        return False
    if not row.get("opponent_clan_id"):
        return False
    fighters = await _fighters(conn, int(row["id"]))
    needed = int(row["fighters_needed"])
    return (
        len(_side_ids(fighters, int(row["challenger_clan_id"]))) >= needed
        and len(_side_ids(fighters, int(row["opponent_clan_id"]))) >= needed
    )


async def _refund(conn, *, row: Mapping[str, Any], fighters: Sequence[Mapping[str, Any]]) -> None:
    stake = money(row["stake_rub"])
    for item in fighters:
        await _credit(
            conn,
            war_id=str(row["war_id"]),
            user_id=int(item["user_id"]),
            amount=stake,
            kind="refund",
        )
    await conn.execute(
        """
        /* war:refund */
        UPDATE casino_clan_wars
        SET status = 'refunded', settled_at = now()
        WHERE id = $1
        """,
        int(row["id"]),
    )
    publish({"type": "refund", "war_id": str(row["war_id"])})


async def _lock_and_settle(conn, *, war_pk: int, cfg: WarConfig) -> None:
    row = await conn.fetchrow(
        "/* war:lock-pk */ SELECT * FROM casino_clan_wars WHERE id = $1 FOR UPDATE",
        war_pk,
    )
    if not row or str(row["status"]) not in {"open", "accepted"}:
        return
    if not row.get("opponent_clan_id"):
        return
    fighters = await _fighters(conn, war_pk)
    needed = int(row["fighters_needed"])
    chall_id = int(row["challenger_clan_id"])
    opp_id = int(row["opponent_clan_id"])
    chall_ids = _side_ids(fighters, chall_id)
    opp_ids = _side_ids(fighters, opp_id)
    if len(chall_ids) < needed or len(opp_ids) < needed:
        return
    message = war_message(str(row["war_id"]), chall_id, opp_id, chall_ids, opp_ids)
    seed = str(row["server_seed"])
    index = hmac_index(seed, message, 2)
    winner_clan = chall_id if index == 0 else opp_id
    winners = chall_ids if index == 0 else opp_ids
    pot = money(money(row["stake_rub"]) * Decimal(len(chall_ids) + len(opp_ids)))
    rake, payout = rake_split(pot, cfg.rake_percent)
    shares = split_even(payout, len(winners))
    wager = {str(int(item["user_id"])): str(money(row["stake_rub"])) for item in fighters}
    await conn.execute(
        """
        /* war:lock-set */
        UPDATE casino_clan_wars
        SET status = 'locked', locked_at = now(), winner_clan_id = $2, winner_index = $3,
            pot_rub = $4, rake_rub = $5, payout_per_winner_rub = $6, wager_json = $7::jsonb
        WHERE id = $1
        """,
        war_pk,
        winner_clan,
        index,
        pot,
        rake,
        shares[0] if shares else money(0),
        json.dumps(wager),
    )
    publish({"type": "lock", "war_id": str(row["war_id"]), "winner_clan_id": winner_clan, "winner_index": index})
    for uid, amount in zip(winners, shares):
        await _credit(conn, war_id=str(row["war_id"]), user_id=int(uid), amount=amount, kind="payout")
    await _credit_house(conn, amount=rake)
    await conn.execute(
        "/* war:settle */ UPDATE casino_clan_wars SET status = 'settled', settled_at = now() WHERE id = $1",
        war_pk,
    )
    publish({"type": "settled", "war_id": str(row["war_id"]), "winner_clan_id": winner_clan})
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, *[int(item["user_id"]) for item in fighters])


async def maybe_close_due(conn) -> None:
    rows = await conn.fetch(
        """
        /* war:due */
        SELECT id FROM casino_clan_wars
        WHERE status IN ('open', 'accepted') AND closes_at IS NOT NULL AND closes_at <= now()
        ORDER BY id
        LIMIT 20
        """
    )
    for item in rows:
        row = await conn.fetchrow(
            "/* war:lock-pk */ SELECT * FROM casino_clan_wars WHERE id = $1 FOR UPDATE",
            int(item["id"]),
        )
        if not row or str(row["status"]) not in {"open", "accepted"}:
            continue
        fighters = await _fighters(conn, int(row["id"]))
        await _refund(conn, row=row, fighters=fighters)
