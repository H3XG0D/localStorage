"""Чистые денежные расчёты для отображения результатов казино."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping


MONEY_QUANTUM = Decimal("0.01")
DEFAULT_COMMISSION_RATE_PERCENT = Decimal("15")
DEFAULT_CREATOR_CUT_PERCENT = Decimal("5")
DEFAULT_REFERRAL_L1_PERCENT = Decimal("2")
DEFAULT_REFERRAL_L2_PERCENT = Decimal("2")
DEFAULT_MIN_BET_RUB = Decimal("10.00")
DEFAULT_MAX_BET_RUB = Decimal("100000.00")


@dataclass(frozen=True)
class CasinoGamePolicy:
    """Снимок недоверенных UI-проверок из актуальных настроек backend."""

    game_key: str
    enabled: bool
    min_bet_rub: Decimal
    max_bet_rub: Decimal
    commission_rate_percent: Decimal
    creator_cut_percent: Decimal
    referral_l1_percent: Decimal
    referral_l2_percent: Decimal


@dataclass(frozen=True)
class HeadToHeadSettlement:
    """Расчёт равных ставок без доверия к нему при движении денег."""

    stake_per_player: Decimal
    pot: Decimal
    commission: Decimal
    payout: Decimal


def to_decimal(value: Any) -> Decimal:
    """Безопасно преобразовать число/строку в Decimal без float-артефактов."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def money(value: Any) -> Decimal:
    """Округлить денежную сумму до копеек по ROUND_HALF_UP."""
    return to_decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def setting_decimal(
    settings: Mapping[str, Any],
    *,
    key: str,
    nested_key: str,
    default: Any,
) -> Decimal:
    """Прочитать JSON-настройку backend вида {key: {nested_key: value}}."""
    raw_value = settings.get(key, default)
    if isinstance(raw_value, Mapping):
        raw_value = raw_value.get(nested_key, default)
    return to_decimal(raw_value)


def casino_game_policy(
    settings: Mapping[str, Any],
    *,
    game_key: str,
    local_min_bet_rub: Any = DEFAULT_MIN_BET_RUB,
) -> CasinoGamePolicy:
    """Нормализовать settings для ранней проверки create/join в боте.

    Это только UX-проверка снимка настроек. Backend обязан повторно проверять
    enabled/min/max при hold и settlement и остаётся источником истины.
    """
    enabled_games = settings.get("enabled_games", {})
    enabled = True
    if isinstance(enabled_games, Mapping):
        raw_enabled = enabled_games.get(game_key, True)
        if isinstance(raw_enabled, bool):
            enabled = raw_enabled

    backend_min = money(
        setting_decimal(
            settings,
            key="min_bet_rub",
            nested_key="amount",
            default=DEFAULT_MIN_BET_RUB,
        )
    )
    local_min = money(local_min_bet_rub)
    max_bet = money(
        setting_decimal(
            settings,
            key="max_bet_rub",
            nested_key="amount",
            default=DEFAULT_MAX_BET_RUB,
        )
    )
    min_bet = max(backend_min, local_min)
    if max_bet < min_bet:
        raise ValueError("max_bet_rub must be greater than or equal to min_bet_rub")

    return CasinoGamePolicy(
        game_key=game_key,
        enabled=enabled,
        min_bet_rub=min_bet,
        max_bet_rub=max_bet,
        commission_rate_percent=setting_decimal(
            settings,
            key="commission_rate",
            nested_key="percent",
            default=DEFAULT_COMMISSION_RATE_PERCENT,
        ),
        creator_cut_percent=setting_decimal(
            settings,
            key="creator_cut_percent",
            nested_key="percent",
            default=DEFAULT_CREATOR_CUT_PERCENT,
        ),
        referral_l1_percent=setting_decimal(
            settings,
            key="referral_l1_percent",
            nested_key="percent",
            default=DEFAULT_REFERRAL_L1_PERCENT,
        ),
        referral_l2_percent=setting_decimal(
            settings,
            key="referral_l2_percent",
            nested_key="percent",
            default=DEFAULT_REFERRAL_L2_PERCENT,
        ),
    )


def validate_game_stake(*, policy: CasinoGamePolicy, stake_rub: Any) -> Decimal:
    """Проверить включение игры и лимиты снимка settings до hold."""
    stake = money(stake_rub)
    if not policy.enabled:
        raise ValueError("game_disabled")
    if stake < policy.min_bet_rub:
        raise ValueError("stake_below_minimum")
    if stake > policy.max_bet_rub:
        raise ValueError("stake_above_maximum")
    return stake


def settlement_payout_rub(response: Mapping[str, Any]) -> Decimal:
    """Извлечь сумму выплаты из доверенного ответа backend settlement."""
    try:
        payout = money(response["payout_rub"])
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("Settlement response has no valid payout_rub") from exc
    if not payout.is_finite() or payout <= 0:
        raise ValueError("Settlement response has no valid payout_rub")
    return payout


def calculate_head_to_head_settlement(
    *,
    stake_per_player: Any,
    commission_rate_percent: Any,
) -> HeadToHeadSettlement:
    """Рассчитать отображаемые суммы для двух равных ставок.

    Комиссия берётся только с проигравшей ставки. Доверенное списание,
    выплата и распределение долей должны выполняться backend settlement.
    """
    stake = money(stake_per_player)
    rate = to_decimal(commission_rate_percent)
    if stake <= 0:
        raise ValueError("stake_per_player must be positive")
    if rate < 0 or rate > 100:
        raise ValueError("commission_rate_percent must be between 0 and 100")

    pot = money(stake * 2)
    commission = money(stake * rate / Decimal("100"))
    payout = money(pot - commission)
    return HeadToHeadSettlement(
        stake_per_player=stake,
        pot=pot,
        commission=commission,
        payout=payout,
    )
