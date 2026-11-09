"""Денежные расчёты и операции unified balance для internal casino API."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from casino_settings_registry import default_numeric

MONEY_STEP = Decimal("0.01")
HUNDRED = Decimal("100")

HEAD_TO_HEAD_GAME_TYPES = (
    "pvp_dice",
    "baccara",
    "blackjack",
)
KNOWN_GAME_TYPES = (
    *HEAD_TO_HEAD_GAME_TYPES,
    "raffle",
    "cub",
    "roulette",
    "holdem",
    "jackpot",
    "fixed_room",
    "clan_war",
    "russian_draughts",
)
RETIRED_SPORT_GAME_TYPES = frozenset(
    {"pvp_darts", "pvp_bowling", "pvp_football", "pvp_basketball"}
)

#: Hard cap of robot seats per player table — a table is for people, a bot only fills one gap.
MAX_BOTS_PER_TABLE = 1

GameType = Literal[
    "pvp_dice",
    "baccara",
    "blackjack",
]
PositiveTelegramId = Annotated[int, Field(gt=0)]
#: Telegram id (>0) or password-web `client_user_id` (<0). Zero is never a user.
ClientUserId = Annotated[int, Field(gt=0)] | Annotated[int, Field(lt=0)]
MoneyInput = Annotated[
    Decimal,
    Field(gt=Decimal("0"), max_digits=14, decimal_places=2, allow_inf_nan=False),
]


def money(value: Decimal | int | float | str) -> Decimal:
    """Привести денежное значение к копейкам без двоичной арифметики."""
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid money value") from exc
    if not result.is_finite():
        raise ValueError("Money value must be finite")
    return result.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def whole_percent(value: Decimal | int | float | str) -> Decimal:
    """Проверить процент в каноническом формате 0..100."""
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Percent must be between 0 and 100") from exc
    if not result.is_finite() or result < 0 or result > HUNDRED:
        raise ValueError("Percent must be between 0 and 100")
    return result


@dataclass(frozen=True)
class EqualStakeSettlement:
    losing_stake: Decimal
    pot: Decimal
    commission: Decimal
    payout: Decimal


@dataclass(frozen=True)
class HouseGameSettlement:
    stake: Decimal
    payout: Decimal
    house_delta: Decimal
    commission: Decimal


@dataclass(frozen=True)
class CommissionAllocation:
    creator: Decimal
    referral_l1: Decimal
    referral_l2: Decimal
    owner: Decimal

    @property
    def total(self) -> Decimal:
        return money(self.creator + self.referral_l1 + self.referral_l2 + self.owner)


@dataclass(frozen=True)
class CasinoSettings:
    commission_rate: Decimal
    commission_rate_wagering_active: Decimal
    commission_rate_wagering_complete: Decimal
    wagering_percent: Decimal
    creator_cut_percent: Decimal
    referral_l1_percent: Decimal
    referral_l2_percent: Decimal
    creator_cut_percent_wagering_active: Decimal
    referral_l1_percent_wagering_active: Decimal
    referral_l2_percent_wagering_active: Decimal
    creator_cut_percent_wagering_complete: Decimal
    referral_l1_percent_wagering_complete: Decimal
    referral_l2_percent_wagering_complete: Decimal
    min_bet_rub: Decimal
    max_bet_rub: Decimal
    min_withdrawal_rub: Decimal
    enabled_games: dict[str, bool]
    commission_cap_rub: Decimal = Decimal("0")
    commission_min_rub: Decimal = Decimal("0")
    max_profit_pct_per_round: Decimal = Decimal("1")
    max_profit_pct_per_round_all: Decimal = Decimal("1.5")
    bankroll_floor_rub: Decimal = Decimal("0")
    liability_amount_rub: Decimal = Decimal("0")
    per_game_limits: dict[str, dict[str, Decimal]] = field(default_factory=dict)

    def public_dict(self) -> dict[str, object]:
        return {
            "commission_rate": float(self.commission_rate),
            "commission_rate_wagering_active": float(self.commission_rate_wagering_active),
            "commission_rate_wagering_complete": float(self.commission_rate_wagering_complete),
            "wagering_percent": float(self.wagering_percent),
            "creator_cut_percent": float(self.creator_cut_percent),
            "referral_l1_percent": float(self.referral_l1_percent),
            "referral_l2_percent": float(self.referral_l2_percent),
            "creator_cut_percent_wagering_active": float(self.creator_cut_percent_wagering_active),
            "referral_l1_percent_wagering_active": float(self.referral_l1_percent_wagering_active),
            "referral_l2_percent_wagering_active": float(self.referral_l2_percent_wagering_active),
            "creator_cut_percent_wagering_complete": float(self.creator_cut_percent_wagering_complete),
            "referral_l1_percent_wagering_complete": float(self.referral_l1_percent_wagering_complete),
            "referral_l2_percent_wagering_complete": float(self.referral_l2_percent_wagering_complete),
            "min_bet_rub": float(self.min_bet_rub),
            "max_bet_rub": float(self.max_bet_rub),
            "min_withdrawal_rub": float(self.min_withdrawal_rub),
            "enabled_games": self.enabled_games.copy(),
        }


class SettlementRequest(BaseModel):
    """Единственный доверенный контракт финансового завершения P2P-игры."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    game_id: str = Field(min_length=1, max_length=64)
    game_type: GameType
    creator_id: PositiveTelegramId
    opponent_id: PositiveTelegramId
    winner_id: PositiveTelegramId
    creator_hold_id: str = Field(min_length=1, max_length=128)
    opponent_hold_id: str = Field(min_length=1, max_length=128)
    stake_rub: MoneyInput

    @field_validator("game_id", "creator_hold_id", "opponent_hold_id")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_players_and_holds(self):
        if self.creator_id == self.opponent_id:
            raise ValueError("Players must be different")
        if self.winner_id not in (self.creator_id, self.opponent_id):
            raise ValueError("Winner must be one of the players")
        if self.creator_hold_id == self.opponent_hold_id:
            raise ValueError("Player holds must be different")
        return self


def calculate_house_settlement(
    stake_rub: Decimal | int | float | str,
    payout_multiplier: Decimal | int | float | str,
    commission_rate: Decimal | int | float | str = Decimal("0"),
    *,
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
) -> HouseGameSettlement:
    """Рассчитать выплату игры против дома с удержанием из выигрыша игрока."""
    from casino_settings_registry import clamp_commission_rub

    stake = money(stake_rub)
    if stake <= 0:
        raise ValueError("Stake must be positive")
    try:
        multiplier = Decimal(str(payout_multiplier))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid payout multiplier") from exc
    if not multiplier.is_finite() or multiplier < 0:
        raise ValueError("Payout multiplier must be non-negative")
    gross_payout = money(stake * multiplier)
    rate = whole_percent(commission_rate)
    winnings = max(Decimal("0.00"), money(gross_payout - stake))
    commission = clamp_commission_rub(
        money(winnings * rate / HUNDRED),
        cap_rub=commission_cap_rub,
        min_rub=commission_min_rub,
    )
    payout = money(gross_payout - commission)
    return HouseGameSettlement(
        stake=stake,
        payout=payout,
        house_delta=money(stake - payout),
        commission=commission,
    )


def calculate_equal_stake_settlement(
    stake_each: Decimal | int | float | str,
    commission_rate: Decimal | int | float | str,
    *,
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
) -> EqualStakeSettlement:
    """Рассчитать банк, комиссию от проигранной ставки и выплату победителю."""
    from casino_settings_registry import clamp_commission_rub

    stake = money(stake_each)
    if stake <= 0:
        raise ValueError("Stake must be positive")
    rate = whole_percent(commission_rate)
    pot = money(stake * 2)
    commission = clamp_commission_rub(
        money(stake * rate / HUNDRED),
        cap_rub=commission_cap_rub,
        min_rub=commission_min_rub,
    )
    payout = money(pot - commission)
    return EqualStakeSettlement(
        losing_stake=stake,
        pot=pot,
        commission=commission,
        payout=payout,
    )


def game_stake_bounds(
    settings: CasinoSettings,
    game_type: str,
    *,
    payout_multiplier: Decimal | int | float | str = Decimal("2"),
    bankroll_rub: Decimal | int | float | str = Decimal("0"),
) -> tuple[Decimal, Decimal]:
    """Нижняя и верхняя ставка: глобальный min/max, per_game_limits, потолок выигрыша."""
    from casino_settings_registry import effective_max_stake

    per = settings.per_game_limits.get(game_type) or {}
    min_bet = money(per["min"]) if "min" in per else settings.min_bet_rub
    max_bet = money(per["max"]) if "max" in per else settings.max_bet_rub
    capped = effective_max_stake(
        max_bet_rub=max_bet,
        liability_amount_rub=settings.liability_amount_rub,
        max_profit_pct_per_round=settings.max_profit_pct_per_round,
        bankroll_rub=bankroll_rub,
        payout_multiplier=payout_multiplier,
    )
    return min_bet, min(max_bet, capped)


def allocate_legacy_commission(
    commission: Decimal | int | float | str,
    *,
    creator_percent: Decimal | int | float | str,
    referral_l1_percent: Decimal | int | float | str,
    referral_l2_percent: Decimal | int | float | str,
    has_creator: bool,
    has_referral_l1: bool,
    has_referral_l2: bool,
) -> CommissionAllocation:
    """Сохранить исторический расчёт для исходов без версии модели."""
    total = money(commission)
    creator_rate = whole_percent(creator_percent)
    l1_rate = whole_percent(referral_l1_percent)
    l2_rate = whole_percent(referral_l2_percent)
    if creator_rate + l1_rate + l2_rate > HUNDRED:
        raise ValueError("Commission allocation percentages cannot exceed 100")

    remaining = total

    def take(rate: Decimal, present: bool) -> Decimal:
        nonlocal remaining
        if not present or remaining <= 0:
            return Decimal("0.00")
        allocated = min(money(total * rate / HUNDRED), remaining)
        remaining = money(remaining - allocated)
        return allocated

    result = CommissionAllocation(
        take(creator_rate, has_creator),
        take(l1_rate, has_referral_l1),
        take(l2_rate, has_referral_l2),
        money(remaining),
    )
    if result.total != total:
        raise AssertionError("Commission allocations must equal commission")
    return result


def allocate_commission(
    losing_stake: Decimal | int | float | str,
    *,
    commission_rate: Decimal | int | float | str,
    creator_percent: Decimal | int | float | str,
    referral_l1_percent: Decimal | int | float | str,
    referral_l2_percent: Decimal | int | float | str,
    has_creator: bool,
    has_referral_l1: bool,
    has_referral_l2: bool,
    commission_cap_rub: Decimal | int | float | str = Decimal("0"),
    commission_min_rub: Decimal | int | float | str = Decimal("0"),
) -> CommissionAllocation:
    """Распределить удержание по долям от проигранной ставки.

    Creator и реферальные проценты — абсолютные доли ставки. Остаток комиссии,
    включая доли отсутствующих рефереров и копейки округления, получает owner.
    """
    from casino_settings_registry import clamp_commission_rub

    stake = money(losing_stake)
    if stake <= 0:
        raise ValueError("Losing stake must be positive")
    total = clamp_commission_rub(
        money(stake * whole_percent(commission_rate) / HUNDRED),
        cap_rub=commission_cap_rub,
        min_rub=commission_min_rub,
    )
    creator_rate = whole_percent(creator_percent)
    l1_rate = whole_percent(referral_l1_percent)
    l2_rate = whole_percent(referral_l2_percent)
    if creator_rate + l1_rate + l2_rate > whole_percent(commission_rate):
        raise ValueError("Recipient shares cannot exceed the commission rate")

    remaining = total

    def take(rate: Decimal, present: bool) -> Decimal:
        nonlocal remaining
        if not present or remaining <= 0:
            return Decimal("0.00")
        allocated = min(money(stake * rate / HUNDRED), remaining)
        remaining = money(remaining - allocated)
        return allocated

    creator = take(creator_rate, has_creator)
    referral_l1 = take(l1_rate, has_referral_l1)
    referral_l2 = take(l2_rate, has_referral_l2)
    result = CommissionAllocation(creator, referral_l1, referral_l2, money(remaining))
    if result.total != total:
        raise AssertionError("Commission allocations must equal commission")
    return result


CommissionProfileName = Literal["wagering_active", "wagering_complete", "base"]


def scale_stake_share_percents(
    actual_commission_rate: Decimal | int | float | str,
    base_commission_rate: Decimal | int | float | str,
    creator_percent: Decimal | int | float | str,
    referral_l1_percent: Decimal | int | float | str,
    referral_l2_percent: Decimal | int | float | str,
) -> tuple[Decimal, Decimal, Decimal]:
    """Пропорционально уменьшить доли ставки, если комиссия снижена сеткой оборота."""
    actual = whole_percent(actual_commission_rate)
    base = whole_percent(base_commission_rate)
    if base <= 0 or actual == base:
        return (
            whole_percent(creator_percent),
            whole_percent(referral_l1_percent),
            whole_percent(referral_l2_percent),
        )
    scale = actual / base
    creator = whole_percent(Decimal(str(creator_percent)) * scale)
    referral_l1 = whole_percent(Decimal(str(referral_l1_percent)) * scale)
    referral_l2 = whole_percent(Decimal(str(referral_l2_percent)) * scale)
    if creator + referral_l1 + referral_l2 > actual:
        raise ValueError("Scaled recipient shares cannot exceed the commission rate")
    return creator, referral_l1, referral_l2


def commission_shares_for_rate(
    settings: CasinoSettings,
    *,
    profile: CommissionProfileName,
    commission_rate: Decimal | int | float | str,
) -> tuple[Decimal, Decimal, Decimal]:
    """Вернуть доли ставки для фактической комиссии с учётом сетки оборота."""
    rate = whole_percent(commission_rate)
    if profile == "wagering_active":
        base_rate = settings.commission_rate_wagering_active
    elif profile == "wagering_complete":
        base_rate = settings.commission_rate_wagering_complete
    else:
        base_rate = settings.commission_rate
    creator, l1, l2 = commission_share_profile(settings, base_rate, profile=profile)
    return scale_stake_share_percents(rate, base_rate, creator, l1, l2)


def commission_share_profile(
    settings: CasinoSettings,
    commission_rate: Decimal | int | float | str,
    *,
    profile: CommissionProfileName | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Вернуть абсолютные доли ставки для зафиксированной игровой комиссии."""
    if profile == "wagering_active":
        return (
            settings.creator_cut_percent_wagering_active,
            settings.referral_l1_percent_wagering_active,
            settings.referral_l2_percent_wagering_active,
        )
    if profile == "wagering_complete":
        return (
            settings.creator_cut_percent_wagering_complete,
            settings.referral_l1_percent_wagering_complete,
            settings.referral_l2_percent_wagering_complete,
        )
    rate = whole_percent(commission_rate)
    if profile is None and rate == settings.commission_rate_wagering_active:
        return commission_share_profile(settings, rate, profile="wagering_active")
    if profile is None and rate == settings.commission_rate_wagering_complete:
        return commission_share_profile(settings, rate, profile="wagering_complete")
    return (
        settings.creator_cut_percent,
        settings.referral_l1_percent,
        settings.referral_l2_percent,
    )


def _json_object(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _setting_decimal(
    values: Mapping[str, object],
    key: str,
    field: str,
) -> Decimal:
    raw_container = _json_object(values.get(key))
    if raw_container is None:
        return default_numeric(key)
    raw = raw_container.get(field)
    if isinstance(raw, bool) or raw is None:
        return default_numeric(key)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return default_numeric(key)


def canonical_casino_settings(rows: Sequence[Mapping[str, object]]) -> CasinoSettings:
    """Нормализовать JSONB-настройки в единый плоский контракт."""
    values = {str(row["key"]): row["value"] for row in rows}
    commission_rate = whole_percent(
        _setting_decimal(values, "commission_rate", "percent")
    )
    commission_active = whole_percent(
        _setting_decimal(values, "commission_rate_wagering_active", "percent")
    )
    commission_complete = whole_percent(
        _setting_decimal(values, "commission_rate_wagering_complete", "percent")
    )
    wagering_percent = whole_percent(
        _setting_decimal(values, "wagering_percent", "percent")
    )
    creator_cut = whole_percent(
        _setting_decimal(values, "creator_cut_percent", "percent")
    )
    referral_l1 = whole_percent(
        _setting_decimal(values, "referral_l1_percent", "percent")
    )
    referral_l2 = whole_percent(
        _setting_decimal(values, "referral_l2_percent", "percent")
    )
    creator_active = whole_percent(
        _setting_decimal(values, "creator_cut_percent_wagering_active", "percent")
    )
    referral_l1_active = whole_percent(
        _setting_decimal(values, "referral_l1_percent_wagering_active", "percent")
    )
    referral_l2_active = whole_percent(
        _setting_decimal(values, "referral_l2_percent_wagering_active", "percent")
    )
    creator_complete = whole_percent(
        _setting_decimal(values, "creator_cut_percent_wagering_complete", "percent")
    )
    referral_l1_complete = whole_percent(
        _setting_decimal(values, "referral_l1_percent_wagering_complete", "percent")
    )
    referral_l2_complete = whole_percent(
        _setting_decimal(values, "referral_l2_percent_wagering_complete", "percent")
    )
    if creator_cut + referral_l1 + referral_l2 > commission_rate:
        raise ValueError("Recipient shares cannot exceed the commission rate")
    if creator_active + referral_l1_active + referral_l2_active > commission_active:
        raise ValueError("Active wagering recipient shares cannot exceed the commission rate")
    if creator_complete + referral_l1_complete + referral_l2_complete > commission_complete:
        raise ValueError("Complete wagering recipient shares cannot exceed the commission rate")

    min_bet = money(_setting_decimal(values, "min_bet_rub", "amount"))
    max_bet = money(_setting_decimal(values, "max_bet_rub", "amount"))
    min_withdrawal = money(
        _setting_decimal(values, "min_withdrawal_rub", "amount")
    )
    if min_bet <= 0 or max_bet <= 0 or min_bet > max_bet:
        raise ValueError("Invalid casino bet limits")
    if min_withdrawal <= 0:
        raise ValueError("Invalid casino minimum withdrawal")

    commission_cap = money(_setting_decimal(values, "commission_cap_rub", "amount"))
    commission_min = money(_setting_decimal(values, "commission_min_rub", "amount"))
    max_profit_pct = _setting_decimal(values, "max_profit_pct_per_round", "percent")
    max_profit_pct_all = _setting_decimal(values, "max_profit_pct_per_round_all", "percent")
    bankroll_floor = money(_setting_decimal(values, "bankroll_floor_rub", "amount"))
    liability_amount = money(_setting_decimal(values, "liability_amount_rub", "amount"))
    per_game_limits: dict[str, dict[str, Decimal]] = {}
    raw_limits = values.get("per_game_limits")
    parsed_limits = raw_limits if isinstance(raw_limits, Mapping) else _json_object(raw_limits)
    if isinstance(parsed_limits, Mapping):
        for game_type, bounds in parsed_limits.items():
            if game_type not in KNOWN_GAME_TYPES or not isinstance(bounds, Mapping):
                continue
            entry: dict[str, Decimal] = {}
            for field_name in ("min", "max"):
                if bounds.get(field_name) is None:
                    continue
                try:
                    entry[field_name] = money(bounds[field_name])
                except (InvalidOperation, ValueError):
                    continue
            if entry:
                per_game_limits[str(game_type)] = entry

    enabled = {game_type: False for game_type in KNOWN_GAME_TYPES}
    raw_enabled = _json_object(values.get("enabled_games"))
    if raw_enabled is not None:
        for game_type in KNOWN_GAME_TYPES:
            if isinstance(raw_enabled.get(game_type), bool):
                enabled[game_type] = raw_enabled[game_type]

    return CasinoSettings(
        commission_rate=commission_rate,
        commission_rate_wagering_active=commission_active,
        commission_rate_wagering_complete=commission_complete,
        wagering_percent=wagering_percent,
        creator_cut_percent=creator_cut,
        referral_l1_percent=referral_l1,
        referral_l2_percent=referral_l2,
        creator_cut_percent_wagering_active=creator_active,
        referral_l1_percent_wagering_active=referral_l1_active,
        referral_l2_percent_wagering_active=referral_l2_active,
        creator_cut_percent_wagering_complete=creator_complete,
        referral_l1_percent_wagering_complete=referral_l1_complete,
        referral_l2_percent_wagering_complete=referral_l2_complete,
        min_bet_rub=min_bet,
        max_bet_rub=max_bet,
        min_withdrawal_rub=min_withdrawal,
        enabled_games=enabled,
        commission_cap_rub=commission_cap,
        commission_min_rub=commission_min,
        max_profit_pct_per_round=max_profit_pct,
        max_profit_pct_per_round_all=max_profit_pct_all,
        bankroll_floor_rub=bankroll_floor,
        liability_amount_rub=liability_amount,
        per_game_limits=per_game_limits,
    )


async def load_casino_settings(conn) -> CasinoSettings:
    rows = await conn.fetch("SELECT key, value FROM casino_settings")
    return canonical_casino_settings(rows)


def casino_ledger_order_ref(hold_id: str) -> str:
    """Короткий стабильный ключ, помещающийся в ledger.order_id вместе с префиксом."""
    digest = hashlib.sha256(hold_id.encode("utf-8")).hexdigest()[:32]
    return f"casino-h-{digest}"


def casino_operation_ref(kind: str, game_id: str, suffix: str = "") -> str:
    digest = hashlib.sha256(f"{game_id}:{suffix}".encode("utf-8")).hexdigest()[:32]
    return f"casino-{kind}-{digest}"


def _hold_order_ids(order_ref: str) -> tuple[str, str, str]:
    return (
        f"hold-{order_ref}",
        f"hold-{order_ref}:ref",
        f"hold-{order_ref}:partner",
    )


def _spent_order_ids(order_ref: str) -> tuple[str, str, str]:
    return (
        f"spend-{order_ref}",
        f"spend-{order_ref}:ref",
        f"spend-{order_ref}:partner",
    )


def _released_order_ids(order_ref: str) -> tuple[str, str, str]:
    return (
        f"refund-{order_ref}",
        f"refund-{order_ref}:ref",
        f"refund-{order_ref}:partner",
    )


async def lock_casino_game(conn, game_id: str) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended('casino-game:' || $1, 0))",
        game_id,
    )


async def lock_casino_users(conn, user_ids: Sequence[int]) -> None:
    for user_id in sorted(set(int(user_id) for user_id in user_ids)):
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('casino-user:' || $1::text, 0))",
            str(user_id),
        )


async def _backing_rows(conn, user_id: int, order_ref: str) -> tuple[object, object, object]:
    cashback_hold_id, referral_hold_id, partner_hold_id = _hold_order_ids(order_ref)
    cashback = await conn.fetchrow(
        """
        SELECT user_id, amount_rub
        FROM user_cashback_ledger
        WHERE order_id = $1 AND type = 'hold' AND user_id = $2
        """,
        cashback_hold_id,
        user_id,
    )
    referral = await conn.fetchrow(
        """
        SELECT referrer_user_id, amount_rub
        FROM user_referral_ledger
        WHERE order_id = $1 AND type = 'hold' AND referrer_user_id = $2
        """,
        referral_hold_id,
        user_id,
    )
    partner = await conn.fetchrow(
        """
        SELECT pl.campaign_id, pl.amount_rub
        FROM partner_ledger pl
        JOIN partner_accounts pa ON pa.promo_campaign_id = pl.campaign_id
        WHERE pl.order_id = $1
          AND pl.type = 'hold'
          AND pa.telegram_user_id = $2
        """,
        partner_hold_id,
        user_id,
    )
    return cashback, referral, partner


async def unified_hold_amount(conn, user_id: int, order_ref: str) -> Decimal:
    rows = await _backing_rows(conn, user_id, order_ref)
    return money(
        sum((abs(money(row["amount_rub"])) for row in rows if row), Decimal("0"))
    )


async def reserve_unified_funds(
    conn,
    *,
    user_id: int,
    order_ref: str,
    amount_rub: Decimal,
) -> None:
    """Создать подтверждаемую бронь во всех частях unified balance.

    Если игрок играет из фишек (бонусный или турнирный кошелёк), ставка уходит
    в фишки и реальный рублёвый баланс не трогается вовсе.
    """
    from casino_tournaments import reserve_tournament_chips
    from casino_wallet import KIND_BONUS, KIND_TOURNAMENT, active_scope, reserve_bonus_chips

    scope = await active_scope(conn, user_id)
    if scope.kind == KIND_TOURNAMENT:
        await reserve_tournament_chips(
            conn,
            tournament_id=int(scope.tournament_id),
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=amount_rub,
        )
        return
    if scope.kind == KIND_BONUS:
        await reserve_bonus_chips(
            conn,
            user_id=user_id,
            order_ref=order_ref,
            amount_rub=amount_rub,
        )
        return

    await reserve_real_funds(conn, user_id=user_id, order_ref=order_ref, amount_rub=amount_rub)


async def reserve_real_funds(
    conn,
    *,
    user_id: int,
    order_ref: str,
    amount_rub: Decimal,
) -> None:
    """Бронь строго из реальных рублей, независимо от выбранного кошелька.

    Нужна для платежей, которые никогда не платятся фишками: взнос и ребай турнира.
    """
    from user_cashback_db import hold_cashback_for_order

    amount = money(amount_rub)
    held = money(await hold_cashback_for_order(conn, user_id, order_ref, amount))
    if held != amount:
        raise ValueError("insufficient balance")
    backed = await unified_hold_amount(conn, user_id, order_ref)
    if backed != amount:
        raise RuntimeError("Unified balance hold was not fully persisted")


async def credit_house_game_settlement(
    conn,
    *,
    amount_rub: Decimal,
    entry_key: str,
    reason: str,
    sql_tag: str | None = None,
    allow_zero: bool = False,
) -> None:
    """Credit or debit the main house bankroll with an auditable game_settlement.

    Jackpot rake and room rake/bot-payout go here. V2 tables write
    casino_v2_house_ledger instead so owner P&L does not double-count.
    """
    amount = money(amount_rub)
    if amount == 0 and not allow_zero:
        return
    prefix = f"/* {sql_tag}:" if sql_tag else None

    def _tagged(tag: str, sql: str) -> str:
        if prefix:
            return f"{prefix}{tag} */\n{sql}"
        return sql

    existing = await conn.fetchrow(
        _tagged(
            "house-ledger-get",
            "SELECT amount_rub FROM casino_house_ledger WHERE entry_key = $1",
        ),
        entry_key,
    )
    if existing:
        if money(existing["amount_rub"]) != amount:
            raise RuntimeError("House settlement conflicts")
        return
    account = None
    if amount != 0:
        account = await conn.fetchrow(
            _tagged(
                "house",
                """
                UPDATE casino_house_accounts
                SET balance_rub = balance_rub + $1, updated_at = now()
                WHERE account_key = 'main'
                  AND balance_rub + $1 >= 0
                  AND reserved_rub <= balance_rub + $1
                RETURNING id, balance_rub
                """,
            ),
            amount,
        )
        if not account:
            raise RuntimeError("House bankroll cannot accept this settlement")
    else:
        account = await conn.fetchrow(
            _tagged(
                "house-account",
                """
                SELECT id, balance_rub FROM casino_house_accounts
                WHERE account_key = 'main'
                """,
            ),
        )
        if not account:
            raise RuntimeError("House bankroll cannot accept this settlement")
    inserted = await conn.fetchrow(
        _tagged(
            "house-ledger",
            """
            INSERT INTO casino_house_ledger (
                account_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
            ) VALUES ($1, $2, 'game_settlement', $3, $4, $5)
            ON CONFLICT (entry_key) DO NOTHING
            RETURNING id
            """,
        ),
        int(account["id"]),
        entry_key,
        amount,
        money(account["balance_rub"]),
        reason,
    )
    if inserted is None:
        replay = await conn.fetchrow(
            _tagged(
                "house-ledger-get",
                "SELECT amount_rub FROM casino_house_ledger WHERE entry_key = $1",
            ),
            entry_key,
        )
        if not replay or money(replay["amount_rub"]) != amount:
            raise RuntimeError("House settlement conflicts")


async def maybe_credit_tournament_payout(
    conn,
    *,
    user_id: int,
    order_id: str,
    amount_rub: Decimal,
    game_id: str = "",
) -> bool:
    """Route a game payout into chips when the player bets from a chip wallet.

    Kept under the historical name because every game engine calls it; it now covers
    both the bonus wallet and tournaments.
    """
    from casino_tournaments import credit_tournament_chips
    from casino_wallet import KIND_BONUS, KIND_TOURNAMENT, active_scope, credit_bonus_chips

    scope = await active_scope(conn, user_id)
    if scope.kind == KIND_TOURNAMENT:
        await credit_tournament_chips(
            conn,
            tournament_id=int(scope.tournament_id),
            user_id=user_id,
            order_id=order_id,
            amount_rub=amount_rub,
            game_id=game_id,
        )
        return True
    if scope.kind == KIND_BONUS:
        await credit_bonus_chips(
            conn,
            user_id=user_id,
            order_id=order_id,
            amount_rub=amount_rub,
            game_id=game_id,
        )
        return True
    return False


async def confirm_unified_hold(
    conn,
    *,
    user_id: int,
    order_ref: str,
    amount_rub: Decimal,
    note: str,
) -> None:
    """Атомарно перевести разложенный unified hold в окончательное списание."""
    from casino_tournaments import confirm_tournament_hold
    from casino_wallet import confirm_bonus_hold

    if await confirm_tournament_hold(conn, order_ref=order_ref, note=note):
        return
    if await confirm_bonus_hold(conn, order_ref=order_ref, note=note):
        return
    await confirm_real_hold(
        conn, user_id=user_id, order_ref=order_ref, amount_rub=amount_rub, note=note
    )


async def confirm_real_hold(
    conn,
    *,
    user_id: int,
    order_ref: str,
    amount_rub: Decimal,
    note: str,
) -> None:
    """Списание брони из реальных рублей без обращения к кошельку игрока."""
    amount = money(amount_rub)
    if await unified_hold_amount(conn, user_id, order_ref) != amount:
        raise RuntimeError("Unified balance hold does not match casino hold")

    hold_ids = _hold_order_ids(order_ref)
    spend_ids = _spent_order_ids(order_ref)
    await conn.execute(
        """
        UPDATE user_cashback_ledger
        SET type = 'spend', order_id = $2, note = $3
        WHERE order_id = $1 AND type = 'hold' AND user_id = $4
        """,
        hold_ids[0],
        spend_ids[0],
        note,
        user_id,
    )
    await conn.execute(
        """
        UPDATE user_referral_ledger
        SET type = 'spend', order_id = $2, note = $3
        WHERE order_id = $1 AND type = 'hold' AND referrer_user_id = $4
        """,
        hold_ids[1],
        spend_ids[1],
        note,
        user_id,
    )
    await conn.execute(
        """
        UPDATE partner_ledger pl
        SET type = 'spend', order_id = $2, note = $3
        FROM partner_accounts pa
        WHERE pl.order_id = $1
          AND pl.type = 'hold'
          AND pa.promo_campaign_id = pl.campaign_id
          AND pa.telegram_user_id = $4
        """,
        hold_ids[2],
        spend_ids[2],
        note,
        user_id,
    )


async def release_unified_hold(
    conn,
    *,
    user_id: int,
    order_ref: str,
    amount_rub: Decimal,
    note: str,
) -> None:
    """Освободить бронь, сохранив нулевые audit-записи без создания денег."""
    from casino_tournaments import release_tournament_hold
    from casino_wallet import release_bonus_hold

    if await release_tournament_hold(conn, order_ref=order_ref, note=note):
        return
    if await release_bonus_hold(conn, order_ref=order_ref, note=note):
        return
    amount = money(amount_rub)
    backed = await unified_hold_amount(conn, user_id, order_ref)
    if backed == Decimal("0.00"):
        return
    if backed != amount:
        raise RuntimeError("Unified balance hold does not match casino hold")

    hold_ids = _hold_order_ids(order_ref)
    release_ids = _released_order_ids(order_ref)
    await conn.execute(
        """
        UPDATE user_cashback_ledger
        SET type = 'adjustment', amount_rub = 0, order_id = $2, note = $3
        WHERE order_id = $1 AND type = 'hold' AND user_id = $4
        """,
        hold_ids[0],
        release_ids[0],
        note,
        user_id,
    )
    await conn.execute(
        """
        UPDATE user_referral_ledger
        SET type = 'adjustment', amount_rub = 0, order_id = $2, note = $3
        WHERE order_id = $1 AND type = 'hold' AND referrer_user_id = $4
        """,
        hold_ids[1],
        release_ids[1],
        note,
        user_id,
    )
    await conn.execute(
        """
        UPDATE partner_ledger pl
        SET type = 'adjustment', amount_rub = 0, order_id = $2, note = $3
        FROM partner_accounts pa
        WHERE pl.order_id = $1
          AND pl.type = 'hold'
          AND pa.promo_campaign_id = pl.campaign_id
          AND pa.telegram_user_id = $4
        """,
        hold_ids[2],
        release_ids[2],
        note,
        user_id,
    )
