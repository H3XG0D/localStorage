"""Промо-бонус к выплате (как в tg_bot_btc/services/promo_bonus.py)."""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

CRYPTO_DECIMALS = {
    "btc": 8,
    "usdt": 6,
    "trx": 6,
    "ltc": 8,
}


def apply_fixed_rub_bonus(
    direction: str,
    crypto_amount: Decimal,
    fiat_amount: Decimal,
    bonus_rub: Decimal,
    crypto: str,
    rate: Decimal,
) -> tuple[Decimal, Decimal]:
    bonus_rub = Decimal(str(bonus_rub))
    if bonus_rub <= 0:
        return crypto_amount, fiat_amount

    crypto_key = crypto.split("_")[0].lower()
    direction = (direction or "").lower()

    if direction == "buy":
        r = Decimal(str(rate)) if rate and rate > 0 else Decimal("0")
        if r <= 0:
            return crypto_amount, fiat_amount
        decimals = CRYPTO_DECIMALS.get(crypto_key, 8)
        q = Decimal("1") / (Decimal(10) ** decimals)
        extra_crypto = (bonus_rub / r).quantize(q, rounding=ROUND_DOWN)
        return crypto_amount + extra_crypto, fiat_amount

    boosted_fiat = (fiat_amount + bonus_rub).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return crypto_amount, boosted_fiat
