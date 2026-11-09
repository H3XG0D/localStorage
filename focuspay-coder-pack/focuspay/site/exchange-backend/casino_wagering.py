"""Wagering-lock: депозит зачисляется по номиналу, но заперт к выводу,
пока казино не получит требуемый плюс комиссией с этого игрока.

Инвариант безопасности: лок влияет ТОЛЬКО на доступную к выводу сумму
(withdrawal-хелперы). Он НЕ трогает unified_available/holds, поэтому играть
заблокированными средствами по-прежнему можно — иначе депозит невозможно отыграть.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Literal, Mapping

from casino_finance import money, whole_percent

logger = logging.getLogger("casino_wagering")

DEFAULT_WAGERING_PERCENT = Decimal("21")
DEFAULT_COMMISSION_RATE_WAGERING_ACTIVE = Decimal("15")
DEFAULT_COMMISSION_RATE_WAGERING_COMPLETE = Decimal("5")
HUNDRED = Decimal("100")


def _percent_from_settings(
    values: Mapping[str, object], key: str, default: Decimal
) -> Decimal:
    raw_container = values.get(key)
    if not isinstance(raw_container, Mapping):
        return default
    raw = raw_container.get("percent")
    if isinstance(raw, bool) or raw is None:
        return default
    try:
        return whole_percent(raw)
    except ValueError:
        return default


def house_take_from_stake(stake: Decimal | int | float | str, commission_rate: Decimal) -> Decimal:
    """Комиссия казино с одной ставки игрока при данной ставке комиссии."""
    return money(money(stake) * whole_percent(commission_rate) / HUNDRED)


def stake_for_house_take(house_take: Decimal | int | float | str, commission_rate: Decimal) -> Decimal:
    """Какой объём ставок нужен, чтобы набрать house_take при данной комиссии."""
    rate = whole_percent(commission_rate)
    take = money(house_take)
    if take <= 0:
        return Decimal("0.00")
    if rate <= 0:
        return Decimal("0.00")
    return money(take * HUNDRED / rate)


def _game_commission_rate(game: Mapping[str, object], fallback_rate: Decimal) -> Decimal:
    raw = game.get("commission_rate")
    if raw is None or raw == "":
        return fallback_rate
    try:
        return whole_percent(raw)
    except ValueError:
        return fallback_rate


async def _load_wagering_settings(conn) -> tuple[Decimal, Decimal, Decimal]:
    rows = await conn.fetch(
        """
        SELECT key, value FROM casino_settings
        WHERE key = ANY($1::text[])
        """,
        [
            "wagering_percent",
            "commission_rate_wagering_active",
            "commission_rate_wagering_complete",
        ],
    )
    values = {str(row["key"]): row["value"] for row in rows}
    return (
        _percent_from_settings(values, "wagering_percent", DEFAULT_WAGERING_PERCENT),
        _percent_from_settings(
            values,
            "commission_rate_wagering_active",
            DEFAULT_COMMISSION_RATE_WAGERING_ACTIVE,
        ),
        _percent_from_settings(
            values,
            "commission_rate_wagering_complete",
            DEFAULT_COMMISSION_RATE_WAGERING_COMPLETE,
        ),
    )


async def record_deposit_lock(
    conn, *, deal_id: int, telegram_id: int, deposit_rub: Decimal
) -> None:
    """Создать wagering-lock при кредите депозита (идемпотентно по deal_id)."""
    deposit = money(deposit_rub)
    if deposit <= 0:
        return
    wagering_percent, _, _ = await _load_wagering_settings(conn)
    required = money(deposit * wagering_percent / HUNDRED)
    unlocked = required <= 0
    await conn.execute(
        """
        INSERT INTO casino_wagering_locks
            (deal_id, telegram_id, deposit_rub, required_commission_rub, unlocked, unlocked_at)
        VALUES ($1, $2, $3, $4, $5, CASE WHEN $5 THEN now() ELSE NULL END)
        ON CONFLICT (deal_id) DO NOTHING
        """,
        deal_id,
        telegram_id,
        deposit,
        required,
        unlocked,
    )


async def record_crypto_deposit_lock(
    conn, *, crypto_credit_id: int, telegram_id: int, deposit_rub: Decimal
) -> None:
    """Тот же отыгрыш, что у фиатного депозита, но без external deal."""
    if telegram_id == 0:
        raise ValueError("client id is required")
    deposit = money(deposit_rub)
    if deposit <= 0:
        return
    wagering_percent, _, _ = await _load_wagering_settings(conn)
    required = money(deposit * wagering_percent / HUNDRED)
    unlocked = required <= 0
    await conn.execute(
        """
        INSERT INTO casino_wagering_locks
            (crypto_credit_id, telegram_id, deposit_rub, required_commission_rub, unlocked, unlocked_at)
        VALUES ($1, $2, $3, $4, $5, CASE WHEN $5 THEN now() ELSE NULL END)
        ON CONFLICT (crypto_credit_id) WHERE crypto_credit_id IS NOT NULL DO NOTHING
        """,
        crypto_credit_id,
        telegram_id,
        deposit,
        required,
        unlocked,
    )


async def _wagering_rows(conn, telegram_id: int) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
    """Загрузить упорядоченные локи и законченные ставки одним снимком транзакции."""
    locks = await conn.fetch(
        """
        SELECT id, deposit_rub, required_commission_rub, unlocked, created_at
        FROM casino_wagering_locks
        WHERE telegram_id = $1
        ORDER BY created_at, id
        FOR UPDATE
        """,
        telegram_id,
    )
    if not locks:
        return [], []
    games = await conn.fetch(
        """
        SELECT id, bet_rub, finished_at,
               game_data -> 'pricing_snapshot' ->> 'commission_rate' AS commission_rate
        FROM casino_games
        WHERE status = 'finished'
          AND finished_at IS NOT NULL
          AND finished_at >= $2
          AND (creator_id = $1 OR opponent_id = $1)
        ORDER BY finished_at, id
        """,
        telegram_id,
        locks[0]["created_at"],
    )
    return list(locks), list(games)


def _allocate_wagering(
    locks: list[Mapping[str, object]],
    games: list[Mapping[str, object]],
    *,
    fallback_rate: Decimal,
) -> dict[int, Decimal]:
    """Распределить комиссию с каждой завершённой ставки по lock-ам не более одного раза."""
    done = {int(lock["id"]): Decimal("0.00") for lock in locks}
    lock_index = 0
    for game in games:
        remaining_take = house_take_from_stake(
            game["bet_rub"], _game_commission_rate(game, fallback_rate)
        )
        while remaining_take > 0 and lock_index < len(locks):
            lock = locks[lock_index]
            if game["finished_at"] < lock["created_at"]:
                break
            required = money(lock["required_commission_rub"])
            available = money(required - done[int(lock["id"])])
            if available <= 0:
                lock_index += 1
                continue
            used = min(remaining_take, available)
            done[int(lock["id"])] = money(done[int(lock["id"])] + used)
            remaining_take = money(remaining_take - used)
            if done[int(lock["id"])] >= required:
                lock_index += 1
    return done


async def _progress_with_conn(
    conn, telegram_id: int
) -> tuple[list[Mapping[str, object]], dict[int, Decimal], Decimal]:
    locks, games = await _wagering_rows(conn, telegram_id)
    _, active_rate, _ = await _load_wagering_settings(conn)
    done = _allocate_wagering(locks, games, fallback_rate=active_rate)
    for lock in locks:
        lock_id = int(lock["id"])
        if not bool(lock["unlocked"]) and done[lock_id] >= money(lock["required_commission_rub"]):
            await conn.execute(
                """UPDATE casino_wagering_locks
                   SET unlocked = TRUE, unlocked_at = now()
                   WHERE id = $1 AND unlocked = FALSE""",
                lock_id,
            )
    return locks, done, active_rate


async def locked_by_wagering(conn, telegram_id: int) -> Decimal:
    """Сумма (₽), запертая к выводу невыполненным отыгрышем."""
    locks, done, _ = await _progress_with_conn(conn, telegram_id)
    return money(
        sum(
            (
                money(lock["deposit_rub"])
                for lock in locks
                if done[int(lock["id"])] < money(lock["required_commission_rub"])
            ),
            Decimal("0"),
        )
    )


async def wagering_progress(conn, telegram_id: int) -> dict[str, Decimal]:
    """Сводка прогресса отыгрыша для показа игроку.

    required_commission_rub в локе — плюс казино (21% от депозита).
    remaining_rub / required_rub — объём ставок, который ещё нужно поставить
    при текущей комиссии «до отыгрыша», чтобы этот плюс набрать.
    """
    locks, done_by_lock, active_rate = await _progress_with_conn(conn, telegram_id)
    active = [
        lock for lock in locks
        if done_by_lock[int(lock["id"])] < money(lock["required_commission_rub"])
    ]
    locked = money(sum((money(lock["deposit_rub"]) for lock in active), Decimal("0")))
    required_house = money(
        sum((money(lock["required_commission_rub"]) for lock in active), Decimal("0"))
    )
    done_house = money(sum((done_by_lock[int(lock["id"])] for lock in active), Decimal("0")))
    remaining_house = max(Decimal("0.00"), money(required_house - done_house))
    required_stake = stake_for_house_take(required_house, active_rate)
    done_stake = stake_for_house_take(done_house, active_rate)
    remaining_stake = stake_for_house_take(remaining_house, active_rate)
    return {
        "locked_rub": locked,
        "required_house_take_rub": required_house,
        "done_house_take_rub": done_house,
        "remaining_house_take_rub": remaining_house,
        "commission_rate_percent": money(active_rate),
        "required_stake_rub": required_stake,
        "done_stake_rub": done_stake,
        "remaining_stake_rub": remaining_stake,
        "required_rub": required_stake,
        "done_rub": done_stake,
        "remaining_rub": remaining_stake,
    }


def serialize_wagering_progress(progress: Mapping[str, Decimal]) -> dict[str, str]:
    """Строки для internal API и outbox — игрок видит объём ставок, не «210 отыграть»."""
    return {key: format(money(value), ".2f") for key, value in progress.items()}


async def commission_rate_for_player(conn, telegram_id: int) -> Decimal:
    """Вернуть ставку комиссии, закрепляемую за новым необратимым исходом игры."""
    profile, rate = await commission_profile_for_player(conn, telegram_id)
    _ = profile
    return rate


async def commission_profile_for_player(
    conn, telegram_id: int
) -> tuple[Literal["wagering_active", "wagering_complete"], Decimal]:
    """Вернуть имя профиля и ставку комиссии для нового необратимого исхода игры."""
    from casino_finance import load_casino_settings
    from casino_tier_config import load_tier_config, resolve_commission_volume_tier
    from casino_weekly_wager import weekly_wager_rub

    settings = await load_casino_settings(conn)
    _ = settings
    tier_config = await load_tier_config(conn)
    wager_rub = await weekly_wager_rub(conn, telegram_id)
    volume_tier = resolve_commission_volume_tier(tier_config.commission_volume_tiers, wager_rub)

    progress = await wagering_progress(conn, telegram_id)
    if progress["remaining_house_take_rub"] > 0:
        return "wagering_active", volume_tier.active_rate
    return "wagering_complete", volume_tier.complete_rate
