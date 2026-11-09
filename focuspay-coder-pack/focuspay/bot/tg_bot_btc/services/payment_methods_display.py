"""Публичные тарифы и условия для UI «Курсы»."""
from __future__ import annotations

from services import config_rates
from services.runtime_settings import (
    buy_spread_auto_tiers_from,
    get_settings_sync,
    min_withdraw_card_rub,
    sell_client_pct,
    sell_pricing_mode,
)
from services.buy_spread_tiers import buy_spread_auto_tiers_to_public, buy_spread_range_label


def public_tariffs_data() -> dict:
    s = get_settings_sync()
    lim = config_rates.MERCHANT_PAYIN_LIMITS
    pay_lim = lim.get("CARDRUB") or lim.get("SBPRUB") or {}
    min_buy = int(pay_lim.get("min_single") or 1000)
    max_buy = int(pay_lim.get("max_single") or 150000)
    sell_mode = sell_pricing_mode()
    sell_pct = round(sell_client_pct(), 1)
    sell_qr: dict = {
        "id": "sell_qr",
        "label": "Оплата по QR-коду",
        "pct": sell_pct,
        "mode": sell_mode,
    }
    if sell_mode == "markup":
        sell_qr["note"] = f"доплачиваем {sell_pct:g}% за вашу крипту"

    parsed = buy_spread_auto_tiers_from(s)
    tiers = buy_spread_auto_tiers_to_public(parsed)
    buy_crypto: dict = {
        "id": "buy_crypto",
        "label": "Покупка криптовалюты",
        "pct": round(float(tiers[0]["pct"] if tiers else s["buy_spread_auto_pct"]), 1),
    }
    if tiers:
        buy_crypto["tiers"] = tiers
        buy_crypto["pct_from"] = min(row["pct"] for row in tiers)
        buy_crypto["pct_to"] = max(row["pct"] for row in tiers)
        range_label = buy_spread_range_label(
            buy_spread_auto_tiers_from(s),
            fallback_pct=float(s["buy_spread_auto_pct"]),
        )
        if "–" in range_label:
            buy_crypto["note"] = range_label

    return {
        "commissions": [
            buy_crypto,
            sell_qr,
            {
                "id": "sell_atm",
                "label": "Выдача наличных через банкомат",
                "pct": round(float(config_rates.SELL_ATM_COMMISSION_PCT), 1),
            },
        ],
        "buy_spread_auto_tiers": tiers,
        "buy_limits": {
            "label": "СБП и карта",
            "min_fiat": min_buy,
            "max_fiat": max_buy,
        },
        "withdraw_limits": {
            "card_min_rub": min_withdraw_card_rub(),
            "crypto_min_usd_btc": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_BTC),
            "crypto_min_usd_ltc": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_LTC),
            "crypto_min_usd_trx": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_TRX),
            "crypto_min_usd_usdt": float(config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_USDT),
            "network_fee_card_rub": float(config_rates.CASINO_WITHDRAW_FEE_CARD_RUB),
            "network_fee_btc_usd": float(config_rates.CASINO_WITHDRAW_FEE_USD_BTC),
            "network_fee_ltc_usd": float(config_rates.CASINO_WITHDRAW_FEE_USD_LTC),
            "network_fee_trx_usd": float(config_rates.CASINO_WITHDRAW_FEE_USD_TRX),
            "network_fee_usdt_usd": float(config_rates.CRYPTO_NETWORK_FEE_USD_USDT),
        },
    }


async def public_tariffs_data_async() -> dict:
    from services.crypto_network_fee import withdraw_terms_snapshot

    data = public_tariffs_data()
    snap = await withdraw_terms_snapshot()
    wl = dict(data["withdraw_limits"])
    wl["usdt_rub"] = snap.get("usdt_rub")
    for coin in ("btc", "ltc", "trx", "usdt"):
        rub = (snap.get("mins") or {}).get(coin, {}).get("rub")
        if rub is not None:
            wl[f"crypto_min_rub_{coin}"] = rub
    fees = snap.get("fees") or {}
    for coin in ("btc", "ltc", "trx", "usdt"):
        fee_rub = (fees.get(coin) or {}).get("rub")
        if fee_rub is not None:
            wl[f"network_fee_{coin}_rub"] = fee_rub
    data["withdraw_limits"] = wl
    data["withdraw_terms"] = snap
    return data


def payment_methods_data() -> list[dict]:
    """Совместимость API: плоский список не используется, см. public_tariffs_data."""
    return []


def _fmt_rub(n: int) -> str:
    return f"{n:,} ₽".replace(",", " ")


def _fmt_rub_range(min_fiat: int, max_fiat: int) -> str:
    return f"{_fmt_rub(min_fiat)}–{_fmt_rub(max_fiat)}"


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "временно недоступен"
    if value >= 1000:
        return f"{value:,.0f} ₽".replace(",", " ")
    if value >= 1:
        return f"{value:,.2f} ₽".replace(",", " ")
    return f"{value:.4f} ₽"


async def build_rates_message_html() -> str:
    from services.rates_api import (
        USER_RATES_UNAVAILABLE,
        RatesUnavailableError,
        get_cached_rate,
        ensure_rates_cache,
    )
    from services.tg_emoji import e
    from services.ux_copy import txt_rates

    try:
        await ensure_rates_cache()
    except RatesUnavailableError:
        return f"<b>{USER_RATES_UNAVAILABLE}</b>"

    rate_lines = []
    for crypto, label in (
        ("btc", "BTC"),
        ("usdt", "USDT"),
        ("trx", "TRX"),
        ("ltc", "LTC"),
    ):
        buy = get_cached_rate(crypto, "buy")
        sell = get_cached_rate(crypto, "sell")
        rate_lines.append(
            f"{e(crypto)} {label} — покупка {_fmt_price(buy)}, продажа {_fmt_price(sell)}"
        )

    site = (getattr(config_rates, "PUBLIC_SITE_URL", None) or "https://focuspay.org").rstrip("/")
    site_label = site.replace("https://", "")

    t = public_tariffs_data()
    bl = t["buy_limits"]
    limits_line = (
        f"Лимиты: {_fmt_rub_range(bl['min_fiat'], bl['max_fiat'])} ({bl['label']})"
    )

    from services.crypto_network_fee import format_withdraw_terms_html

    terms = await format_withdraw_terms_html(compact=False)
    return txt_rates(
        rate_lines=rate_lines,
        limits_line=limits_line,
        site=site_label,
        withdraw_block=terms,
    )
