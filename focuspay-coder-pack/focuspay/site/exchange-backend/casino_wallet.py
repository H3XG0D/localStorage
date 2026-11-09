"""Wallet scopes for FocusBet.

A *scope* answers one question: what does this player stake, and who may sit at the
same table. Three kinds exist:

* ``rub``       — real money from the unified balance (cashback + referral + partner).
* ``bonus``     — bonus chips, free to grant, never withdrawable.
* ``tournament``— chips inside one tournament; every tournament is its own scope, so two
  tournaments running at the same time never share a table.

Every table/round carries the same pair (``wallet_kind``, ``tournament_id``), and
:func:`assert_same_scope` refuses a seat when the player's scope differs. That is what
makes "chips against money" impossible instead of merely unlikely.

Chips reuse the RUB numeric scale (1 chip = 1.00) so game engines keep one amount type.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from fastapi import HTTPException

from casino_finance import money

logger = logging.getLogger("casino_wallet")

KIND_RUB = "rub"
KIND_BONUS = "bonus"
KIND_TOURNAMENT = "tournament"
WALLET_KINDS = (KIND_RUB, KIND_BONUS, KIND_TOURNAMENT)

DEFAULT_BONUS_GRANT_CHIPS = Decimal("1000.00")
DEFAULT_BONUS_COOLDOWN_HOURS = 24


# --------------------------------------------------------------------------- scope


@dataclass(frozen=True)
class WalletScope:
    """The pair stamped on a player and on every table they may join."""

    kind: str = KIND_RUB
    tournament_id: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in WALLET_KINDS:
            raise ValueError(f"unknown wallet kind: {self.kind}")
        if self.kind == KIND_TOURNAMENT and not self.tournament_id:
            raise ValueError("tournament scope needs a tournament id")

    @property
    def is_rub(self) -> bool:
        return self.kind == KIND_RUB

    @property
    def is_chips(self) -> bool:
        return self.kind in {KIND_BONUS, KIND_TOURNAMENT}

    def key(self) -> str:
        return f"trn:{self.tournament_id}" if self.kind == KIND_TOURNAMENT else self.kind

    def unit(self) -> str:
        return "rub" if self.is_rub else "chips"

    def title(self) -> str:
        if self.kind == KIND_BONUS:
            return "Бонусные фишки"
        if self.kind == KIND_TOURNAMENT:
            return "Турнирные фишки"
        return "Основной баланс"

    def db_tuple(self) -> tuple[str, int | None]:
        return self.kind, int(self.tournament_id) if self.tournament_id else None

    def public_dict(self) -> dict[str, Any]:
        return {
            "wallet_kind": self.kind,
            "wallet_scope": self.key(),
            "tournament_id": int(self.tournament_id) if self.tournament_id else None,
            "unit": self.unit(),
        }


RUB_SCOPE = WalletScope(KIND_RUB)
BONUS_SCOPE = WalletScope(KIND_BONUS)


def tournament_scope(tournament_id: int) -> WalletScope:
    return WalletScope(KIND_TOURNAMENT, int(tournament_id))


def scope_from_row(row: Mapping[str, Any] | None) -> WalletScope:
    """Read a scope off a table/round row, defaulting to real money.

    Rows written before the migration have no columns at all, so a missing key means
    "real money" — the behaviour those rows were created with.
    """
    if not row:
        return RUB_SCOPE
    try:
        kind = str(row["wallet_kind"] or KIND_RUB)
    except (KeyError, TypeError):
        kind = KIND_RUB
    try:
        raw_tid = row["tournament_id"]
    except (KeyError, TypeError):
        raw_tid = None
    if kind not in WALLET_KINDS:
        kind = KIND_RUB
    if kind == KIND_TOURNAMENT:
        if not raw_tid:
            return RUB_SCOPE
        return tournament_scope(int(raw_tid))
    return WalletScope(kind)


def parse_scope(kind: str | None, tournament_id: int | None = None) -> WalletScope:
    """Validate a client-supplied scope, raising 400 on nonsense."""
    value = str(kind or KIND_RUB).strip().lower()
    if value in {"", "real", "money"}:
        value = KIND_RUB
    if value == "demo":
        value = KIND_BONUS
    if value not in WALLET_KINDS:
        raise HTTPException(status_code=400, detail="Неизвестный кошелёк")
    if value == KIND_TOURNAMENT:
        if not tournament_id:
            raise HTTPException(status_code=400, detail="Не указан турнир")
        return tournament_scope(int(tournament_id))
    return WalletScope(value)


def scope_mismatch_detail(table_scope: WalletScope, player_scope: WalletScope) -> str:
    if table_scope.is_rub:
        return "Этот стол для реальных ставок — переключите кошелёк на основной баланс"
    if table_scope.kind == KIND_BONUS:
        return "Этот стол для бонусных фишек — переключите кошелёк на бонусный"
    if player_scope.kind == KIND_TOURNAMENT:
        return "Этот стол другого турнира"
    return "Этот стол турнирный — войдите в турнир и выберите его кошелёк"


def assert_same_scope(table_scope: WalletScope, player_scope: WalletScope) -> None:
    """Refuse to mix stake currencies at one table."""
    if table_scope == player_scope:
        return
    raise HTTPException(status_code=409, detail=scope_mismatch_detail(table_scope, player_scope))


# --------------------------------------------------------------------------- probes


async def _has_table(conn, name: str) -> bool:
    try:
        return bool(await conn.fetchval(f"SELECT to_regclass('public.{name}')"))
    except Exception:  # noqa: BLE001 - a missing feature must never break a round
        return False


async def _bonus_ready(conn) -> bool:
    return await _has_table(conn, "casino_bonus_wallets")


async def _state_has_wallet_kind(conn) -> bool:
    try:
        return bool(
            await conn.fetchval(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'casino_tournament_user_state' AND column_name = 'wallet_kind'
                """
            )
        )
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- active scope


async def active_scope(conn, user_id: int) -> WalletScope:
    """The scope the player stakes from right now.

    Falls back to real money whenever the selected wallet became unusable (tournament
    finished, entry blocked, bonus wallet disabled), so a stale pointer can never park a
    player in a dead scope.
    """
    from casino_tournaments import tournament_wallet_of

    tournament_id = await tournament_wallet_of(conn, user_id)
    if tournament_id is not None:
        return tournament_scope(tournament_id)
    if not await _state_has_wallet_kind(conn):
        return RUB_SCOPE
    try:
        kind = await conn.fetchval(
            """
            /* wallet:active */
            SELECT wallet_kind FROM casino_tournament_user_state WHERE user_id = $1
            """,
            int(user_id),
        )
    except Exception:  # noqa: BLE001
        return RUB_SCOPE
    if str(kind or KIND_RUB) != KIND_BONUS:
        return RUB_SCOPE
    if not await bonus_enabled(conn):
        return RUB_SCOPE
    return BONUS_SCOPE


async def viewer_scope(conn, user_id: int | None) -> WalletScope:
    """Scope used to filter lobbies. Guests always look at the real-money pool."""
    if not user_id:
        return RUB_SCOPE
    return await active_scope(conn, int(user_id))


async def set_active_scope(conn, *, user_id: int, scope: WalletScope) -> WalletScope:
    """Switch the player's wallet. Blocked while a stake sits in a live hold."""
    from casino_tournaments import has_open_tournament_holds, set_active_wallet

    if scope.kind == KIND_TOURNAMENT:
        await set_active_wallet(conn, user_id=user_id, tournament_id=scope.tournament_id)
        return scope

    if await has_open_tournament_holds(conn, user_id):
        raise HTTPException(status_code=409, detail="Сначала завершите текущий раунд")
    if await has_open_bonus_holds(conn, user_id):
        raise HTTPException(status_code=409, detail="Сначала завершите текущий раунд")
    if scope.kind == KIND_BONUS and not await bonus_enabled(conn):
        raise HTTPException(status_code=409, detail="Бонусные фишки отключены")

    # Clearing the tournament pointer is what makes the chip wallet inactive.
    try:
        await set_active_wallet(conn, user_id=user_id, tournament_id=None)
    except HTTPException as exc:
        if exc.status_code != 409 or "Турниры недоступны" not in str(exc.detail):
            raise
    await store_wallet_kind(conn, user_id=user_id, kind=scope.kind)
    if scope.kind == KIND_BONUS:
        await ensure_bonus_wallet(conn, user_id)
    return scope


async def store_wallet_kind(conn, *, user_id: int, kind: str) -> None:
    """Persist the scope kind next to the tournament pointer. No-op before migration."""
    if not await _state_has_wallet_kind(conn):
        return
    await conn.execute(
        """
        /* wallet:store-kind */
        INSERT INTO casino_tournament_user_state (user_id, wallet_kind, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO UPDATE SET wallet_kind = EXCLUDED.wallet_kind, updated_at = now()
        """,
        int(user_id),
        kind,
    )


# --------------------------------------------------------------------------- settings


async def _setting(conn, key: str) -> Any:
    try:
        return await conn.fetchval("SELECT value FROM casino_settings WHERE key = $1", key)
    except Exception:  # noqa: BLE001
        return None


def _unwrap(raw: Any, field: str, default: Any) -> Any:
    import json

    if raw is None:
        return default
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return default
    if isinstance(raw, Mapping):
        return raw.get(field, default)
    return raw


async def bonus_enabled(conn) -> bool:
    if not await _bonus_ready(conn):
        return False
    return bool(_unwrap(await _setting(conn, "bonus_wallet_enabled"), "enabled", True))


async def bonus_grant_chips(conn) -> Decimal:
    raw = _unwrap(await _setting(conn, "bonus_wallet_grant_chips"), "amount", None)
    if raw is None:
        return DEFAULT_BONUS_GRANT_CHIPS
    try:
        value = money(raw)
    except Exception:  # noqa: BLE001
        return DEFAULT_BONUS_GRANT_CHIPS
    return value if value > 0 else DEFAULT_BONUS_GRANT_CHIPS


async def bonus_grant_cooldown_hours(conn) -> int:
    raw = _unwrap(await _setting(conn, "bonus_wallet_grant_cooldown_hours"), "value", None)
    try:
        value = int(raw) if raw is not None else DEFAULT_BONUS_COOLDOWN_HOURS
    except (TypeError, ValueError):
        value = DEFAULT_BONUS_COOLDOWN_HOURS
    return max(1, value)


# --------------------------------------------------------------------------- bonus chips


def bonus_order_ref(kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{kind}:{key}".encode("utf-8")).hexdigest()[:32]
    return f"bns-{kind}-{digest}"[:64]


async def ensure_bonus_wallet(conn, user_id: int) -> dict[str, Any]:
    if not await _bonus_ready(conn):
        raise HTTPException(status_code=409, detail="Бонусные фишки недоступны")
    await conn.execute(
        """
        /* wallet:bonus-ensure */
        INSERT INTO casino_bonus_wallets (user_id) VALUES ($1)
        ON CONFLICT (user_id) DO NOTHING
        """,
        int(user_id),
    )
    row = await conn.fetchrow(
        "/* wallet:bonus-get */ SELECT * FROM casino_bonus_wallets WHERE user_id = $1",
        int(user_id),
    )
    return dict(row) if row else {"user_id": int(user_id), "chips_balance": Decimal("0.00")}


async def bonus_balance(conn, user_id: int) -> Decimal:
    if not await _bonus_ready(conn):
        return Decimal("0.00")
    value = await conn.fetchval(
        "/* wallet:bonus-balance */ SELECT chips_balance FROM casino_bonus_wallets WHERE user_id = $1",
        int(user_id),
    )
    return money(value or 0)


async def has_open_bonus_holds(conn, user_id: int) -> bool:
    if not await _bonus_ready(conn):
        return False
    return bool(
        await conn.fetchval(
            """
            /* wallet:bonus-open-holds */
            SELECT 1 FROM casino_bonus_holds WHERE user_id = $1 AND status = 'hold' LIMIT 1
            """,
            int(user_id),
        )
    )


async def grant_bonus_chips(
    conn,
    *,
    user_id: int,
    amount_chips: Decimal,
    order_id: str,
    note: str = "",
) -> Decimal:
    """Idempotent chip grant. Returns the balance after the grant."""
    amount = money(amount_chips)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")
    await ensure_bonus_wallet(conn, user_id)
    inserted = await conn.fetchrow(
        """
        /* wallet:bonus-grant-ledger */
        INSERT INTO casino_bonus_ledger (user_id, kind, amount_chips, order_id, note)
        VALUES ($1, 'grant', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING id
        """,
        int(user_id),
        amount,
        order_id[:80],
        str(note or "")[:300],
    )
    if not inserted:
        return await bonus_balance(conn, user_id)
    row = await conn.fetchrow(
        """
        /* wallet:bonus-grant */
        UPDATE casino_bonus_wallets
        SET chips_balance = chips_balance + $2,
            granted_total = granted_total + $2,
            last_grant_at = now(),
            updated_at = now()
        WHERE user_id = $1
        RETURNING chips_balance
        """,
        int(user_id),
        amount,
    )
    return money(row["chips_balance"]) if row else amount


async def self_refill_bonus_chips(conn, *, user_id: int) -> dict[str, Any]:
    """Top the wallet back up to the configured nominal when it is empty."""
    if not await bonus_enabled(conn):
        raise HTTPException(status_code=409, detail="Бонусные фишки отключены")
    wallet = await ensure_bonus_wallet(conn, user_id)
    if bool(wallet.get("blocked")):
        raise HTTPException(status_code=403, detail="Бонусный кошелёк заблокирован")
    if money(wallet.get("chips_balance") or 0) > 0:
        raise HTTPException(status_code=409, detail="Фишки ещё есть — пополнение не нужно")
    if await has_open_bonus_holds(conn, user_id):
        raise HTTPException(status_code=409, detail="Сначала завершите текущий раунд")
    cooldown = await bonus_grant_cooldown_hours(conn)
    last = wallet.get("last_grant_at")
    if last is not None:
        fresh = await conn.fetchval(
            """
            /* wallet:bonus-cooldown */
            SELECT last_grant_at > now() - ($2 || ' hours')::interval
            FROM casino_bonus_wallets WHERE user_id = $1
            """,
            int(user_id),
            str(cooldown),
        )
        if bool(fresh):
            raise HTTPException(
                status_code=429,
                detail=f"Следующее пополнение бонусных фишек через {cooldown} ч",
            )
    amount = await bonus_grant_chips(conn)
    order_id = bonus_order_ref("refill", f"{user_id}:{await _refill_seq(conn, user_id)}")
    balance = await grant_bonus_chips(
        conn,
        user_id=user_id,
        amount_chips=amount,
        order_id=order_id,
        note="Самостоятельное пополнение бонусного кошелька",
    )
    return {"chips_balance": float(balance), "granted_chips": float(amount)}


async def _refill_seq(conn, user_id: int) -> int:
    value = await conn.fetchval(
        """
        /* wallet:bonus-refill-seq */
        SELECT COUNT(*) FROM casino_bonus_ledger WHERE user_id = $1 AND kind = 'grant'
        """,
        int(user_id),
    )
    return int(value or 0) + 1


async def reserve_bonus_chips(conn, *, user_id: int, order_ref: str, amount_rub: Decimal) -> None:
    """Debit bonus chips into a named hold. Mirrors ``reserve_unified_funds``."""
    amount = money(amount_rub)
    existing = await conn.fetchrow(
        "/* wallet:bonus-hold-get */ SELECT amount_chips, status FROM casino_bonus_holds WHERE order_ref = $1",
        order_ref,
    )
    if existing:
        if money(existing["amount_chips"]) != amount:
            raise RuntimeError("Bonus hold conflicts")
        return
    updated = await conn.fetchrow(
        """
        /* wallet:bonus-hold-debit */
        UPDATE casino_bonus_wallets
        SET chips_balance = chips_balance - $2, updated_at = now()
        WHERE user_id = $1 AND NOT blocked AND chips_balance >= $2
        RETURNING chips_balance
        """,
        int(user_id),
        amount,
    )
    if not updated:
        raise ValueError("insufficient bonus chips")
    await conn.execute(
        """
        /* wallet:bonus-hold-insert */
        INSERT INTO casino_bonus_holds (order_ref, user_id, amount_chips, status)
        VALUES ($1, $2, $3, 'hold')
        """,
        order_ref,
        int(user_id),
        amount,
    )


async def confirm_bonus_hold(conn, *, order_ref: str, note: str) -> bool:
    row = await conn.fetchrow(
        """
        /* wallet:bonus-hold-spend */
        UPDATE casino_bonus_holds
        SET status = 'spend', note = $2, updated_at = now()
        WHERE order_ref = $1 AND status = 'hold'
        RETURNING user_id, amount_chips
        """,
        order_ref,
        note[:300],
    )
    if not row:
        return False
    await conn.execute(
        """
        /* wallet:bonus-round-count */
        UPDATE casino_bonus_wallets
        SET rounds_played = rounds_played + 1,
            total_wagered_chips = total_wagered_chips + $2,
            updated_at = now()
        WHERE user_id = $1
        """,
        int(row["user_id"]),
        money(row["amount_chips"]),
    )
    await conn.execute(
        """
        /* wallet:bonus-bet-ledger */
        INSERT INTO casino_bonus_ledger (user_id, kind, amount_chips, order_id, note)
        VALUES ($1, 'bet', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        """,
        int(row["user_id"]),
        money(row["amount_chips"]),
        f"bet:{order_ref}"[:80],
        note[:300],
    )
    return True


async def release_bonus_hold(conn, *, order_ref: str, note: str) -> bool:
    row = await conn.fetchrow(
        """
        /* wallet:bonus-hold-release */
        UPDATE casino_bonus_holds
        SET status = 'released', note = $2, updated_at = now()
        WHERE order_ref = $1 AND status = 'hold'
        RETURNING user_id, amount_chips
        """,
        order_ref,
        note[:300],
    )
    if not row:
        return False
    await conn.execute(
        """
        /* wallet:bonus-hold-refund */
        UPDATE casino_bonus_wallets
        SET chips_balance = chips_balance + $2, updated_at = now()
        WHERE user_id = $1
        """,
        int(row["user_id"]),
        money(row["amount_chips"]),
    )
    return True


async def credit_bonus_chips(
    conn, *, user_id: int, order_id: str, amount_rub: Decimal, game_id: str = ""
) -> None:
    """Idempotent chip payout, keyed exactly like the RUB ledger order id."""
    amount = money(amount_rub)
    if amount <= 0:
        return
    inserted = await conn.fetchrow(
        """
        /* wallet:bonus-win-ledger */
        INSERT INTO casino_bonus_ledger (user_id, kind, amount_chips, order_id, game_id)
        VALUES ($1, 'win', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING id
        """,
        int(user_id),
        amount,
        order_id[:80],
        str(game_id or "")[:128],
    )
    if not inserted:
        return
    await ensure_bonus_wallet(conn, user_id)
    await conn.execute(
        """
        /* wallet:bonus-win */
        UPDATE casino_bonus_wallets
        SET chips_balance = chips_balance + $2,
            wins_count = wins_count + 1,
            updated_at = now()
        WHERE user_id = $1
        """,
        int(user_id),
        amount,
    )


# --------------------------------------------------------------------------- wallet list


async def my_wallets(conn, user_id: int) -> list[dict[str, Any]]:
    """Switcher payload: real money, bonus chips, then one row per joined tournament."""
    from casino_tournaments import my_wallets as tournament_wallets
    from user_unified_balance import unified_available

    scope = await active_scope(conn, user_id)
    out: list[dict[str, Any]] = []
    try:
        available = money(await unified_available(conn, int(user_id)))
    except Exception:  # noqa: BLE001 - the switcher must render even if stats fail
        logger.exception("wallet list: unified balance")
        available = Decimal("0.00")
    out.append(
        {
            "kind": KIND_RUB,
            "scope": RUB_SCOPE.key(),
            "title": RUB_SCOPE.title(),
            "unit": "rub",
            "available_rub": float(available),
            "selected": scope.is_rub,
        }
    )
    if await bonus_enabled(conn):
        out.append(
            {
                "kind": KIND_BONUS,
                "scope": BONUS_SCOPE.key(),
                "title": BONUS_SCOPE.title(),
                "unit": "chips",
                "chips_balance": float(await bonus_balance(conn, user_id)),
                "grant_chips": float(await bonus_grant_chips(conn)),
                "selected": scope.kind == KIND_BONUS,
            }
        )
    for item in await tournament_wallets(conn, user_id):
        tid = int(item.get("tournament_id") or item.get("id") or 0)
        if not tid:
            continue
        out.append(
            {
                "kind": KIND_TOURNAMENT,
                "scope": tournament_scope(tid).key(),
                "tournament_id": tid,
                "title": str(item.get("title") or "Турнир"),
                "status": item.get("status"),
                "ends_at": item.get("ends_at"),
                "unit": "chips",
                "chips_balance": float(money(item.get("chips_balance") or 0)),
                "selected": scope.kind == KIND_TOURNAMENT and scope.tournament_id == tid,
            }
        )
    return out


async def scope_balance(conn, user_id: int, scope: WalletScope | None = None) -> Decimal:
    """Stakeable amount in the player's own unit."""
    scope = scope or await active_scope(conn, user_id)
    if scope.kind == KIND_BONUS:
        return await bonus_balance(conn, user_id)
    if scope.kind == KIND_TOURNAMENT:
        value = await conn.fetchval(
            """
            /* wallet:trn-balance */
            SELECT chips_balance FROM casino_tournament_entries
            WHERE tournament_id = $1 AND user_id = $2
            """,
            int(scope.tournament_id),
            int(user_id),
        )
        return money(value or 0)
    from user_unified_balance import unified_available

    return money(await unified_available(conn, int(user_id)))


# --------------------------------------------------------------------- scope columns

SCOPED_TABLES = (
    "casino_v2_tables",
    "casino_games",
    "casino_fixed_room_rounds",
    "casino_jackpot_rounds",
    "casino_roulette_rounds",
)


async def table_has_scope_columns(conn, table: str) -> bool:
    """True once ``add_casino_wallet_scopes.sql`` stamped ``table``.

    Everything below degrades to real money while the migration is not applied, so the
    same code runs on an old schema without a single failing query.
    """
    try:
        return bool(
            await conn.fetchval(
                """
                /* wallet:scope-columns */
                SELECT 1 FROM information_schema.columns
                WHERE table_name = $1 AND column_name = 'wallet_kind'
                """,
                table,
            )
        )
    except Exception:  # noqa: BLE001 - a missing probe must never break a round
        return False


async def scope_insert_sql(
    conn, table: str, scope: WalletScope, *, next_index: int
) -> tuple[str, str, list[Any]]:
    """Columns/placeholders/values to append to an INSERT so the row carries the scope.

    Returns empty parts before the migration; a chip scope then has nowhere to be
    stamped, and letting it through would create a table everybody can sit at.
    """
    if not await table_has_scope_columns(conn, table):
        if scope.is_rub:
            return "", "", []
        raise HTTPException(status_code=409, detail="Фишковые столы пока недоступны")
    kind, tournament_id = scope.db_tuple()
    return (
        ", wallet_kind, tournament_id",
        f", ${next_index}::varchar, ${next_index + 1}::bigint",
        [kind, tournament_id],
    )


def scope_sql_filter(scope: WalletScope, alias: str = "") -> str:
    """AND-fragment keeping a lobby query inside one scope.

    Values are inlined on purpose: the kind comes from a closed set and the tournament
    id is cast through ``int``, so there is nothing a client can inject.
    """
    prefix = f"{alias}." if alias else ""
    kind, tournament_id = scope.db_tuple()
    if kind == KIND_TOURNAMENT:
        return (
            f" AND COALESCE({prefix}wallet_kind, 'rub') = 'tournament'"
            f" AND {prefix}tournament_id = {int(tournament_id)}"
        )
    return (
        f" AND COALESCE({prefix}wallet_kind, 'rub') = '{kind}'"
        f" AND {prefix}tournament_id IS NULL"
    )


async def scope_or_mine_filter(
    conn, table: str, scope: WalletScope, *, mine_sql: str, alias: str = ""
) -> str:
    """Своя область ИЛИ стол, где игрок уже сидит.

    Без второй половины смена кошелька спрятала бы от игрока его же живой стол, и
    он не смог бы ни доиграть, ни выйти.
    """
    base = await scope_filter_for(conn, table, scope, alias)
    if not base:
        return ""
    condition = base[len(" AND ") :] if base.startswith(" AND ") else base
    return f" AND (({condition}) OR {mine_sql})"


async def scope_filter_for(conn, table: str, scope: WalletScope, alias: str = "") -> str:
    """``scope_sql_filter`` when the columns exist, otherwise nothing to filter on."""
    if not await table_has_scope_columns(conn, table):
        return ""
    return scope_sql_filter(scope, alias)


async def row_scope_of(conn, table: str, key_column: str, key_value: Any) -> WalletScope:
    """Read a stored row's scope without assuming the caller selected the columns."""
    if not await table_has_scope_columns(conn, table):
        return RUB_SCOPE
    row = await conn.fetchrow(
        f"/* wallet:row-scope */ SELECT wallet_kind, tournament_id FROM {table} WHERE {key_column} = $1",
        key_value,
    )
    return scope_from_row(row)


async def assert_player_may_sit(conn, row: Mapping[str, Any] | None, user_id: int) -> WalletScope:
    """409 unless the player stakes the same thing the table does. Returns the scope."""
    table_scope = scope_from_row(row)
    assert_same_scope(table_scope, await active_scope(conn, int(user_id)))
    return table_scope


async def assert_real_money_only(conn, user_id: int) -> None:
    """Игры против банкролла казино живут только в рублях: банк не платит фишками."""
    scope = await active_scope(conn, int(user_id))
    if scope.is_rub:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            "В режиме «{title}» игры против казино недоступны — выберите стол с живыми"
            " игроками или вернитесь на основной баланс."
        ).format(title=scope.title()),
    )


async def assert_may_sit_at(
    conn, table: str, key_column: str, key_value: Any, user_id: int
) -> WalletScope:
    """``assert_player_may_sit`` for callers whose SELECT omits the scope columns."""
    table_scope = await row_scope_of(conn, table, key_column, key_value)
    assert_same_scope(table_scope, await active_scope(conn, int(user_id)))
    return table_scope
