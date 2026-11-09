"""Admin operator period/daily stats must count role_split like shift KPIs."""
from datetime import datetime, timezone

from operator_stats import build_daily_stats, compute_period_stats


def _shift(started, ended=None, sid=1):
    return {"id": sid, "started_at": started, "ended_at": ended}


def test_period_stats_include_role_split_orders_and_ledger_earnings():
    started = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)
    orders = [
        {
            "order_id": "legacy-a",
            "fiat_amount": 1000,
            "crypto": "usdt",
            "direction": "buy",
            "cashback_applied_rub": 0,
            "card_fee_pct": 0,
            "rate": 100,
            "crypto_amount": 10,
            "payroll_model": "legacy",
            "payout_confirmed_at": datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
        },
        {
            "order_id": "split-a",
            "fiat_amount": 5000,
            "payroll_model": "role_split",
            "payout_confirmed_at": datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc),
        },
    ]
    out = compute_period_stats(
        [_shift(started, ended)],
        orders,
        10.0,
        {},
        role_split_earnings_by_order={"split-a": 42.5},
    )
    assert out["orders_period"] == 2
    assert out["fiat_period"] == 6000.0
    assert out["earnings_period_rub"] > 42.5


def test_daily_stats_keep_newest_first_and_count_role_split():
    from datetime import date

    day_a = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
    day_b = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
    orders = [
        {
            "order_id": "split-b",
            "fiat_amount": 3000,
            "payroll_model": "role_split",
            "payout_confirmed_at": datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
        }
    ]
    daily, summary = build_daily_stats(
        [_shift(day_b, datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc), 2),
         _shift(day_a, datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc), 1)],
        orders,
        0.0,
        {},
        date(2026, 8, 19),
        date(2026, 8, 20),
        role_split_earnings_by_order={"split-b": 12.0},
    )
    assert [row["date"] for row in daily] == ["2026-08-20", "2026-08-19"]
    assert daily[0]["orders"] == 1
    assert daily[0]["fiat"] == 3000.0
    assert daily[0]["earnings_rub"] == 12.0
    assert daily[1]["orders"] == 0
    assert summary["orders"] == 1
