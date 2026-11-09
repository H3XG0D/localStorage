from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from services.templates import CRYPTO_DECIMALS


def apply_fixed_rub_bonus(
    direction: str,
    crypto_amount: Decimal,
    fiat_amount: Decimal,
    bonus_rub: Decimal,
    crypto: str,
    rate: Decimal,
) -> tuple[Decimal, Decimal]:
    """
    Одноразовый бонус в рублях к выплате клиенту.
    BUY: больше крипты (fiat оплаты без изменений).
    SELL: больше рублей (crypto депозита без изменений).
    """
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


def promo_bonus_note(
    *,
    bonus_percent: float | None = None,
    bonus_fixed_rub: float | None = None,
) -> str:
    if bonus_fixed_rub and float(bonus_fixed_rub) > 0:
        return f"🎁 Промо-бонус +{float(bonus_fixed_rub):,.0f} ₽ к выплате"
    if bonus_percent and float(bonus_percent) > 0:
        return f"🎁 Промо-бонус +{float(bonus_percent):g}% к выплате"
    return ""
