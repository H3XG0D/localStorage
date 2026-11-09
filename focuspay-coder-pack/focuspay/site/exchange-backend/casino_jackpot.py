"""CSGETGO-style jackpot: ticket-weighted pot, committed roll, avatar reel."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping, Sequence
from uuid import uuid4

from fastapi import HTTPException

from casino_chat import actor_chip, public_actors
from casino_finance import (
    casino_ledger_order_ref,
    casino_operation_ref,
    confirm_unified_hold,
    credit_house_game_settlement,
    load_casino_settings,
    money,
    maybe_credit_tournament_payout,
    reserve_unified_funds,
)
from casino_settings_registry import REGISTRY, default_numeric
from casino_wallet import (
    RUB_SCOPE,
    WalletScope,
    active_scope,
    scope_filter_for,
    scope_from_row,
    scope_insert_sql,
    viewer_scope,
)

logger = logging.getLogger("casino_jackpot")

GAME_TYPE = "jackpot"
TICKETS_PER_RUBLE = 100
_subscribers: set[asyncio.Queue] = set()
_closer_started = False


@dataclass(frozen=True)
class JackpotConfig:
    enabled: bool
    collect_seconds: int
    max_players: int
    rake_percent: Decimal
    min_bet: Decimal
    max_bet: Decimal


def tickets_for_amount(amount: Decimal | int | float | str) -> int:
    kopecks = int((money(amount) * Decimal("100")).to_integral_value(rounding=ROUND_DOWN))
    return kopecks  # 1 ₽ = 100 tickets


def make_roll() -> str:
    n = secrets.randbits(256)
    return format(n / (2**256), ".32f")


def commit_roll(roll: str) -> str:
    return hashlib.sha256((roll or "").encode("utf-8")).hexdigest()


def winning_ticket(roll: str, total_tickets: int) -> int:
    if total_tickets <= 0:
        raise ValueError("no tickets")
    raw = (Decimal(roll) * Decimal(total_tickets)).to_integral_value(rounding=ROUND_DOWN)
    ticket = int(raw)
    if ticket < 0:
        ticket = 0
    if ticket >= total_tickets:
        ticket = total_tickets - 1
    return ticket


def assign_ranges(stakes: Sequence[tuple[int, Decimal]]) -> list[dict[str, object]]:
    cursor = 0
    out: list[dict[str, object]] = []
    for user_id, amount in stakes:
        tickets = tickets_for_amount(amount)
        if tickets <= 0:
            continue
        start = cursor
        end = cursor + tickets - 1
        out.append(
            {
                "user_id": int(user_id),
                "amount_rub": money(amount),
                "tickets": tickets,
                "ticket_from": start,
                "ticket_to": end,
            }
        )
        cursor = end + 1
    return out


def pick_winner(ranges: Sequence[Mapping[str, object]], ticket: int) -> int | None:
    for row in ranges:
        start = int(row["ticket_from"])
        end = int(row["ticket_to"])
        if start <= ticket <= end:
            return int(row["user_id"])
    return None


def rake_split(pot: Decimal, percent: Decimal) -> tuple[Decimal, Decimal]:
    bank = money(pot)
    rake = money(bank * money(percent) / Decimal("100"))
    payout = money(bank - rake)
    return rake, payout


def verify_jackpot_round(
    *,
    roll: str,
    commit: str,
    total_tickets: int,
    expected_ticket: int | None = None,
    expected_winner: int | None = None,
    ranges: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    computed = commit_roll(roll)
    commit_matches = computed.lower() == (commit or "").strip().lower()
    ticket = winning_ticket(roll, total_tickets) if total_tickets > 0 else None
    ticket_matches = expected_ticket is None or ticket == int(expected_ticket)
    winner = pick_winner(ranges or (), ticket) if ticket is not None and ranges else None
    winner_matches = expected_winner is None or winner == int(expected_winner)
    matches = bool(commit_matches and ticket_matches and winner_matches)
    return {
        "matches": matches,
        "commit_matches": commit_matches,
        "ticket_matches": ticket_matches,
        "winner_matches": winner_matches,
        "computed_commit": computed,
        "winning_ticket": ticket,
        "winner_id": winner,
        "total_tickets": total_tickets,
        "algorithm": "sha256-roll-x-tickets",
    }


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


async def load_jackpot_config(conn) -> JackpotConfig:
    settings = await load_casino_settings(conn)
    rows = {str(row["key"]): row["value"] for row in await conn.fetch("SELECT key, value FROM casino_settings")}
    collect = _setting_int(rows, "jackpot_collect_seconds") or 300
    max_players = _setting_int(rows, "jackpot_max_players") or 30
    rake = _setting_percent(rows, "jackpot_rake_percent")
    if rake == 0 and "jackpot_rake_percent" not in rows:
        rake = money(default_numeric("jackpot_rake_percent"))
    return JackpotConfig(
        enabled=bool(settings.enabled_games.get(GAME_TYPE, False)),
        collect_seconds=max(30, min(collect, 3600)),
        max_players=max(2, min(max_players, 100)),
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
            logger.exception("jackpot closer")


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


async def _lock_open(conn, scope: WalletScope = RUB_SCOPE) -> dict[str, Any]:
    """Открытый раунд своей области: у рублей, бонусов и каждого турнира он свой."""
    scope_and = await scope_filter_for(conn, "casino_jackpot_rounds", scope)
    open_sql = f"""
        SELECT * FROM casino_jackpot_rounds
        WHERE status IN ('open', 'locked'){scope_and}
        ORDER BY id DESC
        LIMIT 1
        FOR UPDATE
        """
    row = await conn.fetchrow(open_sql)
    if row:
        return dict(row)
    roll = make_roll()
    round_id = f"jp-{uuid4().hex[:12]}"
    scope_cols, scope_params, scope_values = await scope_insert_sql(
        conn, "casino_jackpot_rounds", scope, next_index=4
    )
    # Вставка в своей точке сохранения: иначе гонка за живой раунд рвёт внешнюю
    # транзакцию и повторное чтение падает с InFailedSQLTransactionError.
    try:
        async with conn.transaction():
            created = await conn.fetchrow(
                f"""
                INSERT INTO casino_jackpot_rounds (round_id, status, commit_hash, roll{scope_cols})
                VALUES ($1, 'open', $2, $3{scope_params})
                RETURNING *
                """,
                round_id,
                commit_roll(roll),
                roll,
                *scope_values,
            )
        return dict(created)
    except Exception:
        existing = await conn.fetchrow(open_sql)
        if existing:
            return dict(existing)
        raise


def _format_money_rub(value: object) -> str:
    amount = money(value)
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _notify_chat(value: object) -> int | None:
    if value is None:
        return None
    try:
        chat_id = int(value)
    except (TypeError, ValueError):
        return None
    if chat_id == 0:
        return None
    return chat_id


def settle_chat_html(snap: Mapping[str, object], *, refund: bool = False) -> str:
    pot = _format_money_rub(snap.get("pot_rub") or 0)
    rake_pct = _format_money_rub(snap.get("rake_percent") or 0)
    lines = ["🎡 <b>Джекпот</b>"]
    players = snap.get("players") if isinstance(snap.get("players"), list) else []
    if refund:
        lines.append(f"Один игрок — ставка возвращена. Банк {pot} ₽.")
    else:
        rake = _format_money_rub(snap.get("rake_rub") or 0)
        payout = _format_money_rub(snap.get("payout_rub") or 0)
        lines.append(f"Банк: <b>{pot} ₽</b> · рейк {rake_pct}% ({rake} ₽)")
        lines.append(f"Выплата: <b>{payout} ₽</b>")
        winner_id = snap.get("winner_id")
        winner = next(
            (
                player
                for player in players
                if isinstance(player, Mapping) and int(player.get("user_id") or 0) == int(winner_id or 0)
            ),
            None,
        )
        if winner is not None:
            uid = int(winner["user_id"])
            name = html.escape(str(winner.get("display_name") or uid)[:80])
            mention = f'<a href="tg://user?id={uid}">{name}</a>'
            chance = _format_money_rub(winner.get("chance_pct") or 0)
            lines.append(f"Победитель: {mention} ({chance}%)")
    for player in players:
        if not isinstance(player, Mapping):
            continue
        uid = int(player.get("user_id") or 0)
        name = html.escape(str(player.get("display_name") or uid)[:80])
        mention = f'<a href="tg://user?id={uid}">{name}</a>' if uid > 0 else name
        amount = _format_money_rub(player.get("amount_rub") or 0)
        chance = _format_money_rub(player.get("chance_pct") or 0)
        lines.append(f"• {mention} — {amount} ₽ ({chance}%)")
    return "\n".join(lines)


async def _enqueue_telegram_results(
    conn,
    *,
    round_id: str,
    event_type: str,
    text: str,
    bets: Sequence[Mapping[str, Any]],
) -> None:
    by_chat: dict[int, list[Mapping[str, Any]]] = {}
    for bet in bets:
        chat_id = _notify_chat(bet.get("notify_chat_id"))
        if chat_id is None:
            continue
        by_chat.setdefault(chat_id, []).append(bet)
    for chat_id, chat_bets in by_chat.items():
        recipient_id = next((int(row["user_id"]) for row in chat_bets if int(row["user_id"]) > 0), 0)
        if recipient_id <= 0:
            continue
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
            f"casino:{game_id}:{event_type}:{recipient_id}",
            event_type,
            game_id,
            recipient_id,
            payload,
        )


async def _bets(conn, round_pk: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT user_id, amount_rub, ticket_from, ticket_to, hold_order_ref, notify_chat_id
        FROM casino_jackpot_bets
        WHERE round_pk = $1
        ORDER BY id
        """,
        round_pk,
    )
    return [dict(row) for row in rows]


def _public_round(
    row: Mapping[str, Any],
    bets: Sequence[Mapping[str, Any]],
    cfg: JackpotConfig,
    *,
    actors: Mapping[int, Mapping[str, Any]],
) -> dict[str, object]:
    pot = money(row["pot_rub"])
    players = []
    total_tickets = 0
    for bet in bets:
        amount = money(bet["amount_rub"])
        tickets = int(bet["ticket_to"]) - int(bet["ticket_from"]) + 1
        total_tickets += tickets
        user_id = int(bet["user_id"])
        actor = actor_chip(actors, user_id)
        players.append(
            {
                "user_id": user_id,
                "display_name": actor["display_name"],
                "initial": actor["initial"],
                "avatar_url": actor.get("avatar_url"),
                "amount_rub": float(amount),
                "chance_pct": float((amount / pot * Decimal("100")) if pot > 0 else 0),
                "ticket_from": int(bet["ticket_from"]),
                "ticket_to": int(bet["ticket_to"]),
            }
        )
    locked = str(row["status"]) in {"locked", "settled"}
    return {
        "round_id": str(row["round_id"]),
        "status": str(row["status"]),
        "commit_hash": str(row["commit_hash"]),
        "roll": str(row["roll"]) if locked else None,
        "closes_at": _iso(row.get("closes_at")),
        "pot_rub": float(pot),
        "rake_percent": float(cfg.rake_percent),
        "rake_rub": float(money(row["rake_rub"])) if locked else None,
        "payout_rub": float(money(row["payout_rub"])) if str(row["status"]) == "settled" else None,
        "winner_id": int(row["winner_id"]) if row.get("winner_id") else None,
        "winning_ticket": int(row["winning_ticket"]) if row.get("winning_ticket") is not None else None,
        "player_count": len(players),
        "max_players": cfg.max_players,
        "collect_seconds": cfg.collect_seconds,
        "min_bet_rub": float(cfg.min_bet),
        "max_bet_rub": float(cfg.max_bet),
        "enabled": cfg.enabled,
        "players": players,
        "total_tickets": total_tickets,
    }


async def _named_public(conn, row: Mapping[str, Any], cfg: JackpotConfig, viewer_id: int | None) -> dict[str, object]:
    bets = await _bets(conn, int(row["id"]))
    actors = await public_actors(conn, [int(bet["user_id"]) for bet in bets])
    payload = _public_round(row, bets, cfg, actors=actors)
    mine = None
    if viewer_id:
        mine = next((item for item in payload["players"] if int(item["user_id"]) == int(viewer_id)), None)
    payload["my_amount_rub"] = mine["amount_rub"] if mine else 0
    payload["my_chance_pct"] = mine["chance_pct"] if mine else 0
    return payload


async def snapshot(conn, *, viewer_id: int | None = None) -> dict[str, object]:
    cfg = await load_jackpot_config(conn)
    await maybe_close_due(conn)
    scope = await viewer_scope(conn, viewer_id)
    scope_and = await scope_filter_for(conn, "casino_jackpot_rounds", scope)
    live = await conn.fetchrow(
        f"""
        SELECT * FROM casino_jackpot_rounds
        WHERE status IN ('open', 'locked'){scope_and}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    recent = await conn.fetchrow(
        f"""
        SELECT * FROM casino_jackpot_rounds
        WHERE status IN ('settled', 'refunded')
          AND COALESCE(settled_at, locked_at, created_at) > now() - interval '15 seconds'{scope_and}
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if live is not None and str(live["status"]) == "open" and money(live["pot_rub"]) <= 0 and recent is not None:
        row = recent
    elif live is not None:
        row = live
    elif recent is not None:
        row = recent
    else:
        async with conn.transaction():
            row = await _lock_open(conn, scope)
    return await _named_public(conn, row, cfg, viewer_id)


async def place_bet(
    conn, *, user_id: int, amount_rub: Decimal, notify_chat_id: int | None = None
) -> dict[str, object]:
    cfg = await load_jackpot_config(conn)
    if not cfg.enabled:
        raise HTTPException(status_code=409, detail="Джекпот выключен")
    amount = money(amount_rub)
    if amount < cfg.min_bet or amount > cfg.max_bet:
        raise HTTPException(status_code=400, detail="Ставка вне лимита")
    await maybe_close_due(conn)
    round_row = await _lock_open(conn, await active_scope(conn, user_id))
    if str(round_row["status"]) != "open":
        raise HTTPException(status_code=409, detail="Раунд уже крутится")
    bets = await _bets(conn, int(round_row["id"]))
    existing = next((row for row in bets if int(row["user_id"]) == int(user_id)), None)
    if existing is None:
        from casino_live_sessions import assert_can_sit

        await assert_can_sit(conn, user_id)
    if existing is None and len(bets) >= cfg.max_players:
        raise HTTPException(status_code=409, detail="Раунд заполнен")
    new_total = money((existing["amount_rub"] if existing else 0) + amount)
    if new_total > cfg.max_bet:
        raise HTTPException(status_code=400, detail="Сумма ставки больше лимита")
    hold_id = f"jackpot-{round_row['round_id']}-{user_id}-{uuid4().hex[:8]}"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=amount)
        await confirm_unified_hold(
            conn,
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=amount,
            note=f"Jackpot bet {round_row['round_id']}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось списать ставку") from exc
    existing_chat = _notify_chat(existing.get("notify_chat_id")) if existing else None
    stored_chat = existing_chat if existing_chat is not None else _notify_chat(notify_chat_id)
    if existing:
        await conn.execute(
            """
            UPDATE casino_jackpot_bets
            SET amount_rub = $3, hold_order_ref = $4,
                notify_chat_id = COALESCE(notify_chat_id, $5)
            WHERE round_pk = $1 AND user_id = $2
            """,
            int(round_row["id"]),
            int(user_id),
            new_total,
            order_ref,
            stored_chat,
        )
    else:
        await conn.execute(
            """
            INSERT INTO casino_jackpot_bets (round_pk, user_id, amount_rub, hold_order_ref, notify_chat_id)
            VALUES ($1, $2, $3, $4, $5)
            """,
            int(round_row["id"]),
            int(user_id),
            amount,
            order_ref,
            stored_chat,
        )
    bets = await _bets(conn, int(round_row["id"]))
    ranges = assign_ranges([(int(row["user_id"]), money(row["amount_rub"])) for row in bets])
    by_user = {int(item["user_id"]): item for item in ranges}
    pot = money(sum((money(row["amount_rub"]) for row in bets), Decimal("0")))
    closes_at = round_row.get("closes_at")
    if closes_at is None:
        closes_at = datetime.now(timezone.utc) + timedelta(seconds=cfg.collect_seconds)
    for row in bets:
        item = by_user[int(row["user_id"])]
        await conn.execute(
            """
            UPDATE casino_jackpot_bets
            SET ticket_from = $3, ticket_to = $4
            WHERE round_pk = $1 AND user_id = $2
            """,
            int(round_row["id"]),
            int(row["user_id"]),
            int(item["ticket_from"]),
            int(item["ticket_to"]),
        )
    await conn.execute(
        """
        UPDATE casino_jackpot_rounds
        SET pot_rub = $2, closes_at = $3
        WHERE id = $1
        """,
        int(round_row["id"]),
        pot,
        closes_at,
    )
    round_pk = int(round_row["id"])
    live = await conn.fetchrow("SELECT * FROM casino_jackpot_rounds WHERE id = $1", round_pk)
    snap = await _named_public(conn, live, cfg, user_id)
    publish({"type": "bet", "round_id": snap["round_id"]})
    if len(bets) >= cfg.max_players:
        await _lock_and_settle(conn, round_pk=round_pk, cfg=cfg)
        settled = await conn.fetchrow("SELECT * FROM casino_jackpot_rounds WHERE id = $1", round_pk)
        return await _named_public(conn, settled, cfg, user_id)
    return snap


async def _credit(conn, *, round_id: str, user_id: int, amount: Decimal, kind: str) -> None:
    payout = money(amount)
    if payout <= 0:
        return
    order_id = casino_operation_ref(kind, round_id, str(user_id))
    if await maybe_credit_tournament_payout(
        conn, user_id=user_id, order_id=order_id, amount_rub=payout, game_id=round_id
    ):
        return
    inserted = await conn.fetchrow(
        """
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING user_id, amount_rub
        """,
        user_id,
        payout,
        order_id,
        f"Jackpot {kind} {round_id}",
    )
    existing = inserted or await conn.fetchrow(
        "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1",
        order_id,
    )
    if not existing or int(existing["user_id"]) != user_id or money(existing["amount_rub"]) != payout:
        raise HTTPException(status_code=409, detail="Jackpot payout conflicts")


async def _credit_house(conn, *, amount: Decimal, entry_key: str, reason: str) -> None:
    try:
        await credit_house_game_settlement(
            conn, amount_rub=amount, entry_key=entry_key, reason=reason
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _lock_and_settle(conn, *, round_pk: int, cfg: JackpotConfig) -> None:
    row = await conn.fetchrow("SELECT * FROM casino_jackpot_rounds WHERE id = $1 FOR UPDATE", round_pk)
    if not row or str(row["status"]) != "open":
        return
    bets = await _bets(conn, round_pk)
    if len(bets) < 2:
        for bet in bets:
            await _credit(
                conn,
                round_id=str(row["round_id"]),
                user_id=int(bet["user_id"]),
                amount=money(bet["amount_rub"]),
                kind="refund",
            )
        await conn.execute(
            """
            UPDATE casino_jackpot_rounds
            SET status = 'refunded', settled_at = now(), roll = roll
            WHERE id = $1
            """,
            round_pk,
        )
        refunded = await conn.fetchrow("SELECT * FROM casino_jackpot_rounds WHERE id = $1", round_pk)
        view = await _named_public(conn, refunded, cfg, None)
        await _enqueue_telegram_results(
            conn,
            round_id=str(row["round_id"]),
            event_type="jackpot_refunded",
            text=settle_chat_html(view, refund=True),
            bets=bets,
        )
        publish({"type": "refund", "round_id": str(row["round_id"])})
        await _lock_open(conn)
        return
    ranges = assign_ranges([(int(item["user_id"]), money(item["amount_rub"])) for item in bets])
    for item in ranges:
        await conn.execute(
            """
            UPDATE casino_jackpot_bets
            SET ticket_from = $3, ticket_to = $4
            WHERE round_pk = $1 AND user_id = $2
            """,
            round_pk,
            int(item["user_id"]),
            int(item["ticket_from"]),
            int(item["ticket_to"]),
        )
    bets = await _bets(conn, round_pk)
    roll = str(row["roll"])
    ticket = winning_ticket(roll, int(ranges[-1]["ticket_to"]) + 1)
    winner_id = pick_winner(ranges, ticket)
    if winner_id is None:
        raise HTTPException(status_code=500, detail="Не удалось выбрать победителя")
    pot = money(row["pot_rub"])
    rake, payout = rake_split(pot, cfg.rake_percent)
    wager = {str(int(item["user_id"])): str(money(item["amount_rub"])) for item in bets}
    await conn.execute(
        """
        UPDATE casino_jackpot_rounds
        SET status = 'locked', locked_at = now(), winning_ticket = $2, winner_id = $3,
            rake_rub = $4, payout_rub = $5, wager_json = $6::jsonb
        WHERE id = $1
        """,
        round_pk,
        ticket,
        winner_id,
        rake,
        payout,
        json.dumps(wager),
    )
    locked = await conn.fetchrow("SELECT * FROM casino_jackpot_rounds WHERE id = $1", round_pk)
    spin_view = await _named_public(conn, locked, cfg, None)
    publish({"type": "lock", "round_id": str(row["round_id"])})
    publish(
        {
            "type": "spin",
            "round_id": str(row["round_id"]),
            "winner_id": winner_id,
            "winning_ticket": ticket,
            "roll": roll,
            "commit_hash": str(row["commit_hash"]),
            "pot_rub": float(pot),
            "rake_rub": float(rake),
            "payout_rub": float(payout),
            "total_tickets": spin_view.get("total_tickets"),
            "players": spin_view["players"],
        }
    )
    await _credit(conn, round_id=str(row["round_id"]), user_id=winner_id, amount=payout, kind="payout")
    round_scope = scope_from_row(row)
    if round_scope.is_rub:
        await _credit_house(
            conn,
            amount=rake,
            entry_key=f"jackpot-rake-{row['round_id']}",
            reason=f"Jackpot rake {row['round_id']}",
        )
    await conn.execute(
        "UPDATE casino_jackpot_rounds SET status = 'settled', settled_at = now() WHERE id = $1",
        round_pk,
    )
    settled = await conn.fetchrow("SELECT * FROM casino_jackpot_rounds WHERE id = $1", round_pk)
    view = await _named_public(conn, settled, cfg, None)
    await _enqueue_telegram_results(
        conn,
        round_id=str(row["round_id"]),
        event_type="jackpot_settled",
        text=settle_chat_html(view, refund=False),
        bets=bets,
    )
    publish({"type": "settled", "round_id": str(row["round_id"]), "winner_id": winner_id})
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    if round_scope.is_rub:
        await maybe_grant_reached_level_bonuses(conn, *[int(uid) for uid in wager])
    await _lock_open(conn, round_scope)


async def maybe_close_due(conn) -> None:
    cfg = await load_jackpot_config(conn)
    row = await conn.fetchrow(
        """
        SELECT id, status, closes_at
        FROM casino_jackpot_rounds
        WHERE status = 'open' AND closes_at IS NOT NULL AND closes_at <= now()
        ORDER BY id
        LIMIT 1
        """
    )
    if not row:
        return
    await _lock_and_settle(conn, round_pk=int(row["id"]), cfg=cfg)
