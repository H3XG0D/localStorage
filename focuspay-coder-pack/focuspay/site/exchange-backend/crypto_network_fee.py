"""Комиссия сети и минимумы вывода баланса по монетам."""
from __future__ import annotations

from decimal import Decimal

from config import settings

_CRYPTO_STEP = {
    "usdt": Decimal("0.01"),
    "btc": Decimal("0.00000001"),
    "ltc": Decimal("0.00000001"),
    "trx": Decimal("0.0001"),
}


def _base_crypto(crypto: str) -> str:
    return (crypto or "").split("_")[0].lower()


def _fmt_rub_int(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", " ")


def _fmt_rub_amount(n: float) -> str:
    if abs(n - round(n)) < 0.01:
        return _fmt_rub_int(n)
    return f"{n:,.2f}".replace(",", " ")


def min_withdraw_usd(crypto: str) -> float:
    base = _base_crypto(crypto)
    if base == "usdt":
        return float(settings.user_referral_min_withdraw_crypto_usd_usdt)
    if base == "btc":
        return float(settings.user_referral_min_withdraw_crypto_usd_btc)
    if base == "ltc":
        return float(settings.user_referral_min_withdraw_crypto_usd_ltc)
    if base == "trx":
        return float(settings.user_referral_min_withdraw_crypto_usd_trx)
    return float(settings.user_referral_min_withdraw_crypto_usd)


def card_withdraw_fee_rub() -> float:
    return round(float(settings.casino_withdraw_fee_card_rub), 2)


def network_fee_usd(crypto: str) -> float:
    base = _base_crypto(crypto)
    if base == "btc":
        return float(settings.casino_withdraw_fee_usd_btc)
    if base == "ltc":
        return float(settings.casino_withdraw_fee_usd_ltc)
    if base == "trx":
        return float(settings.casino_withdraw_fee_usd_trx)
    if base == "usdt":
        return float(settings.crypto_network_fee_usd_usdt)
    return 0.0


def network_fee_rub(crypto: str, *, usdt_rub: float) -> float:
    usd = network_fee_usd(crypto)
    if usd <= 0:
        return 0.0
    return round(usd * float(usdt_rub or 0), 2)


def withdraw_network_fee_rub(crypto: str, *, usdt_rub: float) -> float:
    return network_fee_rub(crypto, usdt_rub=usdt_rub)


def payout_from_fee(amount_rub: float, fee_rub: float) -> float:
    return max(0.0, round(float(amount_rub) - float(fee_rub), 2))


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def withdraw_payout_rub(
    *,
    amount_rub: float | None = None,
    payout_amount_rub: float | None = None,
    network_fee_rub: float | None = None,
) -> float:
    stored = _as_float(payout_amount_rub)
    if stored is not None:
        return stored
    return payout_from_fee(float(amount_rub or 0), float(network_fee_rub or 0))


def quote_withdraw_crypto(
    *,
    method: str | None = None,
    crypto: str | None = None,
    amount_rub: float | None = None,
    payout_amount_rub: float | None = None,
    network_fee_rub: float | None = None,
    rates: dict | None = None,
) -> dict[str, float | None]:
    """Live RUB→coin amount to send. Card / missing rate → null crypto amount."""
    empty: dict[str, float | None] = {"payout_crypto_amount": None, "rate_rub": None}
    if (method or "").strip().lower() != "crypto":
        return empty
    coin = _base_crypto(crypto or "")
    if not coin:
        return empty
    rate = _as_float((rates or {}).get(coin))
    if rate is None or rate <= 0:
        return empty
    payout = withdraw_payout_rub(
        amount_rub=amount_rub,
        payout_amount_rub=payout_amount_rub,
        network_fee_rub=network_fee_rub,
    )
    try:
        rate_dec = Decimal(str(rate))
        step = _CRYPTO_STEP.get(coin, _CRYPTO_STEP["usdt"])
        amount = float((Decimal(str(payout)) / rate_dec).quantize(step))
    except (ValueError, ArithmeticError, Exception):
        return {"payout_crypto_amount": None, "rate_rub": float(rate)}
    return {"payout_crypto_amount": amount, "rate_rub": float(rate)}


def payout_amount_rub(amount_rub: float, crypto: str, *, usdt_rub: float) -> float:
    fee = withdraw_network_fee_rub(crypto, usdt_rub=usdt_rub)
    return payout_from_fee(amount_rub, fee)


def casino_withdraw_fee_rub(
    method: str,
    crypto: str | None = None,
    *,
    usdt_rub: float | None,
) -> float:
    """Card is ₽; BTC/LTC/TRX/USDT are $ converted at USDT/RUB."""
    kind = (method or "").strip().lower()
    if kind == "card":
        return card_withdraw_fee_rub()
    return network_fee_rub(crypto or "", usdt_rub=float(usdt_rub or 0))


def withdraw_fee_rub(
    method: str,
    crypto: str | None = None,
    *,
    usdt_rub: float | None,
    source: str | None = None,
) -> float:
    """source kept for call sites; casino and balance use the same table."""
    _ = source
    return casino_withdraw_fee_rub(method, crypto, usdt_rub=usdt_rub)


def format_crypto_withdraw_limits(crypto: str) -> str:
    return f"${min_withdraw_usd(crypto):g}"


def _min_rub_for_crypto(crypto: str, usdt_rub: float | None) -> float | None:
    if usdt_rub is None or usdt_rub <= 0:
        return None
    return round(min_withdraw_usd(crypto) * float(usdt_rub), 2)


def _fee_parts(crypto: str, usdt_rub: float | None) -> dict:
    usd = network_fee_usd(crypto)
    rub = (
        round(usd * float(usdt_rub), 2)
        if usdt_rub is not None and usdt_rub > 0 and usd > 0
        else None
    )
    return {"usd": usd, "rub": rub}


async def resolve_usdt_rub() -> float:
    from routers.public import get_rates_cached

    market = await get_rates_cached()
    usdt_rub = market.get("usdt")
    if not usdt_rub:
        raise ValueError("Курс временно недоступен")
    return float(usdt_rub)


async def min_crypto_amount_rub(crypto: str) -> float:
    return min_withdraw_usd(crypto) * await resolve_usdt_rub()


async def withdraw_terms_snapshot() -> dict:
    usdt_rub: float | None = None
    try:
        usdt_rub = await resolve_usdt_rub()
    except ValueError:
        pass

    from runtime_settings import min_withdraw_card_rub

    return {
        "usdt_rub": usdt_rub,
        "card_min_rub": min_withdraw_card_rub(),
        "mins": {
            "btc": {
                "usd": float(settings.user_referral_min_withdraw_crypto_usd_btc),
                "rub": _min_rub_for_crypto("btc", usdt_rub),
            },
            "ltc": {
                "usd": float(settings.user_referral_min_withdraw_crypto_usd_ltc),
                "rub": _min_rub_for_crypto("ltc", usdt_rub),
            },
            "trx": {
                "usd": float(settings.user_referral_min_withdraw_crypto_usd_trx),
                "rub": _min_rub_for_crypto("trx", usdt_rub),
            },
            "usdt": {
                "usd": float(settings.user_referral_min_withdraw_crypto_usd_usdt),
                "rub": _min_rub_for_crypto("usdt", usdt_rub),
            },
        },
        "fees": {
            "card": {"rub": card_withdraw_fee_rub()},
            "btc": _fee_parts("btc", usdt_rub),
            "ltc": _fee_parts("ltc", usdt_rub),
            "trx": _fee_parts("trx", usdt_rub),
            "usdt": _fee_parts("usdt", usdt_rub),
        },
    }
