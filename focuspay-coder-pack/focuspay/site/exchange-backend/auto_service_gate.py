"""Гейт обслуживания без оператора на смене (реквизиты + последующая авто-выплата)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from auto_settings import (
    auto_no_shift_enabled,
    auto_no_shift_max_rub,
    auto_no_shift_min_buy_paid,
    auto_no_shift_shadow_mode,
    auto_whitelist_user_ids,
)
from db import get_pool
from payin_requisite_rail import buy_paid_count

logger = logging.getLogger("auto_service_gate")

DecisionKind = Literal["allow_shift", "allow_auto", "block"]


@dataclass(frozen=True)
class NoShiftDecision:
    kind: DecisionKind
    reason: str
    shadow: bool = False
    coin: str = ""
    need: float | None = None
    spendable: float | None = None
    reserved: float | None = None


def _coin_block(
    reason: str,
    *,
    coin: str,
    need: float | None,
    spendable: float | None,
    reserved: float | None,
) -> NoShiftDecision:
    return NoShiftDecision(
        "block",
        reason,
        coin=coin,
        need=need,
        spendable=spendable,
        reserved=reserved,
    )


async def buy_coin_fits(
    conn,
    crypto: str | None,
    crypto_amount: float | None,
) -> NoShiftDecision | None:
    """None — этой монеты хватает. Иначе блок: сумма больше свободного остатка."""
    from auto_payout_guard import coin_spendable, order_coin, reserved_buy_crypto

    coin = order_coin(crypto)
    try:
        need = float(crypto_amount) if crypto_amount is not None else 0.0
    except (TypeError, ValueError):
        need = 0.0
    if not coin or need <= 0:
        return _coin_block("coin_unknown", coin=coin, need=None, spendable=None, reserved=None)

    spendable = await coin_spendable(coin)
    if spendable is None:
        return _coin_block("coin_unknown", coin=coin, need=need, spendable=None, reserved=None)

    reserved = await reserved_buy_crypto(conn, coin)
    if spendable + 1e-12 < need + reserved:
        return _coin_block(
            "coin_short",
            coin=coin,
            need=need,
            spendable=spendable,
            reserved=reserved,
        )
    return None


async def _user_override(conn, user_id: int) -> bool | None:
    val = await conn.fetchval(
        "SELECT auto_service_override FROM bot_users WHERE user_id = $1",
        int(user_id),
    )
    if val is None:
        return None
    return bool(val)


async def _log_decision(
    conn,
    *,
    user_id: int,
    direction: str,
    fiat_amount: int | None,
    decision: str,
    reason: str,
    shadow: bool,
) -> None:
    try:
        await conn.execute(
            """
            INSERT INTO auto_service_gate_log (
                user_id, direction, fiat_amount, decision, reason, shadow_mode
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            int(user_id),
            direction[:16],
            fiat_amount,
            decision[:32],
            (reason or "")[:128],
            shadow,
        )
    except Exception:
        logger.debug("auto_service_gate_log insert skipped (migration?)", exc_info=True)


async def resolve_no_shift_access(
    user_id: int,
    direction: str,
    fiat_amount: int | None,
    *,
    crypto: str | None = None,
    crypto_amount: float | None = None,
    conn=None,
    log: bool = True,
) -> NoShiftDecision:
    """Решение, можно ли обслужить заявку без полной смены операторов."""
    from operator_availability import has_operator_on_shift

    if await has_operator_on_shift():
        return NoShiftDecision("allow_shift", "on_shift")

    direction_l = (direction or "buy").strip().lower()
    if direction_l != "buy":
        return NoShiftDecision("block", "sell_requires_shift")

    shadow = auto_no_shift_shadow_mode()
    whitelist = auto_whitelist_user_ids()
    enabled = auto_no_shift_enabled()

    async def _eval(inner_conn) -> NoShiftDecision:
        override = await _user_override(inner_conn, user_id)
        if override is False:
            return NoShiftDecision("block", "user_override_off")

        fiat = int(fiat_amount or 0)
        max_rub = auto_no_shift_max_rub()
        if max_rub and fiat > max_rub:
            return NoShiftDecision("block", "amount_over_cap")

        eligible = False
        reason = "eligible"
        if override is True:
            eligible = True
            reason = "user_override_on"
        elif enabled:
            if whitelist and user_id not in whitelist:
                return NoShiftDecision("block", "not_whitelisted")
            paid = await buy_paid_count(inner_conn, user_id)
            if paid < auto_no_shift_min_buy_paid():
                return NoShiftDecision("block", "insufficient_paid_buys")
            eligible = True
        else:
            return NoShiftDecision("block", "auto_disabled")

        from auto_payout_guard import signer_circuit_closed

        if not await signer_circuit_closed(inner_conn):
            return NoShiftDecision("block", "signer_circuit_open")

        # Без смены выплату шлёт кошелёк проекта: сумма заявки не может быть
        # больше свободного остатка именно этой монеты.
        short = await buy_coin_fits(inner_conn, crypto, crypto_amount)
        if short is not None:
            return short

        if shadow:
            return NoShiftDecision("block", "shadow_would_auto", shadow=True)

        if eligible:
            return NoShiftDecision("allow_auto", reason)
        return NoShiftDecision("block", "auto_disabled")

    async def _safe_eval(inner_conn) -> NoShiftDecision:
        # Любая ошибка автопилота (неприменённая миграция, недоступная таблица)
        # должна возвращать прежнее поведение — блок, а не 500 на создании заявки.
        try:
            return await _eval(inner_conn)
        except Exception:
            logger.exception("auto_service_gate eval failed, falling back to block")
            return NoShiftDecision("block", "gate_error")

    # Без транзакции: сбой записи в журнал не должен ронять решение гейта.
    def _noted(decision: NoShiftDecision) -> NoShiftDecision:
        if decision.reason == "coin_short":
            logger.info(
                "auto no-shift coin short user=%s coin=%s need=%s spendable=%s reserved=%s",
                user_id,
                decision.coin,
                decision.need,
                decision.spendable,
                decision.reserved,
            )
        return decision

    if conn is not None:
        decision = await _safe_eval(conn)
        if log:
            await _log_decision(
                conn,
                user_id=user_id,
                direction=direction_l,
                fiat_amount=int(fiat_amount) if fiat_amount is not None else None,
                decision=decision.kind,
                reason=decision.reason,
                shadow=decision.shadow or shadow,
            )
        return _noted(decision)

    pool = await get_pool()
    async with pool.acquire() as acquired:
        decision = await _safe_eval(acquired)
        if log:
            await _log_decision(
                acquired,
                user_id=user_id,
                direction=direction_l,
                fiat_amount=int(fiat_amount) if fiat_amount is not None else None,
                decision=decision.kind,
                reason=decision.reason,
                shadow=decision.shadow or shadow,
            )
    if decision.kind == "allow_auto":
        logger.info(
            "auto no-shift allowed user=%s fiat=%s reason=%s",
            user_id,
            fiat_amount,
            decision.reason,
        )
    return _noted(decision)
