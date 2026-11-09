"""Согласованность крипты с payin (дублирует tg_bot_btc/services/buy_payout_validate.py)."""
from __future__ import annotations

from service_profit import buy_markup


def expected_crypto_for_paid_rub(
    *,
    fiat_amount: float,
    rate: float,
    crypto: str,
    cashback_applied_rub: float = 0,
    exchange_discount_applied_rub: float = 0,
) -> float | None:
    """Крипта за payin+cashback+discount.

    order.rate уже market×buy_markup — без повторного × markup.
    """
    fiat = float(fiat_amount or 0)
    rate_f = float(rate or 0)
    if fiat <= 0 or rate_f <= 0:
        return None
    cb = max(0.0, float(cashback_applied_rub or 0))
    disc = max(0.0, float(exchange_discount_applied_rub or 0))
    if buy_markup(crypto) <= 0:
        return None
    return (fiat + cb + disc) / rate_f


def max_crypto_for_paid_rub(order: dict, *, tolerance: float = 0.02) -> float | None:
    exp = expected_crypto_for_paid_rub(
        fiat_amount=float(order.get("fiat_amount") or 0),
        rate=float(order.get("rate") or 0),
        crypto=str(order.get("crypto") or ""),
        cashback_applied_rub=float(order.get("cashback_applied_rub") or 0),
        exchange_discount_applied_rub=float(order.get("exchange_discount_applied_rub") or 0),
    )
    if exp is None:
        return None
    return exp * (1.0 + tolerance)


def clamp_buy_crypto_amount(
    crypto_amount: float,
    *,
    fiat_amount: float,
    rate: float,
    crypto: str,
    cashback_applied_rub: float = 0,
    exchange_discount_applied_rub: float = 0,
    lock_crypto: bool = False,
) -> float:
    out = float(crypto_amount or 0)
    if lock_crypto:
        return out
    cap = max_crypto_for_paid_rub(
        {
            "fiat_amount": fiat_amount,
            "rate": rate,
            "crypto": crypto,
            "cashback_applied_rub": cashback_applied_rub,
            "exchange_discount_applied_rub": exchange_discount_applied_rub,
        },
        tolerance=0,
    )
    if cap is not None and out > cap:
        return cap
    return out
