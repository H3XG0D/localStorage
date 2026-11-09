"""Публичные тарифы и условия для API и сайта."""
from __future__ import annotations

from config import settings
from runtime_settings import (
    buy_spread_auto_tiers_from,
    get_settings_sync,
    min_withdraw_card_rub,
    sell_client_pct,
    sell_pricing_mode,
)
from buy_spread_tiers import buy_spread_auto_tiers_to_public, buy_spread_range_label


def public_tariffs_data() -> dict:
    s = get_settings_sync()
    lim = settings.merchant_payin_limits
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
    buy_pct = round(float(tiers[0]["pct"] if tiers else s["buy_spread_auto_pct"]), 1)
    buy_crypto: dict = {
        "id": "buy_crypto",
        "label": "Покупка криптовалюты",
        "pct": buy_pct,
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
                "pct": round(float(settings.sell_atm_commission_pct), 1),
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
            "crypto_min_usd_btc": float(settings.user_referral_min_withdraw_crypto_usd_btc),
            "crypto_min_usd_ltc": float(settings.user_referral_min_withdraw_crypto_usd_ltc),
            "crypto_min_usd_trx": float(settings.user_referral_min_withdraw_crypto_usd_trx),
            "crypto_min_usd_usdt": float(settings.user_referral_min_withdraw_crypto_usd_usdt),
            "network_fee_card_rub": float(settings.casino_withdraw_fee_card_rub),
            "network_fee_btc_usd": float(settings.casino_withdraw_fee_usd_btc),
            "network_fee_ltc_usd": float(settings.casino_withdraw_fee_usd_ltc),
            "network_fee_trx_usd": float(settings.casino_withdraw_fee_usd_trx),
            "network_fee_usdt_usd": float(settings.crypto_network_fee_usd_usdt),
        },
    }


async def public_tariffs_data_async() -> dict:
    from crypto_network_fee import withdraw_terms_snapshot

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
    return []
