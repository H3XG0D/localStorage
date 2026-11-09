"""Подгонка суммы SELL под открытый реквизит выплаты — только на котировке.

Клиент видит уже подогнанную сумму и она больше не меняется. Цель — чтобы
одна клиентская заявка закрывала реквизит целиком, без доливов и вторых чеков.

Предохранители: сдвиг не больше `sell_snap_cap_rub` и итоговый спред/наценка обязаны
остаться внутри коридора `sell_spread_min_pct .. sell_spread_max_pct`.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence

from payout_requisite_matcher import from_kop, to_kop

logger = logging.getLogger(__name__)

# Кэш целей обновляет фоновый матчер; котировка не ходит в БД.
_targets: tuple[int, ...] = ()
_targets_ts: float = 0.0
TARGETS_TTL_SEC = 600


def set_targets(values: Iterable[int]) -> None:
    global _targets, _targets_ts
    _targets = tuple(sorted({int(v) for v in values if int(v) > 0}))
    _targets_ts = time.time()


def clear_targets() -> None:
    set_targets([])


def get_targets() -> tuple[int, ...]:
    """Устаревший кэш не используем: лучше обычная котировка, чем подгонка под мусор."""
    if not _targets:
        return ()
    if time.time() - _targets_ts > TARGETS_TTL_SEC:
        return ()
    return _targets


def targets_from_free_amounts(free_amounts: Iterable) -> list[int]:
    return [to_kop(v) for v in free_amounts if to_kop(v) > 0]


def _pick_target(fiat_kop: int, cap_kop: int, targets: Sequence[int]) -> int | None:
    best: int | None = None
    best_delta: int | None = None
    for target in targets:
        delta = abs(target - fiat_kop)
        if delta == 0 or delta > cap_kop:
            continue
        # При равном сдвиге выбираем более выгодный клиенту (больший) вариант.
        if best_delta is None or delta < best_delta or (delta == best_delta and target > (best or 0)):
            best, best_delta = target, delta
    return best


def snap_sell_fiat(
    fiat: Decimal,
    crypto_amount: Decimal,
    market: Decimal,
    *,
    config: dict | None = None,
    targets: Sequence[int] | None = None,
) -> tuple[Decimal, Decimal] | None:
    """Вернуть (новая сумма ₽, новый курс) либо None — если подгонка неуместна."""
    if config is None:
        from runtime_settings import sell_snap_config

        config = sell_snap_config()
    if not config.get("enabled"):
        return None

    cap_kop = to_kop(config.get("cap_rub") or 0)
    if cap_kop <= 0:
        return None
    if crypto_amount is None or Decimal(str(crypto_amount)) <= 0:
        return None
    if market is None or Decimal(str(market)) <= 0:
        return None

    pool = tuple(targets) if targets is not None else get_targets()
    if not pool:
        return None

    target_kop = _pick_target(to_kop(fiat), cap_kop, pool)
    if target_kop is None:
        return None

    new_fiat = from_kop(target_kop)
    crypto = Decimal(str(crypto_amount))
    market_dec = Decimal(str(market))
    new_rate = (new_fiat / crypto).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if str(config.get("pricing_mode") or "discount") == "markup":
        spread_pct = (new_rate / market_dec - Decimal("1")) * 100
    else:
        spread_pct = (Decimal("1") - new_rate / market_dec) * 100

    lo = Decimal(str(config.get("spread_min_pct", 0)))
    hi = Decimal(str(config.get("spread_max_pct", 0)))
    if spread_pct < lo or spread_pct > hi:
        return None

    return new_fiat, new_rate
