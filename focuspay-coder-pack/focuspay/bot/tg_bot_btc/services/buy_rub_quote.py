"""BUY quote when the client types a RUB base (how much crypto they need)."""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

CRYPTO_Q = Decimal("0.00000001")


def quote_buy_rub_base(
    *,
    base_fiat: Decimal,
    rapira: Decimal,
    coingecko: Decimal,
    markup: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Крипта по CoinGecko, оплата по Rapira × markup.

    Returns (crypto_amount, pay_fiat, rate) where rate = rapira × markup.
    pay is rounded UP to a whole ruble so clamp(pay/rate) cannot cut crypto.
    """
    if base_fiat <= 0 or rapira <= 0 or coingecko <= 0 or markup <= 0:
        raise ValueError("invalid buy RUB quote inputs")
    crypto_amt = (base_fiat / coingecko).quantize(CRYPTO_Q, rounding=ROUND_HALF_UP)
    rate = rapira * markup
    pay = (crypto_amt * rate).quantize(Decimal("1"), rounding=ROUND_CEILING)
    return crypto_amt, pay, rate
