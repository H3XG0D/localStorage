"""Комиссия сети и минимумы вывода баланса по монетам."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from services import config_rates
from services.runtime_settings import min_withdraw_card_rub
from services.rates_api import get_market_price


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
        return float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_USDT)
    if base == "btc":
        return float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_BTC)
    if base == "ltc":
        return float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_LTC)
    if base == "trx":
        return float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_TRX)
    return float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD)


def card_withdraw_fee_rub() -> float:
    return round(float(config_rates.CASINO_WITHDRAW_FEE_CARD_RUB), 2)


def network_fee_usd(crypto: str) -> float:
    base = _base_crypto(crypto)
    if base == "btc":
        return float(config_rates.CASINO_WITHDRAW_FEE_USD_BTC)
    if base == "ltc":
        return float(config_rates.CASINO_WITHDRAW_FEE_USD_LTC)
    if base == "trx":
        return float(config_rates.CASINO_WITHDRAW_FEE_USD_TRX)
    if base == "usdt":
        return float(config_rates.CRYPTO_NETWORK_FEE_USD_USDT)
    return 0.0


def network_fee_rub(crypto: str, *, usdt_rub: float) -> float:
    usd = network_fee_usd(crypto)
    if usd <= 0:
        return 0.0
    return round(usd * float(usdt_rub or 0), 2)


def withdraw_network_fee_rub(crypto: str, *, usdt_rub: float) -> float:
    return network_fee_rub(crypto, usdt_rub=usdt_rub)


def buy_network_fee_rub(crypto: str, *, usdt_rub: float) -> float:
    return network_fee_rub(crypto, usdt_rub=usdt_rub)


def buy_client_send_fee_usd() -> float:
    return float(config_rates.CRYPTO_NETWORK_FEE_USD_USDT)


def buy_client_send_fee_rub(crypto: str, *, usdt_rub: float) -> float:
    """Фиксированные $ за отправку, только покупка USDT (к оплате в ₽)."""
    if _base_crypto(crypto) != "usdt":
        return 0.0
    rate = float(usdt_rub or 0)
    if rate <= 0:
        return 0.0
    return round(buy_client_send_fee_usd() * rate, 2)


def btc_send_surcharge_rub(
    fee_rate_sat_vb: float | None,
    *,
    btc_rub: float,
    order_rub: float,
) -> float:
    """Превышение порога sat/vB в ₽: до порога отправку оплачивает компания.

    Считается в момент котировки — сумма к оплате фиксируется вместе с реквизитами,
    и добрать разницу после оплаты уже нельзя.
    """
    rate = float(fee_rate_sat_vb or 0)
    free = float(config_rates.BUY_BTC_FEE_FREE_SAT_VB)
    price = float(btc_rub or 0)
    if rate <= free or price <= 0:
        return 0.0
    sats = (rate - free) * int(config_rates.BUY_BTC_FEE_VSIZE)
    fee = sats / 1e8 * price
    fee *= 1 + float(config_rates.BUY_BTC_FEE_BUFFER_PCT) / 100
    cap_pct = float(config_rates.BUY_BTC_FEE_MAX_PCT_OF_ORDER)
    if cap_pct > 0 and order_rub > 0:
        fee = min(fee, float(order_rub) * cap_pct / 100)
    return round(fee, 2)


def buy_btc_send_fee_rub(
    crypto: str,
    *,
    btc_rub: float,
    order_rub: float,
    fee_rate_sat_vb: float | None,
) -> float:
    if _base_crypto(crypto) != "btc":
        return 0.0
    return btc_send_surcharge_rub(
        fee_rate_sat_vb, btc_rub=btc_rub, order_rub=order_rub
    )


def apply_buy_client_send_fee(
    fiat_amount,
    crypto: str,
    *,
    usdt_rub: float,
    btc_fee_rate_sat_vb: float | None = None,
):
    """Прибавить send-fee к оплате. Крипта не меняется. (fiat_with_fee, fee_rub).

    `usdt_rub` для USDT — курс USDT/RUB, для BTC сюда приходит курс BTC/RUB
    (вызывающий передаёт рыночную цену выбранной монеты).
    """
    fee = buy_client_send_fee_rub(crypto, usdt_rub=usdt_rub)
    if fee <= 0 and btc_fee_rate_sat_vb is not None:
        fee = buy_btc_send_fee_rub(
            crypto,
            btc_rub=usdt_rub,
            order_rub=float(fiat_amount),
            fee_rate_sat_vb=btc_fee_rate_sat_vb,
        )
    if fee <= 0:
        return fiat_amount, 0.0
    if isinstance(fiat_amount, Decimal):
        new_fiat = (fiat_amount + Decimal(str(fee))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return new_fiat, fee
    return round(float(fiat_amount) + fee, 2), fee


def format_usdt_buy_send_fee_html(*, fee_rub: float | None = None) -> str:
    usd = buy_client_send_fee_usd()
    if fee_rub is not None and float(fee_rub) > 0:
        return (
            f"Комиссия за отправку USDT: <b>${usd:g}</b> "
            f"(≈{_fmt_rub_amount(float(fee_rub))} ₽) — добавляется к оплате."
        )
    return (
        f"Комиссия за отправку USDT: <b>${usd:g}</b> — "
        f"добавляется к оплате при покупке."
    )


def payout_from_fee(amount_rub: float, fee_rub: float) -> float:
    return max(0.0, round(float(amount_rub) - float(fee_rub), 2))


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


def network_fee_applies(crypto: str) -> bool:
    return network_fee_usd(crypto) > 0


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


async def withdraw_terms_snapshot() -> dict:
    """Снимок лимитов и комиссий для UI (курс USDT опционален)."""
    usdt_rub: float | None = None
    try:
        usdt_rub = await resolve_usdt_rub()
    except ValueError:
        pass

    return {
        "usdt_rub": usdt_rub,
        "card_min_rub": min_withdraw_card_rub(),
        "mins": {
            "btc": {"usd": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_BTC), "rub": _min_rub_for_crypto("btc", usdt_rub)},
            "ltc": {"usd": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_LTC), "rub": _min_rub_for_crypto("ltc", usdt_rub)},
            "trx": {"usd": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_TRX), "rub": _min_rub_for_crypto("trx", usdt_rub)},
            "usdt": {"usd": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_USDT), "rub": _min_rub_for_crypto("usdt", usdt_rub)},
        },
        "fees": {
            "card": {"rub": card_withdraw_fee_rub()},
            "btc": _fee_parts("btc", usdt_rub),
            "ltc": _fee_parts("ltc", usdt_rub),
            "trx": _fee_parts("trx", usdt_rub),
            "usdt": _fee_parts("usdt", usdt_rub),
        },
    }


def _fmt_usd_fee_line(usd: float, rub: float | None) -> str:
    if rub is not None and rub > 0:
        return f"${usd:g} (≈{_fmt_rub_amount(rub)} ₽)"
    return f"${usd:g}"


async def format_withdraw_terms_html(*, compact: bool = False) -> str:
    from services.ux_copy import txt_withdraw_terms

    snap = await withdraw_terms_snapshot()
    card = snap["card_min_rub"]
    mins = snap["mins"]
    fees = snap["fees"]

    min_btc = f"от ${mins['btc']['usd']:g}"
    if mins["btc"]["rub"]:
        min_btc += f" (≈{_fmt_rub_int(mins['btc']['rub'])} ₽)"
    min_usdt = f"от ${mins['usdt']['usd']:g}"
    if mins["usdt"]["rub"]:
        min_usdt += f" (≈{_fmt_rub_int(mins['usdt']['rub'])} ₽)"

    fee_card = f"{_fmt_rub_amount(fees['card']['rub'])} ₽"
    fee_crypto = _fmt_usd_fee_line(fees["btc"]["usd"], fees["btc"]["rub"])
    fee_usdt = _fmt_usd_fee_line(fees["usdt"]["usd"], fees["usdt"]["rub"])

    return txt_withdraw_terms(
        card_min=card,
        min_btc_line=min_btc,
        min_usdt_line=min_usdt,
        fee_card=fee_card,
        fee_crypto=fee_crypto,
        fee_usdt=fee_usdt,
        compact=compact,
    )


def format_crypto_fee_hint_html(crypto: str, *, usdt_rub: float) -> str:
    """Краткая подсказка по комиссии для выбранной монеты."""
    base = _base_crypto(crypto)
    fee = withdraw_network_fee_rub(crypto, usdt_rub=usdt_rub)
    min_rub = min_withdraw_usd(crypto) * usdt_rub
    label = base.upper()
    usd = network_fee_usd(crypto)
    if usd > 0:
        return (
            f"Минимум для {label}: ≈{_fmt_rub_int(min_rub)} ₽ (${min_withdraw_usd(crypto):g}). "
            f"Комиссия сети: {_fmt_usd_fee_line(usd, fee)} — удерживается с суммы вывода."
        )
    return f"Минимум для {label}: ≈{_fmt_rub_int(min_rub)} ₽ (${min_withdraw_usd(crypto):g})."


async def min_crypto_amount_rub(crypto: str) -> float:
    """Минимум вывода в ₽: $N по курсу USDT/RUB."""
    usdt_rub, _, blocked = await get_market_price("usdt")
    if blocked or not usdt_rub:
        raise ValueError("Курс временно недоступен")
    return min_withdraw_usd(crypto) * float(usdt_rub)


async def resolve_usdt_rub() -> float:
    usdt_rub, _, blocked = await get_market_price("usdt")
    if blocked or not usdt_rub:
        raise ValueError("Курс временно недоступен")
    return float(usdt_rub)
