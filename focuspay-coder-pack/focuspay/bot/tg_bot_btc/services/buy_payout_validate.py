"""Согласованность крипты с оплаченными рублями (создание заявки и выплата)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN

from services.service_profit import buy_markup


def expected_crypto_for_paid_rub(
    *,
    fiat_amount: float,
    rate: float,
    crypto: str,
    cashback_applied_rub: float = 0,
    exchange_discount_applied_rub: float = 0,
) -> float | None:
    """Крипта, соответствующая payin + списанному кешбэку и скидке на обмен.

    В ордере rate уже = market × buy_markup (как в rates_api / order_service),
    поэтому крипта = (fiat + cashback + discount) / rate — без повторного × markup.
    """
    fiat = float(fiat_amount or 0)
    rate_f = float(rate or 0)
    if fiat <= 0 or rate_f <= 0:
        return None
    cb = max(0.0, float(cashback_applied_rub or 0))
    disc = max(0.0, float(exchange_discount_applied_rub or 0))
    # buy_markup(crypto) — sanity, что наценка сконфигурирована; в формулу не входит.
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
    """Не больше крипты, чем покрывают оплаченные рубли."""
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


def validate_buy_payout_crypto(order: dict) -> tuple[bool, str | None]:
    crypto_out = float(order.get("crypto_amount") or 0)
    if crypto_out <= 0:
        return False, "invalid_crypto_amount"
    # Никакого процентного допуска при выплате.
    cap = max_crypto_for_paid_rub(order, tolerance=0)
    if cap is None:
        return True, None
    # Карточка выплаты представляет крипту с 8 знаками. Округление вверх
    # последнего знака не является переплатой (например, 0.60472271595 →
    # 0.60472272). Сравниваем с округлённым пределом, НЕ округляя саму
    # выплату: лишняя единица точности должна по-прежнему блокироваться.
    # Decimal из исходных полей исключает float-шум при расчёте предела.
    paid = (
        Decimal(str(order.get("fiat_amount") or 0))
        + max(Decimal(0), Decimal(str(order.get("cashback_applied_rub") or 0)))
        + max(Decimal(0), Decimal(str(order.get("exchange_discount_applied_rub") or 0)))
    )
    exact_cap = paid / Decimal(str(order["rate"]))
    rounded_cap = exact_cap.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN)
    # Не запрещаем сохранённые неокруглённые суммы, когда округление вниз.
    allowed_cap = max(exact_cap, rounded_cap)
    if Decimal(str(order.get("crypto_amount") or 0)) > allowed_cap + Decimal("1e-12"):
        return False, "crypto_exceeds_paid"
    return True, None
