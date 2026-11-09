"""Единая оценка прибыли сервиса по одной сделке (синхронно с exchange/backend/service_profit.py).

BUY (пример buy_markup=1.20, оплата 12 000 ₽, крипта на ~10 000 ₽ по рынку):
  валовая маржа = оплата − себестоимость крипты;
  комиссия мерчанта (карт) = card_fee_pct × сумма, ушедшая в payin (не от «базы»);
  чистая ≈ маржа − комиссия мерчанта − списанный кешбэк.
SELL: fiat × (1/sell_multiplier − 1); в режиме скидки ещё × sell_profit_factor
"""
from services.runtime_settings import (
    buy_markup as _buy_markup_factor,
    card_fee_pct as rs_card_fee_pct,
    is_manual_card_fee,
    sell_discount,
    sell_pricing_mode,
    sell_profit_factor,
)


def base_crypto(crypto: str) -> str:
    return (crypto or "").split("_")[0].lower()


def buy_markup(crypto: str, *, manual: bool | None = None, card_fee: float | None = None) -> float:
    del crypto  # global spreads for all coins
    if manual is None:
        manual = is_manual_card_fee(card_fee)
    return _buy_markup_factor(manual=manual)


def buy_gross_margin_rub(
    total_fiat: float,
    crypto: str,
    *,
    crypto_amount: float = 0,
    rate: float = 0,
    card_fee: float | None = None,
    clamp: bool = True,
) -> float:
    """Маржа от наценки: total_fiat − crypto×рыночный курс (или total × (1 − 1/markup))."""
    fiat = float(total_fiat or 0)
    if fiat <= 0:
        return 0.0
    markup = buy_markup(crypto, card_fee=card_fee)
    if crypto_amount and rate and float(crypto_amount) > 0 and float(rate) > 0 and markup > 0:
        market_rate = float(rate) / markup
        cost = float(crypto_amount) * market_rate
        diff = fiat - cost
        return max(0.0, diff) if clamp else diff
    if markup <= 1:
        return 0.0
    return fiat * (1.0 - 1.0 / markup)


def order_service_profit(
    direction: str,
    crypto: str,
    fiat_amount: float,
    crypto_amount: float = 0,
    rate: float = 0,
    *,
    cashback_applied_rub: float = 0,
    card_fee_pct: float | None = None,
    clamp: bool = True,
) -> float:
    """Чистая прибыль сервиса по сделке.

    BUY: валовая маржа (оплата − себестоимость крипты) − комиссия мерчанта − кешбэк.
    SELL: fiat × (1/sell_multiplier − 1); в режиме скидки ещё × sell_profit_factor.

    clamp=True — для комиссий: убыток как 0. clamp=False — реальный минус для P&L/админки.
    """
    fiat = float(fiat_amount or 0)
    direction = (direction or "").lower()

    if fiat <= 0:
        return 0.0

    if direction == "buy":
        cb = max(0.0, float(cashback_applied_rub or 0))
        payin_fiat = fiat
        total_fiat = payin_fiat + cb
        fee = card_fee_pct if card_fee_pct is not None else rs_card_fee_pct(manual=False)
        gross = buy_gross_margin_rub(
            total_fiat,
            crypto,
            crypto_amount=crypto_amount,
            rate=rate,
            card_fee=card_fee_pct,
            clamp=clamp,
        )
        merchant_fee = payin_fiat * fee
        net = gross - merchant_fee - cb
        return max(0.0, net) if clamp else net

    multiplier = sell_discount()
    if multiplier <= 0:
        return 0.0
    gross = fiat * (1.0 / multiplier - 1.0)
    profit = gross if sell_pricing_mode() == "markup" else gross * sell_profit_factor()
    return max(0.0, profit) if clamp else profit


CARD_FEE_DEFAULT = rs_card_fee_pct(manual=False)
