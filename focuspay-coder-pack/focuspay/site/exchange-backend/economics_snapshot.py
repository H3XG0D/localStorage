"""Immutable pricing and profit snapshot stored with each order."""
from __future__ import annotations

import json
from typing import Any, Mapping

from runtime_settings import (
    buy_markup,
    card_fee_pct,
    sell_client_pct,
    sell_discount,
    sell_pricing_mode,
    sell_profit_factor,
)

FORMULA_VERSION = "pricing_snapshot_v1"
FORMULA_VERSION_V2 = "pricing_snapshot_v2"
LEGACY_LOCKED_VERSION = "legacy_locked_v1"


def _as_snapshot(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return dict(value) if isinstance(value, Mapping) else None


def build_economics_snapshot(
    direction: str,
    crypto: str,
    fiat_amount: float,
    crypto_amount: float,
    rate: float,
    *,
    cashback_applied_rub: float = 0,
    card_fee: float | None = None,
    manual_buy: bool = False,
    buy_markup_override: float | None = None,
    formula_version: str = FORMULA_VERSION,
    triangle_subsidy_rub: float = 0,
) -> dict[str, Any]:
    """Capture every mutable tariff used to value an order at quote time."""
    del crypto
    direction = (direction or "").lower()
    fiat = float(fiat_amount or 0)
    crypto_qty = float(crypto_amount or 0)
    quote_rate = float(rate or 0)
    cashback = max(0.0, float(cashback_applied_rub or 0))
    subsidy = max(0.0, float(triangle_subsidy_rub or 0))

    if direction == "buy":
        markup = float(
            buy_markup_override
            if buy_markup_override is not None
            else buy_markup(manual=manual_buy)
        )
        fee = float(card_fee if card_fee is not None else card_fee_pct(manual=manual_buy))
        market_rate = quote_rate / markup if markup > 0 else 0.0
        gross = fiat + cashback - crypto_qty * market_rate
        merchant_fee = fiat * fee
        return {
            "formula_version": formula_version,
            "direction": "buy",
            "buy_markup": markup,
            "market_rate": market_rate,
            "card_fee_pct": fee,
            "cashback_applied_rub": cashback,
            "gross_margin_rub": gross,
            "merchant_fee_rub": merchant_fee,
            "triangle_subsidy_rub": subsidy,
            "service_profit_rub": gross - merchant_fee - cashback - subsidy,
        }

    multiplier = float(sell_discount())
    factor = float(sell_profit_factor())
    gross = fiat * (1.0 / multiplier - 1.0) if multiplier > 0 else 0.0
    mode = sell_pricing_mode()
    if mode == "markup":
        return {
            "formula_version": FORMULA_VERSION_V2,
            "direction": "sell",
            "sell_pricing_mode": "markup",
            "sell_multiplier": multiplier,
            "sell_discount": multiplier,
            "sell_markup_pct": float(sell_client_pct()),
            "sell_profit_factor": 1.0,
            "gross_margin_rub": gross,
            "merchant_fee_rub": 0.0,
            "cashback_applied_rub": 0.0,
            "service_profit_rub": gross,
        }
    return {
        "formula_version": formula_version,
        "direction": "sell",
        "sell_pricing_mode": "discount",
        "sell_discount": multiplier,
        "sell_profit_factor": factor,
        "gross_margin_rub": gross,
        "merchant_fee_rub": 0.0,
        "cashback_applied_rub": 0.0,
        "service_profit_rub": gross * factor,
    }


def snapshot_economics(snapshot: object, *, clamp: bool = True) -> dict[str, float] | None:
    """Read a persisted snapshot without consulting current runtime settings."""
    data = _as_snapshot(snapshot)
    if not data or "service_profit_rub" not in data:
        return None
    profit = float(data["service_profit_rub"] or 0)
    return {
        "gross_margin_rub": float(data.get("gross_margin_rub") or 0),
        "merchant_fee_rub": float(data.get("merchant_fee_rub") or 0),
        "service_profit_rub": max(0.0, profit) if clamp else profit,
    }


def order_economics(order: Mapping[str, Any], *, clamp: bool = True) -> dict[str, float]:
    """Value a persisted order, using live tariffs only for legacy rows."""
    snapshot = snapshot_economics(order.get("economics_snapshot"), clamp=clamp)
    if snapshot is not None:
        return snapshot

    from service_profit import buy_gross_margin_rub, order_service_profit

    direction = str(order.get("direction") or "").lower()
    fiat = float(order.get("fiat_amount") or 0)
    crypto = str(order.get("crypto") or "")
    crypto_amount = float(order.get("crypto_amount") or 0)
    rate = float(order.get("rate") or 0)
    cashback = float(order.get("cashback_applied_rub") or 0)
    raw_fee = order.get("card_fee_pct")
    fee = float(raw_fee) if raw_fee is not None else None
    profit = order_service_profit(
        direction,
        crypto,
        fiat,
        crypto_amount,
        rate,
        cashback_applied_rub=cashback,
        card_fee_pct=fee,
        clamp=clamp,
    )
    gross = (
        buy_gross_margin_rub(
            fiat + cashback,
            crypto,
            crypto_amount=crypto_amount,
            rate=rate,
            card_fee=fee,
            clamp=clamp,
        )
        if direction == "buy"
        else profit
    )
    return {
        "gross_margin_rub": gross,
        "merchant_fee_rub": fiat * fee if direction == "buy" and fee is not None else 0.0,
        "service_profit_rub": profit,
    }
