"""FocusBet tournaments: several parallel tournaments, flexible entry, chip wallet, live bracket.

Money model
-----------
* Entry fee / rebuy fee (RUB) leaves the real unified balance and feeds the dynamic prize pool.
* Inside a tournament players bet **chips**, never RUB. Every casino game routes its
  stake/payout through :func:`tournament_wallet_of` while the player has a tournament wallet
  selected, so no game engine had to learn a second currency.
* Prizes are credited as plain RUB on the withdrawable balance when the clock runs out.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from fastapi import HTTPException

from casino_finance import money

logger = logging.getLogger("casino_tournaments")

WATCH_PATH = "/casino/tournaments"
MAX_PRIZE_PLACES = 20
DEFAULT_ALLOWED_GAMES: tuple[str, ...] = (
    "pvp_dice",
    "baccara",
    "blackjack",
    "roulette",
    "fixed_room",
    "jackpot",
)
ENTRY_MODES = ("free", "promo", "paid", "promo_or_paid")
PRIZE_MODES = ("fixed", "dynamic")
LIVE_STATUSES = ("registration", "active")

_subscribers: set[asyncio.Queue] = set()
_closer_started = False


# --------------------------------------------------------------------------- helpers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


def chips(value: Decimal | int | float | str | None) -> Decimal:
    return money(value or 0)


def tournament_order_ref(kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{kind}:{key}".encode("utf-8")).hexdigest()[:32]
    return f"trn-{kind}-{digest}"[:64]


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


def _json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return list(raw) if isinstance(raw, (list, tuple)) else []


def parse_prize_places(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, row in enumerate(_json_list(raw)):
        if not isinstance(row, Mapping):
            continue
        out.append(
            {
                "place": index + 1,
                "prize_rub": float(money(row.get("prize_rub") or 0)),
                "share_pct": float(money(row.get("share_pct") or 0)),
            }
        )
    return out


def normalize_prize_places(raw: Any) -> list[dict[str, Any]]:
    rows = _json_list(raw)
    if not rows:
        raise ValueError("Нужно хотя бы одно призовое место")
    if len(rows) > MAX_PRIZE_PLACES:
        raise ValueError(f"Максимум {MAX_PRIZE_PLACES} призовых мест")
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError("Каждое место — объект с суммой приза")
        prize = money(row.get("prize_rub") or 0)
        share = money(row.get("share_pct") or 0)
        if prize < 0 or share < 0:
            raise ValueError("Призы и доли не могут быть отрицательными")
        out.append({"place": index + 1, "prize_rub": float(prize), "share_pct": float(share)})
    return out


def normalize_allowed_games(raw: Any) -> list[str]:
    items = [str(item).strip() for item in _json_list(raw) if str(item).strip()]
    allowed = [item for item in items if item in DEFAULT_ALLOWED_GAMES]
    return allowed or list(DEFAULT_ALLOWED_GAMES)


def prize_pool_for(row: Mapping[str, Any], *, paid_rub_total: Decimal) -> Decimal:
    """Fixed mode = sum of places. Dynamic = guarantee + share of collected entries."""
    places = parse_prize_places(row.get("prize_places"))
    if str(row.get("prize_mode") or "fixed") == "fixed":
        return money(sum((money(item["prize_rub"]) for item in places), Decimal("0")))
    share = money(row.get("entry_pool_share_pct") or 0) / Decimal("100")
    return money(money(row.get("guaranteed_pool_rub") or 0) + money(paid_rub_total) * share)


def prize_for_rank(
    row: Mapping[str, Any], rank: int, *, pool_rub: Decimal
) -> Decimal:
    places = parse_prize_places(row.get("prize_places"))
    place = next((item for item in places if int(item["place"]) == int(rank)), None)
    if not place:
        return Decimal("0.00")
    if str(row.get("prize_mode") or "fixed") == "fixed":
        return money(place["prize_rub"])
    shares = money(sum((money(item["share_pct"]) for item in places), Decimal("0")))
    if shares <= 0:
        return Decimal("0.00")
    return money(money(pool_rub) * money(place["share_pct"]) / shares)


def entry_fee_for(row: Mapping[str, Any], *, via: str) -> Decimal:
    mode = str(row.get("entry_mode") or "promo")
    if mode == "paid" or (mode == "promo_or_paid" and via == "paid"):
        return money(row.get("entry_fee_rub") or 0)
    return Decimal("0.00")


def status_label(status: str) -> str:
    return {
        "draft": "Черновик",
        "registration": "Регистрация открыта",
        "active": "Идёт сейчас",
        "finished": "Завершён",
        "cancelled": "Отменён",
    }.get(str(status), str(status))


# --------------------------------------------------------------------------- chip wallet


async def tournament_wallet_of(conn, user_id: int) -> int | None:
    """Tournament the player currently bets from, or ``None`` for the real RUB wallet."""
    if not await _tables_ready(conn):
        return None
    row = await conn.fetchrow(
        """
        /* trn:wallet */
        SELECT s.active_tournament_id AS tid
        FROM casino_tournament_user_state s
        JOIN casino_tournaments t ON t.id = s.active_tournament_id
        JOIN casino_tournament_entries e
          ON e.tournament_id = t.id AND e.user_id = s.user_id
        WHERE s.user_id = $1
          AND t.status = 'active'
          AND NOT e.blocked
        """,
        int(user_id),
    )
    return int(row["tid"]) if row and row["tid"] is not None else None


async def _tables_ready(conn) -> bool:
    """True once the tournament migration is applied.

    A probe failure (e.g. a stubbed connection in unit tests) means "no tournaments",
    never a broken round. Deliberately not cached: the probe is a cheap catalog lookup
    and a process-wide cache would leak between independent connections.
    """
    try:
        return bool(await conn.fetchval("SELECT to_regclass('public.casino_tournaments')"))
    except Exception:  # noqa: BLE001 - absence of the feature must not break a game
        return False


async def reserve_tournament_chips(
    conn, *, tournament_id: int, user_id: int, order_ref: str, amount_rub: Decimal
) -> None:
    """Debit chips into a named hold. Mirrors ``reserve_unified_funds`` semantics."""
    amount = chips(amount_rub)
    existing = await conn.fetchrow(
        "/* trn:hold-get */ SELECT amount_chips, status FROM casino_tournament_holds WHERE order_ref = $1",
        order_ref,
    )
    if existing:
        if chips(existing["amount_chips"]) != amount:
            raise RuntimeError("Tournament hold conflicts")
        return
    updated = await conn.fetchrow(
        """
        /* trn:hold-debit */
        UPDATE casino_tournament_entries
        SET chips_balance = chips_balance - $3, updated_at = now()
        WHERE tournament_id = $1 AND user_id = $2 AND NOT blocked AND chips_balance >= $3
        RETURNING chips_balance
        """,
        int(tournament_id),
        int(user_id),
        amount,
    )
    if not updated:
        raise ValueError("insufficient tournament chips")
    await conn.execute(
        """
        /* trn:hold-insert */
        INSERT INTO casino_tournament_holds (order_ref, tournament_id, user_id, amount_chips, status)
        VALUES ($1, $2, $3, $4, 'hold')
        """,
        order_ref,
        int(tournament_id),
        int(user_id),
        amount,
    )


async def confirm_tournament_hold(conn, *, order_ref: str, note: str) -> bool:
    row = await conn.fetchrow(
        """
        /* trn:hold-spend */
        UPDATE casino_tournament_holds
        SET status = 'spend', note = $2, updated_at = now()
        WHERE order_ref = $1 AND status = 'hold'
        RETURNING tournament_id, user_id, amount_chips
        """,
        order_ref,
        note[:300],
    )
    if not row:
        return False
    await conn.execute(
        """
        /* trn:round-count */
        UPDATE casino_tournament_entries
        SET rounds_played = rounds_played + 1,
            total_wagered_chips = total_wagered_chips + $3,
            updated_at = now()
        WHERE tournament_id = $1 AND user_id = $2
        """,
        int(row["tournament_id"]),
        int(row["user_id"]),
        chips(row["amount_chips"]),
    )
    publish({"type": "bracket", "tournament_id": int(row["tournament_id"])})
    return True


async def release_tournament_hold(conn, *, order_ref: str, note: str) -> bool:
    row = await conn.fetchrow(
        """
        /* trn:hold-release */
        UPDATE casino_tournament_holds
        SET status = 'released', note = $2, updated_at = now()
        WHERE order_ref = $1 AND status = 'hold'
        RETURNING tournament_id, user_id, amount_chips
        """,
        order_ref,
        note[:300],
    )
    if not row:
        return False
    await conn.execute(
        """
        /* trn:hold-refund */
        UPDATE casino_tournament_entries
        SET chips_balance = chips_balance + $3, updated_at = now()
        WHERE tournament_id = $1 AND user_id = $2
        """,
        int(row["tournament_id"]),
        int(row["user_id"]),
        chips(row["amount_chips"]),
    )
    publish({"type": "bracket", "tournament_id": int(row["tournament_id"])})
    return True


async def credit_tournament_chips(
    conn, *, tournament_id: int, user_id: int, order_id: str, amount_rub: Decimal, game_id: str = ""
) -> None:
    """Idempotent chip payout, keyed exactly like the RUB ledger order id."""
    amount = chips(amount_rub)
    if amount <= 0:
        return
    inserted = await conn.fetchrow(
        """
        /* trn:payout */
        INSERT INTO casino_tournament_payouts (order_id, tournament_id, user_id, amount_chips, game_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING order_id
        """,
        order_id[:64],
        int(tournament_id),
        int(user_id),
        amount,
        str(game_id or "")[:128],
    )
    if not inserted:
        return
    await conn.execute(
        """
        /* trn:payout-credit */
        UPDATE casino_tournament_entries
        SET chips_balance = chips_balance + $3,
            wins_count = wins_count + 1,
            updated_at = now()
        WHERE tournament_id = $1 AND user_id = $2
        """,
        int(tournament_id),
        int(user_id),
        amount,
    )
    publish({"type": "bracket", "tournament_id": int(tournament_id)})


async def has_open_tournament_holds(conn, user_id: int) -> bool:
    if not await _tables_ready(conn):
        return False
    return bool(
        await conn.fetchval(
            "/* trn:open-holds */ SELECT 1 FROM casino_tournament_holds WHERE user_id = $1 AND status = 'hold' LIMIT 1",
            int(user_id),
        )
    )


async def set_active_wallet(conn, *, user_id: int, tournament_id: int | None) -> int | None:
    """Switch the player's betting wallet. Blocked while chips sit in a live hold.

    Clearing the tournament pointer always lands on the real RUB wallet, so the legacy
    bot endpoint cannot leave a player parked on bonus chips.
    """
    from casino_wallet import KIND_RUB, KIND_TOURNAMENT, has_open_bonus_holds, store_wallet_kind

    if not await _tables_ready(conn):
        raise HTTPException(status_code=409, detail="Турниры недоступны")
    if await has_open_tournament_holds(conn, user_id):
        raise HTTPException(status_code=409, detail="Сначала завершите текущий раунд")
    if await has_open_bonus_holds(conn, user_id):
        raise HTTPException(status_code=409, detail="Сначала завершите текущий раунд")
    if tournament_id is not None:
        entry = await conn.fetchrow(
            """
            SELECT e.id FROM casino_tournament_entries e
            JOIN casino_tournaments t ON t.id = e.tournament_id
            WHERE e.tournament_id = $1 AND e.user_id = $2 AND NOT e.blocked
              AND t.status IN ('registration', 'active')
            """,
            int(tournament_id),
            int(user_id),
        )
        if not entry:
            raise HTTPException(status_code=404, detail="Вы не участвуете в этом турнире")
    await conn.execute(
        """
        INSERT INTO casino_tournament_user_state (user_id, active_tournament_id, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO UPDATE SET active_tournament_id = EXCLUDED.active_tournament_id, updated_at = now()
        """,
        int(user_id),
        int(tournament_id) if tournament_id is not None else None,
    )
    await store_wallet_kind(
        conn,
        user_id=user_id,
        kind=KIND_TOURNAMENT if tournament_id is not None else KIND_RUB,
    )
    return int(tournament_id) if tournament_id is not None else None


# --------------------------------------------------------------------------- entry


async def _lock_tournament(conn, tournament_id: int) -> dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT * FROM casino_tournaments WHERE id = $1 FOR UPDATE",
        int(tournament_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Турнир не найден")
    return dict(row)


async def _paid_rub_total(conn, tournament_id: int) -> Decimal:
    value = await conn.fetchval(
        "SELECT COALESCE(SUM(paid_rub_total), 0) FROM casino_tournament_entries WHERE tournament_id = $1",
        int(tournament_id),
    )
    return money(value or 0)


async def _access_ready(conn) -> bool:
    try:
        return bool(await conn.fetchval("SELECT to_regclass('public.casino_tournament_access')"))
    except Exception:  # noqa: BLE001 - absence of the allowlist means "no personal grants"
        return False


async def has_personal_access(conn, *, tournament_id: int, user_id: int) -> bool:
    """Owner-granted seat: the player skips the exchange-history gate."""
    if not await _access_ready(conn):
        return False
    return bool(
        await conn.fetchval(
            """
            /* trn:access-check */
            SELECT 1 FROM casino_tournament_access
            WHERE tournament_id = $1 AND user_id = $2 LIMIT 1
            """,
            int(tournament_id),
            int(user_id),
        )
    )


async def grant_access(
    conn, *, tournament_id: int, user_id: int, note: str = "", granted_by: int | None = None
) -> None:
    if not await _access_ready(conn):
        raise HTTPException(
            status_code=409,
            detail="Таблица доступов не создана — примените миграцию add_casino_tournament_access.sql",
        )
    if not await conn.fetchval("SELECT 1 FROM casino_tournaments WHERE id = $1", int(tournament_id)):
        raise HTTPException(status_code=404, detail="Турнир не найден")
    await conn.execute(
        """
        INSERT INTO casino_tournament_access (tournament_id, user_id, note, granted_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (tournament_id, user_id) DO UPDATE SET note = EXCLUDED.note
        """,
        int(tournament_id),
        int(user_id),
        str(note or "")[:300],
        int(granted_by) if granted_by else None,
    )
    publish({"type": "access", "tournament_id": int(tournament_id)})


async def revoke_access(conn, *, tournament_id: int, user_id: int) -> None:
    if not await _access_ready(conn):
        return
    await conn.execute(
        "DELETE FROM casino_tournament_access WHERE tournament_id = $1 AND user_id = $2",
        int(tournament_id),
        int(user_id),
    )
    publish({"type": "access", "tournament_id": int(tournament_id)})


async def list_access(conn, tournament_id: int) -> list[dict[str, Any]]:
    if not await _access_ready(conn):
        return []
    rows = await conn.fetch(
        """
        SELECT a.user_id, a.note, a.created_at, bu.username,
               (e.id IS NOT NULL) AS joined
        FROM casino_tournament_access a
        LEFT JOIN bot_users bu ON bu.user_id = a.user_id
        LEFT JOIN casino_tournament_entries e
               ON e.tournament_id = a.tournament_id AND e.user_id = a.user_id
        WHERE a.tournament_id = $1
        ORDER BY a.created_at DESC
        """,
        int(tournament_id),
    )
    return [
        {
            "user_id": int(row["user_id"]),
            "username": row["username"],
            "note": str(row["note"] or ""),
            "joined": bool(row["joined"]),
            "created_at": _iso(row["created_at"]),
        }
        for row in rows
    ]


async def _assert_entry_requirements(conn, row: Mapping[str, Any], user_id: int) -> None:
    if not bool(row.get("require_exchange_history")):
        return
    if await has_personal_access(conn, tournament_id=int(row["id"]), user_id=int(user_id)):
        return
    paid = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(fiat_amount), 0)::numeric AS volume, COUNT(*)::int AS deals
        FROM orders
        WHERE user_id = $1 AND status IN ('PAID', 'COMPLETED')
        """,
        int(user_id),
    )
    deals = int(paid["deals"] or 0) if paid else 0
    volume = money(paid["volume"] or 0) if paid else Decimal("0")
    if deals <= 0:
        raise HTTPException(
            status_code=403,
            detail="Турнир доступен клиентам с историей обменов FocusPay",
        )
    required_deals = int(row.get("min_exchange_count") or 0)
    if required_deals > 0 and deals < required_deals:
        raise HTTPException(
            status_code=403,
            detail=f"Нужно минимум {required_deals} обменов в FocusPay",
        )
    required = money(row.get("min_exchange_volume_rub") or 0)
    if required > 0 and volume < required:
        raise HTTPException(
            status_code=403,
            detail=f"Нужен оборот обменов от {required:.0f} ₽",
        )


async def _record_cash_event(
    conn,
    *,
    tournament_id: int,
    user_id: int,
    kind: str,
    amount: Decimal,
    order_ref: str,
) -> None:
    """Book a RUB cash movement for owner PnL (fees in, prizes/refunds out)."""
    if money(amount) <= 0:
        return
    try:
        await conn.execute(
            """
            INSERT INTO casino_tournament_cash_events (
                tournament_id, user_id, kind, amount_rub, order_ref
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (order_ref) DO NOTHING
            """,
            int(tournament_id),
            int(user_id),
            kind,
            money(amount),
            order_ref[:64],
        )
    except Exception:  # noqa: BLE001 - PnL bookkeeping must never block play
        logger.exception("tournament cash event failed kind=%s ref=%s", kind, order_ref)


async def _charge_rub(conn, *, user_id: int, amount: Decimal, order_ref: str, note: str) -> None:
    if amount <= 0:
        return
    # Взнос и ребай — всегда реальные рубли, даже когда уже выбран кошелёк фишек.
    from casino_finance import confirm_real_hold as confirm_unified_hold, reserve_real_funds

    try:
        await reserve_real_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=amount)
        await confirm_unified_hold(
            conn, user_id=user_id, order_ref=order_ref, amount_rub=amount, note=note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Не удалось списать взнос") from exc


async def join_tournament(
    conn, *, user_id: int, tournament_id: int, promo_code: str | None = None
) -> dict[str, Any]:
    if not await _tables_ready(conn):
        raise HTTPException(status_code=409, detail="Турниры недоступны")
    row = await _lock_tournament(conn, tournament_id)
    status = str(row["status"])
    if status not in LIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Регистрация в этот турнир закрыта")
    existing = await conn.fetchrow(
        "SELECT * FROM casino_tournament_entries WHERE tournament_id = $1 AND user_id = $2",
        int(tournament_id),
        int(user_id),
    )
    if existing:
        raise HTTPException(status_code=409, detail="Вы уже участвуете в этом турнире")
    seats = int(
        await conn.fetchval(
            "SELECT COUNT(*)::int FROM casino_tournament_entries WHERE tournament_id = $1",
            int(tournament_id),
        )
        or 0
    )
    if seats >= int(row["max_participants"]):
        raise HTTPException(status_code=409, detail="Мест в турнире больше нет")

    mode = str(row["entry_mode"])
    code = (promo_code or "").strip().upper()
    wanted = (row.get("promo_code") or "").strip().upper()
    via = "free"
    if mode == "promo":
        if not wanted or code != wanted:
            raise HTTPException(status_code=400, detail="Неверный промокод турнира")
        via = "promo"
    elif mode == "paid":
        via = "paid"
    elif mode == "promo_or_paid":
        via = "promo" if (wanted and code == wanted) else "paid"

    await _assert_entry_requirements(conn, row, user_id)
    fee = entry_fee_for(row, via=via)
    entry_ref = tournament_order_ref("entry", f"{tournament_id}:{user_id}")
    await _charge_rub(
        conn,
        user_id=user_id,
        amount=fee,
        order_ref=entry_ref,
        note=f"Турнир {row['code']}: вход",
    )
    await _record_cash_event(
        conn,
        tournament_id=int(tournament_id),
        user_id=int(user_id),
        kind="entry",
        amount=fee,
        order_ref=entry_ref,
    )
    starting = chips(row["starting_chips"])
    await conn.execute(
        """
        INSERT INTO casino_tournament_entries (
            tournament_id, user_id, chips_balance, starting_chips_granted,
            paid_rub_total, entered_via, promo_code_used
        ) VALUES ($1, $2, $3, $3, $4, $5, $6)
        """,
        int(tournament_id),
        int(user_id),
        starting,
        fee,
        via,
        code or None,
    )
    await set_active_wallet(conn, user_id=user_id, tournament_id=int(tournament_id))
    publish({"type": "join", "tournament_id": int(tournament_id)})
    return await snapshot(conn, tournament_id=int(tournament_id), viewer_id=int(user_id))


async def rebuy_tournament(conn, *, user_id: int, tournament_id: int) -> dict[str, Any]:
    if not await _tables_ready(conn):
        raise HTTPException(status_code=409, detail="Турниры недоступны")
    row = await _lock_tournament(conn, tournament_id)
    if str(row["status"]) != "active":
        raise HTTPException(status_code=409, detail="Докупка доступна только во время турнира")
    if not bool(row["rebuy_enabled"]):
        raise HTTPException(status_code=409, detail="В этом турнире докупка выключена")
    entry = await conn.fetchrow(
        "SELECT * FROM casino_tournament_entries WHERE tournament_id = $1 AND user_id = $2 FOR UPDATE",
        int(tournament_id),
        int(user_id),
    )
    if not entry or bool(entry["blocked"]):
        raise HTTPException(status_code=404, detail="Вы не участвуете в этом турнире")
    limit = int(row["max_rebuys_per_user"])
    if limit and int(entry["rebuys_count"]) >= limit:
        raise HTTPException(status_code=409, detail=f"Лимит докупок — {limit}")
    threshold = chips(row["rebuy_max_balance_chips"])
    if threshold <= 0:
        threshold = chips(row["min_bet_chips"])
    if chips(entry["chips_balance"]) > threshold:
        raise HTTPException(
            status_code=409,
            detail=f"Докупка доступна при балансе не больше {threshold:.0f} фишек",
        )
    fee = money(row["rebuy_fee_rub"])
    nth = int(entry["rebuys_count"]) + 1
    rebuy_ref = tournament_order_ref("rebuy", f"{tournament_id}:{user_id}:{nth}")
    await _charge_rub(
        conn,
        user_id=user_id,
        amount=fee,
        order_ref=rebuy_ref,
        note=f"Турнир {row['code']}: докупка #{nth}",
    )
    await _record_cash_event(
        conn,
        tournament_id=int(tournament_id),
        user_id=int(user_id),
        kind="rebuy",
        amount=fee,
        order_ref=rebuy_ref,
    )
    await conn.execute(
        """
        UPDATE casino_tournament_entries
        SET chips_balance = chips_balance + $3,
            rebuys_count = rebuys_count + 1,
            paid_rub_total = paid_rub_total + $4,
            updated_at = now()
        WHERE tournament_id = $1 AND user_id = $2
        """,
        int(tournament_id),
        int(user_id),
        chips(row["rebuy_chips"]),
        fee,
    )
    publish({"type": "rebuy", "tournament_id": int(tournament_id)})
    return await snapshot(conn, tournament_id=int(tournament_id), viewer_id=int(user_id))


async def join_by_promo_code(conn, *, user_id: int, promo_code: str) -> dict[str, Any] | None:
    """Hook for the cashier promo field: a tournament code enrolls instead of crediting RUB."""
    if not await _tables_ready(conn):
        return None
    code = (promo_code or "").strip().upper()
    if not code:
        return None
    row = await conn.fetchrow(
        """
        SELECT id FROM casino_tournaments
        WHERE UPPER(COALESCE(promo_code, '')) = $1
          AND status IN ('registration', 'active')
          AND entry_mode IN ('promo', 'promo_or_paid')
        ORDER BY id DESC LIMIT 1
        """,
        code,
    )
    if not row:
        return None
    return await join_tournament(
        conn, user_id=user_id, tournament_id=int(row["id"]), promo_code=code
    )


# --------------------------------------------------------------------------- bracket


def _rank_entries(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        [row for row in rows if not bool(row.get("blocked"))],
        key=lambda row: (
            -chips(row["chips_balance"]),
            -int(row["rounds_played"] or 0),
            row["joined_at"],
        ),
    )


async def snapshot(conn, *, tournament_id: int | None, viewer_id: int | None) -> dict[str, Any]:
    if not await _tables_ready(conn):
        return empty_snapshot(viewer_id)
    if tournament_id:
        row = await conn.fetchrow("SELECT * FROM casino_tournaments WHERE id = $1", int(tournament_id))
    else:
        row = await conn.fetchrow(
            """
            SELECT * FROM casino_tournaments
            ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'registration' THEN 1
                                 WHEN 'finished' THEN 2 ELSE 3 END,
                     starts_at DESC, id DESC
            LIMIT 1
            """
        )
    if not row:
        return empty_snapshot(viewer_id)
    camp = dict(row)
    tid = int(camp["id"])
    entries = [
        dict(item)
        for item in await conn.fetch(
            "SELECT * FROM casino_tournament_entries WHERE tournament_id = $1",
            tid,
        )
    ]
    paid_total = money(sum((money(item["paid_rub_total"]) for item in entries), Decimal("0")))
    pool = prize_pool_for(camp, paid_rub_total=paid_total)
    ranked = _rank_entries(entries)

    from casino_chat import actor_chip, public_actors

    ids = [int(item["user_id"]) for item in ranked]
    if viewer_id:
        ids.append(int(viewer_id))
    actors = await public_actors(conn, ids) if ids else {}

    players: list[dict[str, Any]] = []
    me: dict[str, Any] | None = None
    for index, item in enumerate(ranked):
        uid = int(item["user_id"])
        actor = actor_chip(actors, uid)
        rank = int(item["final_rank"]) if item.get("final_rank") else index + 1
        projected = (
            money(item["prize_rub"])
            if item.get("prize_rub") is not None
            else prize_for_rank(camp, rank, pool_rub=pool)
        )
        player = {
            "rank": rank,
            "user_id": uid,
            "display_name": actor["display_name"],
            "initial": actor["initial"],
            "avatar_url": actor.get("avatar_url"),
            "chips_balance": float(chips(item["chips_balance"])),
            "rounds_played": int(item["rounds_played"] or 0),
            "wins_count": int(item["wins_count"] or 0),
            "rebuys_count": int(item["rebuys_count"] or 0),
            "projected_prize_rub": float(projected),
            "prize_paid": bool(item.get("prize_credited_at")),
        }
        players.append(player)
        if viewer_id and uid == int(viewer_id):
            me = player

    places = parse_prize_places(camp.get("prize_places"))
    prize_places = [
        {
            "place": int(item["place"]),
            "prize_rub": float(prize_for_rank(camp, int(item["place"]), pool_rub=pool)),
            "leader": next((p for p in players if p["rank"] == int(item["place"])), None),
        }
        for item in places
    ]
    now = _now()
    ends_at = camp.get("ends_at")
    seconds_left = None
    if isinstance(ends_at, datetime):
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        seconds_left = max(0, int((ends_at - now).total_seconds()))
    return {
        "tournament_id": tid,
        "code": str(camp["code"]),
        "title": str(camp["title"]),
        "subtitle": str(camp.get("subtitle") or ""),
        "status": str(camp["status"]),
        "status_label": status_label(str(camp["status"])),
        "starts_at": _iso(camp.get("starts_at")),
        "ends_at": _iso(camp.get("ends_at")),
        "seconds_left": seconds_left,
        "duration_minutes": int(camp["duration_minutes"]),
        "entry_mode": str(camp["entry_mode"]),
        "entry_fee_rub": float(money(camp["entry_fee_rub"])),
        "has_promo": bool((camp.get("promo_code") or "").strip()),
        "starting_chips": float(chips(camp["starting_chips"])),
        "min_bet_chips": float(chips(camp["min_bet_chips"])),
        "max_bet_chips": float(chips(camp["max_bet_chips"])),
        "rebuy_enabled": bool(camp["rebuy_enabled"]),
        "rebuy_fee_rub": float(money(camp["rebuy_fee_rub"])),
        "rebuy_chips": float(chips(camp["rebuy_chips"])),
        "max_rebuys_per_user": int(camp["max_rebuys_per_user"]),
        "prize_mode": str(camp["prize_mode"]),
        "prize_pool_rub": float(pool),
        "prize_places": prize_places,
        "require_exchange_history": bool(camp["require_exchange_history"]),
        "my_access_granted": bool(
            viewer_id
            and await has_personal_access(conn, tournament_id=tid, user_id=int(viewer_id))
        ),
        "min_exchange_count": int(camp["min_exchange_count"] or 0),
        "min_rounds_for_prize": int(camp["min_rounds_for_prize"]),
        "max_participants": int(camp["max_participants"]),
        "max_bots_per_table": int(camp["max_bots_per_table"]),
        "allowed_games": normalize_allowed_games(camp.get("allowed_games")),
        "player_count": len(players),
        "players": players,
        "me": me,
        "my_user_id": int(viewer_id) if viewer_id else None,
        "watch_path": WATCH_PATH,
    }


def empty_snapshot(viewer_id: int | None) -> dict[str, Any]:
    return {
        "tournament_id": None,
        "code": "",
        "title": "Турниры FocusBet",
        "subtitle": "",
        "status": "none",
        "status_label": "Турниров нет",
        "starts_at": None,
        "ends_at": None,
        "seconds_left": None,
        "duration_minutes": 60,
        "entry_mode": "free",
        "entry_fee_rub": 0.0,
        "has_promo": False,
        "starting_chips": 0.0,
        "min_bet_chips": 0.0,
        "max_bet_chips": 0.0,
        "rebuy_enabled": False,
        "rebuy_fee_rub": 0.0,
        "rebuy_chips": 0.0,
        "max_rebuys_per_user": 0,
        "prize_mode": "fixed",
        "prize_pool_rub": 0.0,
        "prize_places": [],
        "require_exchange_history": True,
        "my_access_granted": False,
        "min_exchange_count": 1,
        "min_rounds_for_prize": 1,
        "max_participants": 0,
        "max_bots_per_table": 1,
        "allowed_games": list(DEFAULT_ALLOWED_GAMES),
        "player_count": 0,
        "players": [],
        "me": None,
        "my_user_id": int(viewer_id) if viewer_id else None,
        "watch_path": WATCH_PATH,
    }


async def list_tournaments(conn, *, viewer_id: int | None, limit: int = 24) -> list[dict[str, Any]]:
    if not await _tables_ready(conn):
        return []
    rows = await conn.fetch(
        """
        SELECT t.*,
               (SELECT COUNT(*)::int FROM casino_tournament_entries e WHERE e.tournament_id = t.id) AS player_count,
               (SELECT COALESCE(SUM(e.paid_rub_total), 0) FROM casino_tournament_entries e WHERE e.tournament_id = t.id) AS paid_total,
               (SELECT e.chips_balance FROM casino_tournament_entries e
                 WHERE e.tournament_id = t.id AND e.user_id = $1) AS my_chips
        FROM casino_tournaments t
        WHERE t.status <> 'draft'
        ORDER BY CASE t.status WHEN 'active' THEN 0 WHEN 'registration' THEN 1
                               WHEN 'finished' THEN 2 ELSE 3 END,
                 t.starts_at DESC, t.id DESC
        LIMIT $2
        """,
        int(viewer_id or 0),
        max(1, min(int(limit), 50)),
    )
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        pool = prize_pool_for(row, paid_rub_total=money(row.get("paid_total") or 0))
        out.append(
            {
                "tournament_id": int(row["id"]),
                "code": str(row["code"]),
                "title": str(row["title"]),
                "subtitle": str(row.get("subtitle") or ""),
                "status": str(row["status"]),
                "status_label": status_label(str(row["status"])),
                "starts_at": _iso(row.get("starts_at")),
                "ends_at": _iso(row.get("ends_at")),
                "entry_mode": str(row["entry_mode"]),
                "entry_fee_rub": float(money(row["entry_fee_rub"])),
                "starting_chips": float(chips(row["starting_chips"])),
                "prize_pool_rub": float(pool),
                "player_count": int(row.get("player_count") or 0),
                "max_participants": int(row["max_participants"]),
                "joined": row.get("my_chips") is not None,
                "my_chips": float(chips(row["my_chips"])) if row.get("my_chips") is not None else None,
            }
        )
    return out


async def my_wallets(conn, user_id: int) -> list[dict[str, Any]]:
    """Wallet switcher payload for the casino header."""
    if not await _tables_ready(conn):
        return []
    rows = await conn.fetch(
        """
        SELECT t.id, t.title, t.code, t.status, t.ends_at, e.chips_balance
        FROM casino_tournament_entries e
        JOIN casino_tournaments t ON t.id = e.tournament_id
        WHERE e.user_id = $1 AND NOT e.blocked AND t.status IN ('registration', 'active')
        ORDER BY t.status, t.starts_at DESC
        """,
        int(user_id),
    )
    active = await tournament_wallet_of(conn, user_id)
    return [
        {
            "tournament_id": int(row["id"]),
            "title": str(row["title"]),
            "code": str(row["code"]),
            "status": str(row["status"]),
            "ends_at": _iso(row["ends_at"]),
            "chips_balance": float(chips(row["chips_balance"])),
            "selected": active is not None and int(row["id"]) == active,
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- lifecycle


async def _credit_prize(
    conn, *, tournament_id: int, code: str, user_id: int, rank: int, amount: Decimal
) -> None:
    if amount <= 0:
        return
    order_id = tournament_order_ref("prize", f"{tournament_id}:{rank}")
    note = f"Турнир {code}: {rank} место"
    await conn.execute(
        """
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'adjustment', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        """,
        int(user_id),
        money(amount),
        order_id,
        note,
    )
    credited = await conn.fetchrow(
        """
        UPDATE casino_tournament_entries
        SET prize_order_id = $3, prize_credited_at = now(), updated_at = now()
        WHERE tournament_id = $1 AND user_id = $2 AND prize_credited_at IS NULL
        RETURNING user_id
        """,
        int(tournament_id),
        int(user_id),
        order_id,
    )
    if credited:
        await _record_cash_event(
            conn,
            tournament_id=int(tournament_id),
            user_id=int(user_id),
            kind="prize",
            amount=amount,
            order_ref=order_id,
        )
    try:
        from casino_inbox import push_item

        await push_item(
            conn,
            recipient_id=int(user_id),
            event_type="tournament_prize",
            game_id=f"trn-{tournament_id}",
            href=WATCH_PATH,
            title=f"{rank} место в турнире",
            body=f"{money(amount)} ₽ уже на балансе",
            payload={"tournament_id": int(tournament_id), "rank": int(rank)},
        )
    except Exception:  # noqa: BLE001 - inbox must never block the payout
        logger.exception("tournament inbox notice")


async def finish_tournament(conn, tournament_id: int) -> dict[str, Any]:
    row = await _lock_tournament(conn, tournament_id)
    if str(row["status"]) in {"finished", "cancelled"}:
        return await snapshot(conn, tournament_id=int(tournament_id), viewer_id=None)
    entries = [
        dict(item)
        for item in await conn.fetch(
            "SELECT * FROM casino_tournament_entries WHERE tournament_id = $1 FOR UPDATE",
            int(tournament_id),
        )
    ]
    pool = prize_pool_for(
        row, paid_rub_total=money(sum((money(e["paid_rub_total"]) for e in entries), Decimal("0")))
    )
    min_rounds = int(row["min_rounds_for_prize"])
    ranked = [e for e in _rank_entries(entries) if int(e["rounds_played"] or 0) >= min_rounds]
    places = parse_prize_places(row.get("prize_places"))
    for index, entry in enumerate(ranked[: len(places)]):
        rank = index + 1
        amount = prize_for_rank(row, rank, pool_rub=pool)
        await conn.execute(
            """
            UPDATE casino_tournament_entries
            SET final_rank = $3, prize_rub = $4, updated_at = now()
            WHERE tournament_id = $1 AND user_id = $2
            """,
            int(tournament_id),
            int(entry["user_id"]),
            rank,
            money(amount),
        )
        await _credit_prize(
            conn,
            tournament_id=int(tournament_id),
            code=str(row["code"]),
            user_id=int(entry["user_id"]),
            rank=rank,
            amount=amount,
        )
    await conn.execute(
        "UPDATE casino_tournaments SET status = 'finished', settled_at = now(), updated_at = now() WHERE id = $1",
        int(tournament_id),
    )
    await conn.execute(
        "UPDATE casino_tournament_user_state SET active_tournament_id = NULL, updated_at = now() WHERE active_tournament_id = $1",
        int(tournament_id),
    )
    publish({"type": "finished", "tournament_id": int(tournament_id)})
    return await snapshot(conn, tournament_id=int(tournament_id), viewer_id=None)


async def cancel_tournament(conn, tournament_id: int) -> dict[str, Any]:
    """Cancel and refund every paid entry/rebuy to the real balance."""
    row = await _lock_tournament(conn, tournament_id)
    if str(row["status"]) in {"finished", "cancelled"}:
        return await snapshot(conn, tournament_id=int(tournament_id), viewer_id=None)
    entries = await conn.fetch(
        "SELECT user_id, paid_rub_total FROM casino_tournament_entries WHERE tournament_id = $1 FOR UPDATE",
        int(tournament_id),
    )
    for entry in entries:
        refund = money(entry["paid_rub_total"])
        if refund <= 0:
            continue
        refund_ref = tournament_order_ref("refund", f"{tournament_id}:{int(entry['user_id'])}")
        inserted = await conn.fetchrow(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'adjustment', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            RETURNING order_id
            """,
            int(entry["user_id"]),
            refund,
            refund_ref,
            f"Турнир {row['code']}: возврат взноса",
        )
        if inserted:
            await _record_cash_event(
                conn,
                tournament_id=int(tournament_id),
                user_id=int(entry["user_id"]),
                kind="refund",
                amount=refund,
                order_ref=refund_ref,
            )
    await conn.execute(
        "UPDATE casino_tournaments SET status = 'cancelled', settled_at = now(), updated_at = now() WHERE id = $1",
        int(tournament_id),
    )
    await conn.execute(
        "UPDATE casino_tournament_user_state SET active_tournament_id = NULL, updated_at = now() WHERE active_tournament_id = $1",
        int(tournament_id),
    )
    publish({"type": "cancelled", "tournament_id": int(tournament_id)})
    return await snapshot(conn, tournament_id=int(tournament_id), viewer_id=None)


async def maybe_advance(conn) -> None:
    """Start scheduled tournaments and settle the ones whose clock ran out."""
    if not await _tables_ready(conn):
        return
    started = await conn.fetch(
        """
        UPDATE casino_tournaments
        SET status = 'active', updated_at = now()
        WHERE status = 'registration' AND starts_at <= now() AND ends_at > now()
        RETURNING id
        """
    )
    for row in started:
        publish({"type": "started", "tournament_id": int(row["id"])})
    due = await conn.fetch(
        "SELECT id FROM casino_tournaments WHERE status IN ('registration', 'active') AND ends_at <= now() ORDER BY id"
    )
    for row in due:
        await finish_tournament(conn, int(row["id"]))


def ensure_closer() -> None:
    global _closer_started
    if _closer_started:
        return
    _closer_started = True
    asyncio.create_task(_closer_loop())


async def _closer_loop() -> None:
    from db import get_pool

    while True:
        await asyncio.sleep(2)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await maybe_advance(conn)
        except Exception:  # noqa: BLE001
            logger.exception("tournament closer")


# --------------------------------------------------------------------------- admin


_ADMIN_FIELDS = (
    "title",
    "subtitle",
    "starts_at",
    "ends_at",
    "duration_minutes",
    "entry_mode",
    "promo_code",
    "entry_fee_rub",
    "starting_chips",
    "min_bet_chips",
    "max_bet_chips",
    "rebuy_enabled",
    "rebuy_fee_rub",
    "rebuy_chips",
    "max_rebuys_per_user",
    "rebuy_max_balance_chips",
    "prize_mode",
    "guaranteed_pool_rub",
    "entry_pool_share_pct",
    "require_exchange_history",
    "min_exchange_count",
    "min_exchange_volume_rub",
    "min_rounds_for_prize",
    "max_participants",
    "min_participants",
)


def _normalize_window(starts_at: Any, ends_at: Any, duration_minutes: Any) -> tuple[datetime, datetime, int]:
    start = starts_at if isinstance(starts_at, datetime) else _now()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    minutes = int(duration_minutes or 60)
    if minutes < 5 or minutes > 43200:
        raise ValueError("Длительность турнира — от 5 минут до 30 дней")
    end = ends_at if isinstance(ends_at, datetime) else start + timedelta(minutes=minutes)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        end = start + timedelta(minutes=minutes)
    return start, end, minutes


async def create_tournament(conn, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not await _tables_ready(conn):
        raise ValueError("Таблицы турниров не созданы — примените миграцию")
    mode = str(payload.get("entry_mode") or "free")
    if mode not in ENTRY_MODES:
        raise ValueError("Неизвестный тип входа")
    prize_mode = str(payload.get("prize_mode") or "fixed")
    if prize_mode not in PRIZE_MODES:
        raise ValueError("Неизвестный режим призового фонда")
    promo = (payload.get("promo_code") or "").strip().upper() or None
    if mode in {"promo", "promo_or_paid"} and not promo:
        raise ValueError("Для входа по промокоду нужен сам промокод")
    places = normalize_prize_places(payload.get("prize_places"))
    start, end, minutes = _normalize_window(
        payload.get("starts_at"), payload.get("ends_at"), payload.get("duration_minutes")
    )
    code = (payload.get("code") or "").strip().upper() or f"TRN{int(_now().timestamp())}"
    row = await conn.fetchrow(
        """
        INSERT INTO casino_tournaments (
            code, title, subtitle, status, starts_at, ends_at, duration_minutes,
            entry_mode, promo_code, entry_fee_rub, starting_chips, min_bet_chips, max_bet_chips,
            rebuy_enabled, rebuy_fee_rub, rebuy_chips, max_rebuys_per_user, rebuy_max_balance_chips,
            prize_mode, guaranteed_pool_rub, entry_pool_share_pct, prize_places,
            require_exchange_history, min_exchange_count, min_exchange_volume_rub, min_rounds_for_prize,
            max_participants, min_participants, allowed_games
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, $9, $10, $11, $12, $13,
            $14, $15, $16, $17, $18,
            $19, $20, $21, $22::jsonb,
            $23, $24, $25, $26,
            $27, $28, $29::jsonb
        )
        RETURNING *
        """,
        code,
        (payload.get("title") or "Турнир FocusBet").strip()[:140],
        (payload.get("subtitle") or "").strip()[:280],
        str(payload.get("status") or "registration"),
        start,
        end,
        minutes,
        mode,
        promo,
        money(payload.get("entry_fee_rub") or 0),
        chips(payload.get("starting_chips") or 1000),
        chips(payload.get("min_bet_chips") or 10),
        chips(payload.get("max_bet_chips") or 1000),
        bool(payload.get("rebuy_enabled")),
        money(payload.get("rebuy_fee_rub") or 0),
        chips(payload.get("rebuy_chips") or payload.get("starting_chips") or 1000),
        int(payload.get("max_rebuys_per_user") or 0),
        chips(payload.get("rebuy_max_balance_chips") or 0),
        prize_mode,
        money(payload.get("guaranteed_pool_rub") or 0),
        money(payload.get("entry_pool_share_pct") or 100),
        json.dumps(places),
        bool(payload.get("require_exchange_history", True)),
        int(payload.get("min_exchange_count") or 0),
        money(payload.get("min_exchange_volume_rub") or 0),
        int(payload.get("min_rounds_for_prize") or 1),
        int(payload.get("max_participants") or 500),
        int(payload.get("min_participants") or 2),
        json.dumps(normalize_allowed_games(payload.get("allowed_games"))),
    )
    ensure_closer()
    publish({"type": "created", "tournament_id": int(row["id"])})
    return dict(row)


async def update_tournament(conn, tournament_id: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    row = await _lock_tournament(conn, tournament_id)
    if str(row["status"]) in {"finished", "cancelled"}:
        raise ValueError("Завершённый турнир изменить нельзя")
    sets: list[str] = []
    args: list[Any] = [int(tournament_id)]
    for field in _ADMIN_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if field in {"entry_fee_rub", "rebuy_fee_rub", "guaranteed_pool_rub", "entry_pool_share_pct", "min_exchange_volume_rub"}:
            value = money(value or 0)
        elif field in {"starting_chips", "min_bet_chips", "max_bet_chips", "rebuy_chips", "rebuy_max_balance_chips"}:
            value = chips(value or 0)
        elif field in {"duration_minutes", "max_rebuys_per_user", "min_rounds_for_prize", "max_participants", "min_participants", "min_exchange_count"}:
            value = int(value or 0)
        elif field in {"rebuy_enabled", "require_exchange_history"}:
            value = bool(value)
        elif field == "promo_code":
            value = (value or "").strip().upper() or None
        args.append(value)
        sets.append(f"{field} = ${len(args)}")
    if "prize_places" in payload:
        args.append(json.dumps(normalize_prize_places(payload["prize_places"])))
        sets.append(f"prize_places = ${len(args)}::jsonb")
    if "allowed_games" in payload:
        args.append(json.dumps(normalize_allowed_games(payload["allowed_games"])))
        sets.append(f"allowed_games = ${len(args)}::jsonb")
    if not sets:
        return row
    updated = await conn.fetchrow(
        f"UPDATE casino_tournaments SET {', '.join(sets)}, updated_at = now() WHERE id = $1 RETURNING *",
        *args,
    )
    publish({"type": "updated", "tournament_id": int(tournament_id)})
    return dict(updated)


async def set_status(conn, tournament_id: int, status: str) -> dict[str, Any]:
    if status == "finished":
        return await finish_tournament(conn, tournament_id)
    if status == "cancelled":
        return await cancel_tournament(conn, tournament_id)
    if status not in {"draft", "registration", "active"}:
        raise ValueError("Неизвестный статус турнира")
    row = await _lock_tournament(conn, tournament_id)
    if str(row["status"]) in {"finished", "cancelled"}:
        raise ValueError("Турнир уже завершён")
    extra = ""
    args: list[Any] = [int(tournament_id), status]
    if status == "active":
        # Launching now re-anchors the clock so the configured duration is honoured.
        extra = ", starts_at = now(), ends_at = now() + make_interval(mins => duration_minutes)"
    await conn.execute(
        f"UPDATE casino_tournaments SET status = $2{extra}, updated_at = now() WHERE id = $1",
        *args,
    )
    ensure_closer()
    publish({"type": "status", "tournament_id": int(tournament_id), "status": status})
    return await snapshot(conn, tournament_id=int(tournament_id), viewer_id=None)


async def block_participant(conn, tournament_id: int, user_id: int, blocked: bool) -> None:
    await conn.execute(
        """
        UPDATE casino_tournament_entries
        SET blocked = $3, updated_at = now()
        WHERE tournament_id = $1 AND user_id = $2
        """,
        int(tournament_id),
        int(user_id),
        bool(blocked),
    )
    publish({"type": "bracket", "tournament_id": int(tournament_id)})


async def admin_list(conn, limit: int = 60) -> list[dict[str, Any]]:
    if not await _tables_ready(conn):
        return []
    rows = await conn.fetch(
        """
        SELECT t.*,
               (SELECT COUNT(*)::int FROM casino_tournament_entries e WHERE e.tournament_id = t.id) AS player_count,
               (SELECT COALESCE(SUM(e.paid_rub_total), 0) FROM casino_tournament_entries e WHERE e.tournament_id = t.id) AS paid_total,
               (SELECT COALESCE(SUM(e.prize_rub), 0) FROM casino_tournament_entries e WHERE e.tournament_id = t.id) AS prizes_paid
        FROM casino_tournaments t
        ORDER BY t.starts_at DESC, t.id DESC
        LIMIT $1
        """,
        max(1, min(int(limit), 200)),
    )
    out = []
    for raw in rows:
        row = dict(raw)
        row["prize_places"] = parse_prize_places(row.get("prize_places"))
        row["allowed_games"] = normalize_allowed_games(row.get("allowed_games"))
        row["prize_pool_rub"] = float(
            prize_pool_for(raw, paid_rub_total=money(row.get("paid_total") or 0))
        )
        row["status_label"] = status_label(str(row["status"]))
        for key in ("starts_at", "ends_at", "settled_at", "created_at", "updated_at"):
            row[key] = _iso(row.get(key))
        for key in (
            "entry_fee_rub",
            "starting_chips",
            "min_bet_chips",
            "max_bet_chips",
            "rebuy_fee_rub",
            "rebuy_chips",
            "rebuy_max_balance_chips",
            "guaranteed_pool_rub",
            "entry_pool_share_pct",
            "min_exchange_volume_rub",
            "paid_total",
            "prizes_paid",
        ):
            row[key] = float(money(row.get(key) or 0))
        out.append(row)
    return out


async def admin_participants(conn, tournament_id: int) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT e.*, bu.username
        FROM casino_tournament_entries e
        LEFT JOIN bot_users bu ON bu.user_id = e.user_id
        WHERE e.tournament_id = $1
        ORDER BY e.blocked, e.chips_balance DESC, e.rounds_played DESC, e.joined_at
        """,
        int(tournament_id),
    )
    return [
        {
            "user_id": int(row["user_id"]),
            "username": row.get("username"),
            "chips_balance": float(chips(row["chips_balance"])),
            "rounds_played": int(row["rounds_played"] or 0),
            "rebuys_count": int(row["rebuys_count"] or 0),
            "paid_rub_total": float(money(row["paid_rub_total"])),
            "entered_via": str(row["entered_via"]),
            "blocked": bool(row["blocked"]),
            "final_rank": int(row["final_rank"]) if row.get("final_rank") else None,
            "prize_rub": float(money(row["prize_rub"])) if row.get("prize_rub") is not None else None,
            "joined_at": _iso(row["joined_at"]),
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- pool wrappers


async def snapshot_for_user(viewer_id: int | None, tournament_id: int | None = None) -> dict[str, Any]:
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        async with conn.transaction():
            ensure_closer()
            try:
                await maybe_advance(conn)
            except Exception:  # noqa: BLE001
                logger.exception("tournament snapshot advance")
            return await snapshot(conn, tournament_id=tournament_id, viewer_id=viewer_id)


async def list_for_user(viewer_id: int | None) -> list[dict[str, Any]]:
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        return await list_tournaments(conn, viewer_id=viewer_id)
