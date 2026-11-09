"""Shared European roulette table: one wheel vs the house, not a player pot.

One live round, HMAC pocket from round_id, each seat settles with
play_roulette_known_pocket_with_conn. Jackpot-style closer and SSE; money is
the same 1×1 house ledger, never a shared bank.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import uuid4

from fastapi import HTTPException

from casino_cards import DEFAULT_CLIENT_SEED, game_commit
from casino_chat import actor_chip, public_actors
from casino_finance import (
    casino_ledger_order_ref,
    load_casino_settings,
    lock_casino_users,
    money,
    release_unified_hold,
    reserve_unified_funds,
)
from casino_roulette import (
    POCKET_COUNT,
    ROULETTE_ALGORITHM,
    ROULETTE_BET_KEY_MAX_LENGTH,
    ROULETTE_GAME_TYPE,
    HOUSE_BANKROLL_INSUFFICIENT,
    STRAIGHT_RETURN,
    apply_roulette_stake_window,
    bet_spec,
    load_roulette_house_seat,
    load_roulette_quote_profile,
    play_roulette_known_pocket_with_conn,
    pocket_color,
    pocket_message,
    roulette_pocket,
    wheel_position,
)
from casino_settings_registry import REGISTRY
from casino_wallet import (
    RUB_SCOPE,
    WalletScope,
    active_scope,
    scope_filter_for,
    scope_from_row,
    scope_insert_sql,
    viewer_scope,
)

logger = logging.getLogger("casino_roulette_table")

CLIENT_SEED = DEFAULT_CLIENT_SEED
NONCE = 0
RECENT_WINDOW = timedelta(seconds=15)
ROULETTE_TABLE_CHIPS_MAX = 80
_subscribers: set[asyncio.Queue] = set()
_closer_started = False


@dataclass(frozen=True)
class RouletteTableConfig:
    enabled: bool
    collect_seconds: int
    max_players: int
    min_bet: Decimal
    max_bet: Decimal
    max_even_bet: Decimal = Decimal("100000")
    max_straight_bet: Decimal = Decimal("100000")


def _setting_int(values: Mapping[str, object], key: str) -> int:
    raw = values.get(key)
    if isinstance(raw, Mapping) and raw.get("value") is not None:
        return int(raw["value"])
    spec = REGISTRY.get(key)
    return int(spec.default) if spec is not None else 0  # type: ignore[arg-type]


async def load_table_config(conn) -> RouletteTableConfig:
    settings = await load_casino_settings(conn)
    rows = {str(row["key"]): row["value"] for row in await conn.fetch("SELECT key, value FROM casino_settings")}
    collect = _setting_int(rows, "roulette_table_collect_seconds") or 25
    max_players = _setting_int(rows, "roulette_table_max_players") or 24
    profile = await load_roulette_quote_profile(conn)
    even_lo, even_hi = apply_roulette_stake_window(settings, Decimal("2"), profile)
    straight_lo, straight_hi = apply_roulette_stake_window(settings, STRAIGHT_RETURN, profile)
    min_bet = max(even_lo, straight_lo)
    return RouletteTableConfig(
        enabled=bool(settings.enabled_games.get(ROULETTE_GAME_TYPE, False)),
        collect_seconds=max(5, min(collect, 120)),
        max_players=max(2, min(max_players, 48)),
        min_bet=min_bet,
        max_bet=even_hi,
        max_even_bet=even_hi,
        max_straight_bet=straight_hi,
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
            logger.exception("roulette table closer")


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


def _new_round_id() -> str:
    return f"rt-{uuid4().hex[:12]}"


def _new_seed() -> str:
    return secrets.token_hex(32)


async def _lock_open(conn, scope: WalletScope = RUB_SCOPE) -> dict[str, Any]:
    """Живой раунд своей области: у рублей, бонусов и каждого турнира он свой."""
    scope_and = await scope_filter_for(conn, "casino_roulette_rounds", scope)
    live_sql = f"""
        SELECT * FROM casino_roulette_rounds
        WHERE status IN ('open', 'locked', 'spinning'){scope_and}
        ORDER BY id DESC
        LIMIT 1
        FOR UPDATE
    """
    row = await conn.fetchrow(live_sql)
    if row:
        return dict(row)
    round_id = _new_round_id()
    seed = _new_seed()
    cols, params, values = await scope_insert_sql(
        conn, "casino_roulette_rounds", scope, next_index=4
    )
    try:
        created = await conn.fetchrow(
            f"""
            INSERT INTO casino_roulette_rounds (round_id, status, commit_hash, server_seed{cols})
            VALUES ($1, 'open', $2, $3{params})
            RETURNING *
            """,
            round_id,
            game_commit(seed, round_id),
            seed,
            *values,
        )
        return dict(created)
    except Exception:
        existing = await conn.fetchrow(live_sql)
        if existing:
            return dict(existing)
        raise


async def _bets(conn, round_pk: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id, user_id, bet, stake_rub, hold_order_ref, house_reserve_rub, display_name, game_id, notify_chat_id
        FROM casino_roulette_bets
        WHERE round_pk = $1
        ORDER BY id
        """,
        round_pk,
    )
    return [dict(row) for row in rows]


def _public_player(bet: Mapping[str, Any], actor: Mapping[str, Any]) -> dict[str, object]:
    spec = bet_spec(bet["bet"])
    return {
        "id": int(bet["id"]) if bet.get("id") is not None else 0,
        "user_id": int(bet["user_id"]),
        "display_name": actor.get("display_name") or str(bet.get("display_name") or bet["user_id"]),
        "initial": actor.get("initial") or "?",
        "avatar_url": actor.get("avatar_url"),
        "bet": spec.key,
        "stake_rub": float(money(bet["stake_rub"])),
        "pockets": sorted(spec.pockets),
        "odds_ru": spec.odds_ru,
        "title_ru": spec.title_ru,
    }


def _public_round(
    row: Mapping[str, Any],
    bets: Sequence[Mapping[str, Any]],
    cfg: RouletteTableConfig,
    *,
    actors: Mapping[int, Mapping[str, Any]],
    history: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    locked = str(row["status"]) in {"locked", "spinning", "settled"}
    pocket = int(row["pocket"]) if row.get("pocket") is not None else None
    players = [_public_player(bet, actor_chip(actors, int(bet["user_id"]))) for bet in bets]
    unique_players = {int(item["user_id"]) for item in players}
    return {
        "round_id": str(row["round_id"]),
        "status": str(row["status"]),
        "commit_hash": str(row["commit_hash"]),
        "server_seed": str(row["server_seed"]) if locked else None,
        "closes_at": _iso(row.get("closes_at")),
        "pocket": pocket,
        "color": pocket_color(pocket) if pocket is not None else None,
        "wheel_index": wheel_position(pocket) if pocket is not None else None,
        "player_count": len(unique_players),
        "max_players": cfg.max_players,
        "collect_seconds": cfg.collect_seconds,
        "min_bet_rub": float(cfg.min_bet),
        "max_bet_rub": float(cfg.max_bet),
        "max_even_bet_rub": float(cfg.max_even_bet),
        "max_straight_bet_rub": float(cfg.max_straight_bet),
        "enabled": cfg.enabled,
        "algorithm": ROULETTE_ALGORITHM,
        "modulus": POCKET_COUNT,
        "client_seed": CLIENT_SEED,
        "nonce": NONCE,
        "hmac_message": (
            pocket_message(client_seed=CLIENT_SEED, nonce=NONCE, game_id=str(row["round_id"]))
            if locked
            else None
        ),
        "players": players,
        "history": list(history),
    }


async def _history(conn, scope: WalletScope = RUB_SCOPE) -> list[dict[str, object]]:
    scope_and = await scope_filter_for(conn, "casino_roulette_rounds", scope)
    rows = await conn.fetch(
        f"""
        SELECT round_id, pocket
        FROM casino_roulette_rounds
        WHERE status = 'settled' AND pocket IS NOT NULL{scope_and}
        ORDER BY id DESC
        LIMIT 10
        """
    )
    out: list[dict[str, object]] = []
    for row in rows:
        pocket = int(row["pocket"])
        out.append(
            {
                "id": str(row["round_id"]),
                "pocket": pocket,
                "color": pocket_color(pocket),
            }
        )
    return out


async def _named_public(conn, row: Mapping[str, Any], cfg: RouletteTableConfig, viewer_id: int | None) -> dict[str, object]:
    bets = await _bets(conn, int(row["id"]))
    actors = await public_actors(conn, [int(bet["user_id"]) for bet in bets])
    history = await _history(conn, scope_from_row(row))
    payload = _public_round(row, bets, cfg, actors=actors, history=history)
    mine = [item for item in payload["players"] if viewer_id and int(item["user_id"]) == int(viewer_id)]
    payload["my_bets"] = mine
    payload["my_bet"] = str(mine[-1]["bet"]) if mine else None
    payload["my_stake_rub"] = float(sum(money(item["stake_rub"]) for item in mine))
    return payload


async def snapshot(conn, *, viewer_id: int | None = None) -> dict[str, object]:
    cfg = await load_table_config(conn)
    try:
        await maybe_close_due(conn)
    except HTTPException as exc:
        logger.warning("roulette table snapshot closer: %s", exc.detail)
    scope = await viewer_scope(conn, viewer_id)
    scope_and = await scope_filter_for(conn, "casino_roulette_rounds", scope)
    live = await conn.fetchrow(
        f"""
        SELECT * FROM casino_roulette_rounds
        WHERE status IN ('open', 'locked', 'spinning'){scope_and}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    recent = await conn.fetchrow(
        f"""
        SELECT * FROM casino_roulette_rounds
        WHERE status = 'settled'
          AND COALESCE(settled_at, locked_at, created_at) > now() - interval '15 seconds'
          {scope_and}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if live is not None and str(live["status"]) == "open":
        # Keep the new collecting round even with no seats. Overlaying the
        # last settled spin here locked every client for 15s (status≠open).
        row = live
    elif live is not None:
        row = live
    elif recent is not None:
        row = recent
    else:
        async with conn.transaction():
            row = await _lock_open(conn, scope)
    return await _named_public(conn, row, cfg, viewer_id)


async def _adjust_house_reserve(conn, *, account_id: int, delta: Decimal) -> None:
    amount = money(delta)
    if amount == 0:
        return
    if amount > 0:
        row = await conn.fetchrow(
            """
            UPDATE casino_house_accounts
            SET reserved_rub = reserved_rub + $2, updated_at = now()
            WHERE id = $1 AND balance_rub - reserved_rub >= $2
            RETURNING id
            """,
            account_id,
            amount,
        )
        if not row:
            raise HTTPException(status_code=409, detail=HOUSE_BANKROLL_INSUFFICIENT)
        return
    released = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET reserved_rub = reserved_rub - $2, updated_at = now()
        WHERE id = $1 AND reserved_rub >= $2
        RETURNING id
        """,
        account_id,
        -amount,
    )
    if not released:
        raise HTTPException(status_code=409, detail="House reservation conflicts")


def _unique_player_ids(bets: Sequence[Mapping[str, Any]]) -> set[int]:
    return {int(row["user_id"]) for row in bets}


def _chip_mapping(chip: object) -> Mapping[str, object]:
    if isinstance(chip, Mapping):
        return chip
    bet = getattr(chip, "bet", None)
    amount = getattr(chip, "amount_rub", None)
    if bet is None or amount is None:
        raise HTTPException(status_code=400, detail="Фишка без клетки или суммы")
    return {"bet": bet, "amount_rub": amount}


def _spot_cap(spec, cfg: RouletteTableConfig) -> Decimal:
    if spec.payout_multiplier >= STRAIGHT_RETURN:
        return cfg.max_straight_bet
    return cfg.max_even_bet


def _normalize_table_chip(amount_rub: object, bet: object, cfg: RouletteTableConfig) -> tuple[str, Decimal]:
    spec = bet_spec(bet)
    if len(spec.key) > ROULETTE_BET_KEY_MAX_LENGTH:
        raise HTTPException(status_code=400, detail="Ставка рулетки слишком длинная")
    chip = money(amount_rub)
    cap = _spot_cap(spec, cfg)
    if chip < cfg.min_bet or chip > cap:
        raise HTTPException(
            status_code=400,
            detail=f"Ставка вне лимита ({format(cfg.min_bet, '.2f')}–{format(cap, '.2f')} ₽)",
        )
    return spec.key, chip


def _aggregate_chips(
    chips: Sequence[object], cfg: RouletteTableConfig
) -> list[tuple[str, Decimal]]:
    totals: dict[str, Decimal] = {}
    order: list[str] = []
    for raw in chips:
        item = _chip_mapping(raw)
        key, chip = _normalize_table_chip(item.get("amount_rub"), item.get("bet"), cfg)
        if key not in totals:
            order.append(key)
            totals[key] = Decimal("0")
        totals[key] += chip
    return [(key, money(totals[key])) for key in order]


async def _write_spot(
    conn,
    *,
    user_id: int,
    round_row: Mapping[str, Any],
    bet_key: str,
    new_stake: Decimal,
    new_reserve: Decimal,
    existing: Mapping[str, Any] | None,
    display_name: str,
    notify_chat_id: int | None = None,
) -> None:
    hold_id = f"roulette-table-{round_row['round_id']}-{user_id}-{uuid4().hex[:8]}"
    order_ref = casino_ledger_order_ref(hold_id)
    old_stake = money(existing["stake_rub"]) if existing else Decimal("0")
    old_hold = str(existing["hold_order_ref"]) if existing else ""
    if existing:
        await release_unified_hold(
            conn,
            user_id=user_id,
            order_ref=old_hold,
            amount_rub=old_stake,
            note=f"Roulette table stack {round_row['round_id']} {bet_key}",
        )
    try:
        await reserve_unified_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=new_stake)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось забронировать ставку") from exc
    if existing:
        await conn.execute(
            """
            UPDATE casino_roulette_bets
            SET stake_rub = $2, hold_order_ref = $3, house_reserve_rub = $4, display_name = $5,
                notify_chat_id = COALESCE(notify_chat_id, $6)
            WHERE id = $1
            """,
            int(existing["id"]),
            new_stake,
            order_ref,
            new_reserve,
            display_name,
            notify_chat_id,
        )
        return
    await conn.execute(
        """
        INSERT INTO casino_roulette_bets (
            round_pk, user_id, bet, stake_rub, hold_order_ref, house_reserve_rub, display_name, notify_chat_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        int(round_row["id"]),
        int(user_id),
        bet_key,
        new_stake,
        order_ref,
        new_reserve,
        display_name,
        notify_chat_id,
    )


async def place_bets(
    conn, *, user_id: int, chips: Sequence[object], notify_chat_id: int | None = None
) -> dict[str, object]:
    """Confirm a draft: many felt spots, one transaction, one SSE bet event."""
    if not chips:
        raise HTTPException(status_code=400, detail="Нет фишек")
    if len(chips) > ROULETTE_TABLE_CHIPS_MAX:
        raise HTTPException(status_code=400, detail="Слишком много фишек")
    cfg = await load_table_config(conn)
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Рулетка против казино выключена")
    # Стол живёт отдельно в каждой области кошелька: рубли, бонусные фишки, турнир.
    scope = await active_scope(conn, user_id)
    stacked = _aggregate_chips(chips, cfg)
    await maybe_close_due(conn)
    round_row = await _lock_open(conn, scope)
    if str(round_row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Раунд уже крутится")
    await lock_casino_users(conn, (user_id,))
    bets = await _bets(conn, int(round_row["id"]))
    occupied = _unique_player_ids(bets)
    if int(user_id) not in occupied:
        from casino_live_sessions import assert_can_sit

        await assert_can_sit(conn, user_id)
    if int(user_id) not in occupied and len(occupied) >= cfg.max_players:
        raise HTTPException(status_code=409, detail="Раунд заполнен")

    planned: list[tuple[str, Decimal, dict[str, Any] | None, Decimal, Decimal]] = []
    already_net = Decimal("0")
    seats: list[Any] = []
    for bet_key, chip in stacked:
        existing = next(
            (row for row in bets if int(row["user_id"]) == int(user_id) and str(row["bet"]) == bet_key),
            None,
        )
        old_reserve = money(existing["house_reserve_rub"]) if existing else Decimal("0")
        old_stake = money(existing["stake_rub"]) if existing else Decimal("0")
        new_stake = old_stake + chip
        cap = _spot_cap(bet_spec(bet_key), cfg)
        if new_stake > cap:
            raise HTTPException(
                status_code=400,
                detail=f"Ставка вне лимита ({format(cfg.min_bet, '.2f')}–{format(cap, '.2f')} ₽)",
            )
        extra = old_reserve - already_net
        seat = await load_roulette_house_seat(
            conn,
            telegram_id=user_id,
            stake_rub=new_stake,
            bet=bet_key,
            extra_available_rub=extra,
            require_bankroll=scope.is_rub,
        )
        new_reserve = money(seat.max_settlement.payout)
        already_net += new_reserve - old_reserve
        planned.append((bet_key, new_stake, existing, old_reserve, new_reserve))
        seats.append(seat)

    actors = await public_actors(conn, [user_id])
    actor = actor_chip(actors, user_id)
    display_name = str(actor.get("display_name") or user_id)[:80]
    stored_chat = next(
        (
            int(row["notify_chat_id"])
            for row in bets
            if int(row["user_id"]) == int(user_id) and row.get("notify_chat_id") is not None
        ),
        int(notify_chat_id) if notify_chat_id not in (None, 0) else None,
    )
    for (bet_key, new_stake, existing, old_reserve, new_reserve), seat in zip(planned, seats, strict=True):
        if scope.is_rub:
            await _adjust_house_reserve(
                conn, account_id=int(seat.profile["account_id"]), delta=new_reserve - old_reserve
            )
        await _write_spot(
            conn,
            user_id=user_id,
            round_row=round_row,
            bet_key=bet_key,
            new_stake=new_stake,
            new_reserve=new_reserve,
            existing=existing,
            display_name=display_name,
            notify_chat_id=stored_chat,
        )

    if round_row.get("closes_at") is None:
        closes_at = datetime.now(timezone.utc) + timedelta(seconds=cfg.collect_seconds)
        await conn.execute(
            "UPDATE casino_roulette_rounds SET closes_at = $2 WHERE id = $1",
            int(round_row["id"]),
            closes_at,
        )
    round_pk = int(round_row["id"])
    live = await conn.fetchrow("SELECT * FROM casino_roulette_rounds WHERE id = $1", round_pk)
    snap = await _named_public(conn, live, cfg, user_id)
    publish({"type": "bet", "round_id": snap["round_id"]})
    bets = await _bets(conn, round_pk)
    if len(_unique_player_ids(bets)) >= cfg.max_players:
        await _lock_and_settle(conn, round_pk=round_pk, cfg=cfg)
        settled = await conn.fetchrow("SELECT * FROM casino_roulette_rounds WHERE id = $1", round_pk)
        return await _named_public(conn, settled, cfg, user_id)
    return snap


async def place_bet(
    conn, *, user_id: int, amount_rub: Decimal, bet: str, notify_chat_id: int | None = None
) -> dict[str, object]:
    """Add a chip to one felt spot. A second chip on the same spot stacks; a new spot stays."""
    return await place_bets(
        conn,
        user_id=user_id,
        chips=[{"bet": bet, "amount_rub": amount_rub}],
        notify_chat_id=notify_chat_id,
    )


async def clear_bets(conn, *, user_id: int, bet: str | None = None) -> dict[str, object]:
    """Take this player's chips off the open round. `bet` clears one spot; omit it to clear all."""
    cfg = await load_table_config(conn)
    await maybe_close_due(conn)
    scope = await active_scope(conn, user_id)
    scope_and = await scope_filter_for(conn, "casino_roulette_rounds", scope)
    round_row = await conn.fetchrow(
        f"""
        SELECT * FROM casino_roulette_rounds
        WHERE status = 'open'{scope_and}
        ORDER BY id DESC
        LIMIT 1
        FOR UPDATE
        """
    )
    if not round_row:
        return await snapshot(conn, viewer_id=user_id)
    if str(round_row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Раунд уже крутится")
    await lock_casino_users(conn, (user_id,))
    spec_key = bet_spec(bet).key if bet else None
    bets = await _bets(conn, int(round_row["id"]))
    mine = [row for row in bets if int(row["user_id"]) == int(user_id)]
    if spec_key is not None:
        mine = [row for row in mine if str(row["bet"]) == spec_key]
    if not mine:
        return await _named_public(conn, round_row, cfg, user_id)
    first = mine[0]
    covered = sum((money(row["house_reserve_rub"]) for row in mine), Decimal("0"))
    seat = await load_roulette_house_seat(
        conn,
        telegram_id=user_id,
        stake_rub=money(first["stake_rub"]),
        bet=str(first["bet"]),
        extra_available_rub=covered,
        require_bankroll=scope.is_rub,
    )
    account_id = int(seat.profile["account_id"])
    for row in mine:
        await release_unified_hold(
            conn,
            user_id=user_id,
            order_ref=str(row["hold_order_ref"]),
            amount_rub=money(row["stake_rub"]),
            note=f"Roulette table clear {round_row['round_id']} {row['bet']}",
        )
        if scope.is_rub:
            await _adjust_house_reserve(
                conn, account_id=account_id, delta=-money(row["house_reserve_rub"])
            )
        await conn.execute("DELETE FROM casino_roulette_bets WHERE id = $1", int(row["id"]))
    live = await conn.fetchrow("SELECT * FROM casino_roulette_rounds WHERE id = $1", int(round_row["id"]))
    snap = await _named_public(conn, live, cfg, user_id)
    publish({"type": "bet", "round_id": snap["round_id"]})
    return snap


def _color_ru(color: str | None) -> str:
    if color == "red":
        return "красное"
    if color == "black":
        return "чёрное"
    if color == "green":
        return "зеро"
    return ""


def _format_money_rub(value: object) -> str:
    amount = money(value)
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _settle_chat_html(
    *,
    pocket: int,
    color: str | None,
    bets: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, object]],
) -> str:
    payout_by_spot: dict[tuple[int, str], Mapping[str, object]] = {}
    for row in results:
        payout_by_spot[(int(row["user_id"]), str(row["bet"]))] = row
    color_label = _color_ru(color)
    lines = [f"🎡 <b>Рулетка</b> · выпало <b>{int(pocket)}</b> {html.escape(color_label)}".rstrip()]
    for bet in bets:
        user_id = int(bet["user_id"])
        spec = bet_spec(bet["bet"])
        paid = payout_by_spot.get((user_id, spec.key), {})
        payout = _format_money_rub(paid.get("payout_rub") or 0)
        stake = _format_money_rub(bet["stake_rub"])
        name = html.escape(str(bet.get("display_name") or user_id)[:80])
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        title = html.escape(spec.title_ru)
        won = bool(paid.get("won"))
        verdict = "выигрыш" if won else "проигрыш"
        lines.append(f"{mention}: {title} · {stake} ₽ → {payout} ₽ ({verdict})")
    return "\n".join(lines)


async def _enqueue_telegram_results(
    conn,
    *,
    round_id: str,
    pocket: int,
    color: str | None,
    bets: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, object]],
) -> None:
    by_chat: dict[int, list[Mapping[str, Any]]] = {}
    for bet in bets:
        raw = bet.get("notify_chat_id")
        if raw is None:
            continue
        chat_id = int(raw)
        if chat_id == 0:
            continue
        by_chat.setdefault(chat_id, []).append(bet)
    for chat_id, chat_bets in by_chat.items():
        recipient_id = next((int(row["user_id"]) for row in chat_bets if int(row["user_id"]) > 0), 0)
        if recipient_id <= 0:
            continue
        text = _settle_chat_html(pocket=pocket, color=color, bets=chat_bets, results=results)
        game_id = f"{round_id}:{chat_id}"[:64]
        payload = json.dumps(
            {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            separators=(",", ":"),
            ensure_ascii=False,
        )
        await conn.execute(
            """
            INSERT INTO casino_notification_outbox (event_key, event_type, game_id, recipient_id, payload)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (game_id, event_type, recipient_id) DO NOTHING
            """,
            f"casino:{game_id}:roulette_table_settled:{recipient_id}",
            "roulette_table_settled",
            game_id,
            recipient_id,
            payload,
        )


async def _lock_and_settle(conn, *, round_pk: int, cfg: RouletteTableConfig) -> None:
    row = await conn.fetchrow("SELECT * FROM casino_roulette_rounds WHERE id = $1 FOR UPDATE", round_pk)
    if not row:
        return
    status = str(row["status"])
    if status == "settled":
        return
    scope = scope_from_row(row)
    bets = await _bets(conn, round_pk)
    round_id = str(row["round_id"])
    if status == "open" and not bets:
        await conn.execute(
            """
            UPDATE casino_roulette_rounds
            SET status = 'settled', settled_at = now(), closes_at = NULL
            WHERE id = $1
            """,
            round_pk,
        )
        publish({"type": "idle", "round_id": round_id})
        await _lock_open(conn, scope)
        return
    seed = str(row["server_seed"])
    commit = str(row["commit_hash"])
    if status == "open":
        pocket = roulette_pocket(seed, round_id, client_seed=CLIENT_SEED, nonce=NONCE)
        await conn.execute(
            """
            UPDATE casino_roulette_rounds
            SET status = 'locked', locked_at = now(), pocket = $2
            WHERE id = $1
            """,
            round_pk,
            pocket,
        )
        locked = await conn.fetchrow("SELECT * FROM casino_roulette_rounds WHERE id = $1", round_pk)
        spin_view = await _named_public(conn, locked, cfg, None)
        publish({"type": "lock", "round_id": round_id})
        publish(
            {
                "type": "spin",
                "round_id": round_id,
                "pocket": pocket,
                "color": pocket_color(pocket),
                "wheel_index": wheel_position(pocket),
                "server_seed": seed,
                "commit_hash": commit,
                "client_seed": CLIENT_SEED,
                "nonce": NONCE,
                "hmac_message": pocket_message(client_seed=CLIENT_SEED, nonce=NONCE, game_id=round_id),
                "players": spin_view["players"],
            }
        )
        await conn.execute(
            "UPDATE casino_roulette_rounds SET status = 'spinning' WHERE id = $1",
            round_pk,
        )
    else:
        pocket = int(row["pocket"]) if row.get("pocket") is not None else roulette_pocket(
            seed, round_id, client_seed=CLIENT_SEED, nonce=NONCE
        )
        if status == "locked":
            await conn.execute(
                "UPDATE casino_roulette_rounds SET status = 'spinning' WHERE id = $1",
                round_pk,
            )
    results: list[dict[str, object]] = []
    pending = [bet for bet in bets if not bet.get("game_id")]
    for bet in pending:
        bet_pk = int(bet["id"]) if bet.get("id") is not None else int(bet["user_id"])
        seat_game_id = f"{round_id}-b{bet_pk}"
        payload = await play_roulette_known_pocket_with_conn(
            conn,
            telegram_id=int(bet["user_id"]),
            stake_rub=money(bet["stake_rub"]),
            bet=str(bet["bet"]),
            pocket=pocket,
            seed=seed,
            rng_commit=commit,
            hmac_game_id=round_id,
            hold_order_ref=str(bet["hold_order_ref"]),
            reserved_payout=money(bet["house_reserve_rub"]),
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            game_id=seat_game_id,
            scope=scope,
        )
        await conn.execute(
            "UPDATE casino_roulette_bets SET game_id = $2 WHERE id = $1",
            bet_pk,
            seat_game_id,
        )
        results.append(
            {
                "user_id": int(bet["user_id"]),
                "bet": str(payload["bet"]),
                "won": bool(payload["won"]),
                "payout_rub": float(payload["payout_rub"]),
                "game_id": seat_game_id,
            }
        )
    await conn.execute(
        "UPDATE casino_roulette_rounds SET status = 'settled', settled_at = now() WHERE id = $1",
        round_pk,
    )
    publish({"type": "settled", "round_id": round_id, "pocket": pocket, "results": results})
    await _enqueue_telegram_results(
        conn,
        round_id=round_id,
        pocket=pocket,
        color=pocket_color(pocket),
        bets=bets,
        results=results,
    )
    await _lock_open(conn, scope)


async def maybe_close_due(conn) -> None:
    cfg = await load_table_config(conn)
    row = await conn.fetchrow(
        """
        SELECT id
        FROM casino_roulette_rounds
        WHERE (status = 'open' AND closes_at IS NOT NULL AND closes_at <= now())
           OR status IN ('locked', 'spinning')
        ORDER BY id
        LIMIT 1
        """
    )
    if not row:
        return
    await _lock_and_settle(conn, round_pk=int(row["id"]), cfg=cfg)
