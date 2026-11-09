"""Unit tests for profit calculation functions in app/services/profit.py."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.profit import (
    build_deal_result,
    calc_avg_rate,
    calc_current_profit,
    calc_doliv_profit_loss,
    calc_remaining,
    calc_required_doliv_amount,
    calc_turnover_usdt,
    calc_zaliv_profit,
    calc_zaliv_profit_usdt,
    calc_zaliv_total,
)


def _zaliv(amount: str, rate: str, profit_percent: str) -> MagicMock:
    z = MagicMock()
    z.amount = Decimal(amount)
    z.rate = Decimal(rate)
    z.profit_percent = Decimal(profit_percent)
    return z


def _doliv(amount: str, rate: str) -> MagicMock:
    d = MagicMock()
    d.amount = Decimal(amount)
    d.rate = Decimal(rate)
    return d


def _requisite(total_amount: str, target_rate: str) -> MagicMock:
    r = MagicMock()
    r.id = 1
    r.total_amount = Decimal(total_amount)
    r.target_rate = Decimal(target_rate)
    return r


# ──────────────────────────────────────────────────────────────────────────────
# calc_zaliv_total
# ──────────────────────────────────────────────────────────────────────────────

def test_zaliv_total_empty():
    assert calc_zaliv_total([]) == Decimal("0")


def test_zaliv_total_single():
    z = _zaliv("5000", "90", "12")
    assert calc_zaliv_total([z]) == Decimal("5000")


def test_zaliv_total_multiple():
    zalivs = [_zaliv("3000", "90", "12"), _zaliv("2000", "91", "10")]
    assert calc_zaliv_total(zalivs) == Decimal("5000")


# ──────────────────────────────────────────────────────────────────────────────
# calc_remaining
# ──────────────────────────────────────────────────────────────────────────────

def test_remaining_no_zalivs():
    req = _requisite("10000", "90")
    assert calc_remaining(req, []) == Decimal("10000.00")


def test_remaining_partial():
    req = _requisite("10000", "90")
    zalivs = [_zaliv("4000", "90", "12")]
    assert calc_remaining(req, zalivs) == Decimal("6000.00")


def test_remaining_fully_filled():
    req = _requisite("10000", "90")
    zalivs = [_zaliv("10000", "90", "12")]
    assert calc_remaining(req, zalivs) == Decimal("0.00")


def test_remaining_overfill():
    req = _requisite("10000", "90")
    zalivs = [_zaliv("12000", "90", "12")]
    assert calc_remaining(req, zalivs) == Decimal("-2000.00")


# ──────────────────────────────────────────────────────────────────────────────
# calc_required_doliv_amount
# ──────────────────────────────────────────────────────────────────────────────

def test_required_doliv_amount_basic():
    req = _requisite("10000", "90")
    zalivs = [_zaliv("4000", "90", "12")]
    assert calc_required_doliv_amount(req, zalivs) == Decimal("6000.00")


def test_required_doliv_amount_zero_when_full():
    req = _requisite("10000", "90")
    zalivs = [_zaliv("10000", "90", "12")]
    assert calc_required_doliv_amount(req, zalivs) == Decimal("0.00")


def test_required_doliv_amount_clamps_negative():
    req = _requisite("5000", "90")
    zalivs = [_zaliv("8000", "90", "12")]
    assert calc_required_doliv_amount(req, zalivs) == Decimal("0.00")


# ──────────────────────────────────────────────────────────────────────────────
# calc_avg_rate
# ──────────────────────────────────────────────────────────────────────────────

def test_avg_rate_empty():
    assert calc_avg_rate([]) is None


def test_avg_rate_single():
    z = _zaliv("5000", "90.5000", "12")
    result = calc_avg_rate([z])
    assert result == Decimal("90.5000")


def test_avg_rate_weighted():
    z1 = _zaliv("3000", "90.0000", "12")
    z2 = _zaliv("1000", "92.0000", "12")
    result = calc_avg_rate([z1, z2])
    # (3000*90 + 1000*92) / 4000 = (270000 + 92000) / 4000 = 362000/4000 = 90.5
    assert result == Decimal("90.5000")


# ──────────────────────────────────────────────────────────────────────────────
# calc_zaliv_profit (USDT)
# ──────────────────────────────────────────────────────────────────────────────

def test_zaliv_profit_basic():
    # 10000 * 12% = 1200 RUB; converted by requisite rate 90 -> 13.33 USDT
    z = _zaliv("10000", "90", "12")
    assert calc_zaliv_profit([z], Decimal("90")) == Decimal("13.33")


def test_zaliv_profit_zero_percent():
    z = _zaliv("10000", "90", "0")
    assert calc_zaliv_profit([z], Decimal("90")) == Decimal("0.00")


def test_zaliv_profit_zero_target_rate():
    z = _zaliv("10000", "90", "12")
    assert calc_zaliv_profit([z], Decimal("0")) == Decimal("0")


def test_zaliv_profit_matches_tz_example():
    # ТЗ: (5000*12% + 4000*12%) / 73.5 = 1080 / 73.5 = 14.69 USDT
    z1 = _zaliv("5000", "72.4", "12")
    z2 = _zaliv("4000", "72.2", "12")
    assert calc_zaliv_profit([z1, z2], Decimal("73.5")) == Decimal("14.69")


def test_zaliv_profit_usdt_per_zaliv():
    # ТЗ: 5000*12%/73.5 = 8.16, 4000*12%/73.5 = 6.53
    z1 = _zaliv("5000", "72.4", "12")
    z2 = _zaliv("4000", "72.2", "12")
    assert calc_zaliv_profit_usdt(z1, Decimal("73.5")) == Decimal("8.16")
    assert calc_zaliv_profit_usdt(z2, Decimal("73.5")) == Decimal("6.53")


# ──────────────────────────────────────────────────────────────────────────────
# calc_doliv_profit_loss
# ──────────────────────────────────────────────────────────────────────────────

def test_doliv_profit_loss_same_rate():
    doliv = _doliv("5000", "90")
    result = calc_doliv_profit_loss(doliv, Decimal("90"))
    assert result == Decimal("0.00")


def test_doliv_profit_loss_better_rate():
    """Dolivshchik used a better rate → profit for trader."""
    doliv = _doliv("9000", "90")
    result = calc_doliv_profit_loss(doliv, Decimal("100"))
    # doliv_usdt = 9000/90 = 100; target_usdt = 9000/100 = 90
    # profit_loss = target_usdt - doliv_usdt = 90 - 100 = -10 (loss)
    assert result == Decimal("-10.00")


def test_doliv_profit_loss_zero_rate():
    doliv = _doliv("5000", "0")
    result = calc_doliv_profit_loss(doliv, Decimal("90"))
    assert result == Decimal("0")


# ──────────────────────────────────────────────────────────────────────────────
# build_deal_result
# ──────────────────────────────────────────────────────────────────────────────

def test_build_deal_result():
    req = _requisite("10000", "90")
    zalivs = [_zaliv("5000", "90.0000", "12")]
    doliv = _doliv("5000", "90.0000")
    req.zalivs = zalivs

    result = build_deal_result(req, zalivs, doliv, merged_path="/tmp/test.pdf")
    assert result.total_turnover == Decimal("10000")
    assert result.doliv_rate == Decimal("90.0000")
    # 5000 * 12% = 600 RUB -> 600 / 90 = 6.67 USDT
    assert result.zaliv_profit == Decimal("6.67")
    assert result.doliv_profit_loss == Decimal("0.00")
    assert result.final_profit == Decimal("6.67")
    assert result.merged_receipt_path == "/tmp/test.pdf"


def test_build_deal_result_tz_example():
    # ТЗ: реквизит 10000 по курсу 73.5, заливы 5000/4000 (12%), долив 1000 по 63
    req = _requisite("10000", "73.5")
    zalivs = [_zaliv("5000", "72.4", "12"), _zaliv("4000", "72.2", "12")]
    doliv = _doliv("1000", "63")
    req.zalivs = zalivs

    result = build_deal_result(req, zalivs, doliv, merged_path=None)
    assert result.doliv_rate == Decimal("63")
    assert result.zaliv_profit == Decimal("14.69")
    # 1000/73.5 - 1000/63 = -2.27 (precise; the TZ used rounded intermediates -> -2.26)
    assert result.doliv_profit_loss == Decimal("-2.27")
    assert result.final_profit == Decimal("12.42")


def test_calc_turnover_usdt_mixed_rates():
    zalivs = [_zaliv("5000", "72.4", "12"), _zaliv("4000", "72.2", "12")]
    doliv = _doliv("1000", "63")
    # 5000/72.4 + 4000/72.2 + 1000/63
    expected = (
        Decimal("5000") / Decimal("72.4")
        + Decimal("4000") / Decimal("72.2")
        + Decimal("1000") / Decimal("63")
    ).quantize(Decimal("0.01"))
    assert calc_turnover_usdt(zalivs, doliv) == expected


def test_build_deal_result_sets_turnover_usdt():
    req = _requisite("10000", "73.5")
    zalivs = [_zaliv("5000", "72.4", "12"), _zaliv("4000", "72.2", "12")]
    doliv = _doliv("1000", "63")
    result = build_deal_result(req, zalivs, doliv, merged_path=None)
    assert result.turnover_usdt == calc_turnover_usdt(zalivs, doliv)
