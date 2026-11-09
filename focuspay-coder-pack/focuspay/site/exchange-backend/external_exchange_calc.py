"""Расчёт внештатных обменов.

Режимы наценки (markup_mode):
  on_deal     — input = сумма на баланс; client_pays = input * (1 + pct/100)
  on_turnover — input = сумма оплаты клиента; base = input * (1 - pct/100)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

MarkupMode = Literal["on_deal", "on_turnover"]


def _fmt_rub(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def normalize_markup_mode(mode: str | None) -> MarkupMode:
    if mode == "on_turnover":
        return "on_turnover"
    return "on_deal"


@dataclass(frozen=True)
class DealCalcResult:
    amount_rub: float
    markup_pct: float
    markup_mode: str
    card_fee_pct: float
    usdt_rate_rub: float
    operator_percent: float
    receive_fee_usd: float

    client_pays_rub: float
    payfast_fee_rub: float
    net_profit_rub: float
    operator_earnings_rub: float
    principal_usdt: float
    reward_usdt: float
    total_credit_usdt: float
    house_profit_usd: float
    input_rub: float
    markup_rub: float


@dataclass(frozen=True)
class PayoutCalcResult:
    gross_usd: float
    fee_usd: float
    net_usd: float
    crypto: str = "usdt"
    crypto_amount: float = 0.0
    crypto_rate_usd: float = 1.0


def build_markup_formula(
    *,
    base_rub: float,
    client_pays_rub: float,
    markup_pct: float,
    markup_mode: str,
    input_rub: float | None = None,
) -> dict:
    mode = normalize_markup_mode(markup_mode)
    inp = round(float(input_rub if input_rub is not None else base_rub), 2)
    base = round(float(base_rub), 2)
    client = round(float(client_pays_rub), 2)
    pct = float(markup_pct)
    markup_rub = round(abs(client - base), 2)

    if mode == "on_turnover":
        inp = round(float(input_rub if input_rub is not None else client), 2)
        formula_text = (
            f"{_fmt_rub(inp)} − {pct:g}% = {_fmt_rub(base)} ₽ на баланс. "
            f"К оплате: {_fmt_rub(client)} ₽"
        )
        input_label = "Сумма оплаты клиента, ₽"
    else:
        inp = round(float(input_rub if input_rub is not None else base), 2)
        formula_text = (
            f"{_fmt_rub(inp)} + {pct:g}% = {_fmt_rub(client)} ₽ к оплате. "
            f"На баланс: {_fmt_rub(base)} ₽"
        )
        input_label = "Сумма на баланс, ₽"

    return {
        "markup_mode": mode,
        "markup_pct": pct,
        "input_rub": inp,
        "base_rub": base,
        "amount_rub": base,
        "client_pays_rub": client,
        "markup_rub": markup_rub,
        "formula_text": formula_text,
        "input_label": input_label,
    }


def calc_deal(
    input_rub: float,
    usdt_rate_rub: float,
    *,
    markup_pct: float,
    card_fee_pct: float,
    receive_fee_usd: float,
    operator_percent: float = 0.0,
    net_percent: float = 0.0,
    markup_mode: str = "on_deal",
) -> DealCalcResult:
    """Рассчитать одну сделку.

    input_rub — сумма, которую вводит внештатник (база или оборот — по markup_mode).
    """
    _ = net_percent
    if usdt_rate_rub <= 0:
        raise ValueError("usdt_rate_rub must be > 0")
    if input_rub <= 0:
        raise ValueError("amount_rub must be > 0")

    mode = normalize_markup_mode(markup_mode)
    if mode == "on_turnover":
        client_pays_rub = round(input_rub, 2)
        base_rub = round(input_rub * (1.0 - markup_pct / 100.0), 2)
        if base_rub <= 0:
            raise ValueError("base amount must be > 0 after markup")
    else:
        base_rub = round(input_rub, 2)
        client_pays_rub = round(input_rub * (1.0 + markup_pct / 100.0), 2)

    payfast_fee_rub = round(client_pays_rub * card_fee_pct, 2)
    net_profit_rub = round(client_pays_rub - payfast_fee_rub - base_rub, 2)

    operator_earnings_rub = round(
        max(0.0, net_profit_rub) * float(operator_percent) / 100.0, 2
    )
    principal_usdt = round(base_rub / usdt_rate_rub, 6)
    reward_usdt = 0.0
    total_credit_usdt = round(principal_usdt, 6)

    house_margin_rub = round(net_profit_rub - operator_earnings_rub, 2)
    house_profit_usd = round(
        house_margin_rub / usdt_rate_rub - receive_fee_usd, 6
    )
    markup_rub = round(abs(client_pays_rub - base_rub), 2)

    return DealCalcResult(
        amount_rub=base_rub,
        markup_pct=markup_pct,
        markup_mode=mode,
        card_fee_pct=card_fee_pct,
        usdt_rate_rub=usdt_rate_rub,
        operator_percent=float(operator_percent),
        receive_fee_usd=receive_fee_usd,
        client_pays_rub=client_pays_rub,
        payfast_fee_rub=payfast_fee_rub,
        net_profit_rub=net_profit_rub,
        operator_earnings_rub=operator_earnings_rub,
        principal_usdt=principal_usdt,
        reward_usdt=reward_usdt,
        total_credit_usdt=total_credit_usdt,
        house_profit_usd=house_profit_usd,
        input_rub=round(input_rub, 2),
        markup_rub=markup_rub,
    )


def calc_payout(
    gross_usd: float,
    *,
    fee_usd: float,
) -> PayoutCalcResult:
    if gross_usd <= 0:
        raise ValueError("gross_usd must be > 0")
    if fee_usd < 0:
        raise ValueError("fee_usd must be >= 0")
    if fee_usd >= gross_usd:
        raise ValueError("fee_usd must be less than gross_usd")

    net_usd = round(gross_usd - fee_usd, 6)
    return PayoutCalcResult(
        gross_usd=round(gross_usd, 6),
        fee_usd=round(fee_usd, 6),
        net_usd=net_usd,
    )


def preview_deal(
    input_rub: float,
    usdt_rate_rub: float,
    *,
    markup_pct: float,
    card_fee_pct: float,
    receive_fee_usd: float,
    operator_percent: float = 0.0,
    net_percent: float = 0.0,
    markup_mode: str = "on_deal",
) -> Optional[dict]:
    try:
        r = calc_deal(
            input_rub,
            usdt_rate_rub,
            markup_pct=markup_pct,
            card_fee_pct=card_fee_pct,
            receive_fee_usd=receive_fee_usd,
            operator_percent=operator_percent,
            net_percent=net_percent,
            markup_mode=markup_mode,
        )
    except ValueError:
        return None

    formula = build_markup_formula(
        base_rub=r.amount_rub,
        client_pays_rub=r.client_pays_rub,
        markup_pct=r.markup_pct,
        markup_mode=r.markup_mode,
        input_rub=r.input_rub,
    )
    return {
        "client_pays_rub": r.client_pays_rub,
        "payfast_fee_rub": r.payfast_fee_rub,
        "net_profit_rub": r.net_profit_rub,
        "operator_earnings_rub": r.operator_earnings_rub,
        "operator_percent": r.operator_percent,
        "principal_usdt": r.principal_usdt,
        "reward_usdt": r.reward_usdt,
        "total_credit_usdt": r.total_credit_usdt,
        "house_profit_usd": r.house_profit_usd,
        "usdt_rate_rub": r.usdt_rate_rub,
        "amount_rub": r.amount_rub,
        "markup_mode": r.markup_mode,
        "markup_rub": r.markup_rub,
        "input_rub": r.input_rub,
        **formula,
    }


def crypto_usd_rate(crypto: str, market_rub: dict[str, float]) -> float:
    c = (crypto or "usdt").split("_")[0].lower().strip()
    usdt_rub = float(market_rub.get("usdt") or 0)
    if usdt_rub <= 0:
        raise ValueError("usdt_rate_rub must be > 0")
    if c == "usdt":
        return 1.0
    crypto_rub = float(market_rub.get(c) or 0)
    if crypto_rub <= 0:
        raise ValueError(f"rate for {c} unavailable")
    return crypto_rub / usdt_rub


def usd_to_crypto(net_usd: float, crypto: str, market_rub: dict[str, float]) -> tuple[float, float]:
    rate = crypto_usd_rate(crypto, market_rub)
    amount = round(net_usd / rate, 8) if rate > 0 else 0.0
    return amount, round(rate, 6)


def calc_payout_with_crypto(
    gross_usd: float,
    *,
    fee_usd: float,
    crypto: str,
    market_rub: dict[str, float],
) -> PayoutCalcResult:
    base = calc_payout(gross_usd, fee_usd=fee_usd)
    crypto_amount, crypto_rate_usd = usd_to_crypto(base.net_usd, crypto, market_rub)
    return PayoutCalcResult(
        gross_usd=base.gross_usd,
        fee_usd=base.fee_usd,
        net_usd=base.net_usd,
        crypto=crypto,
        crypto_amount=crypto_amount,
        crypto_rate_usd=crypto_rate_usd,
    )


def preview_payout(
    gross_usd: float,
    crypto: str,
    market_rub: dict[str, float],
    *,
    fee_usd: float,
    payout_threshold_usd: float,
) -> Optional[dict]:
    try:
        r = calc_payout_with_crypto(
            gross_usd,
            fee_usd=fee_usd,
            crypto=crypto,
            market_rub=market_rub,
        )
    except ValueError:
        return None
    return {
        "gross_usd": r.gross_usd,
        "fee_usd": r.fee_usd,
        "net_usd": r.net_usd,
        "crypto": r.crypto,
        "crypto_amount": r.crypto_amount,
        "crypto_rate_usd": r.crypto_rate_usd,
        "payout_threshold_usd": payout_threshold_usd,
    }
