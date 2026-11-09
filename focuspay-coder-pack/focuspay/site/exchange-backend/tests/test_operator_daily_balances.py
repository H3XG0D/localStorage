from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from operator_stats import (
    MOSCOW_DATE_SQL,
    MOSCOW_TODAY_SQL,
    build_daily_balance_stats,
    compute_balance_summary,
    moscow_date_expr,
)


def test_compute_balance_summary_network_fees():
    raw = [{"crypto": "usdt", "balance_start": 1000.0, "balance_end": 900.0}]
    orders = [
        {"crypto": "usdt", "direction": "buy", "crypto_amount": 50.0},
        {"crypto": "usdt", "direction": "sell", "crypto_amount": 10.0},
    ]
    rows = compute_balance_summary(raw, orders)
    assert len(rows) == 1
    assert rows[0]["sent_in_buy"] == 50.0
    assert rows[0]["recv_in_sell"] == 10.0
    assert rows[0]["expected_end"] == 960.0
    assert rows[0]["network_fees"] == 60.0


def test_build_daily_balance_stats_gap_and_delta():
    d1 = datetime(2026, 7, 6, 6, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)
    d3 = datetime(2026, 7, 7, 6, 0, tzinfo=timezone.utc)

    shifts = [
        {
            "id": 1,
            "started_at": d1,
            "ended_at": datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
            "balance_summary": [
                {
                    "crypto": "usdt",
                    "balance_start": 1000.0,
                    "balance_end": 800.0,
                    "sent_in_buy": 100.0,
                    "recv_in_sell": 20.0,
                    "network_fees": 0.0,
                }
            ],
        },
        {
            "id": 2,
            "started_at": d2,
            "ended_at": datetime(2026, 7, 6, 20, 0, tzinfo=timezone.utc),
            "balance_summary": [
                {
                    "crypto": "usdt",
                    "balance_start": 850.0,
                    "balance_end": 700.0,
                    "sent_in_buy": 50.0,
                    "recv_in_sell": 10.0,
                    "network_fees": 1.0,
                }
            ],
        },
        {
            "id": 3,
            "started_at": d3,
            "ended_at": datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
            "balance_summary": [
                {
                    "crypto": "usdt",
                    "balance_start": 750.0,
                    "balance_end": 600.0,
                    "sent_in_buy": 80.0,
                    "recv_in_sell": 5.0,
                    "network_fees": 0.5,
                }
            ],
        },
    ]

    daily = build_daily_balance_stats(shifts, date(2026, 7, 6), date(2026, 7, 7))
    assert len(daily) == 2

    day_jul7 = next(r for r in daily if r["date"] == "2026-07-07")
    gap = day_jul7["shifts"][0]["balances"][0]["gap_from_prev"]
    assert gap == 50.0

    day_jul6 = next(r for r in daily if r["date"] == "2026-07-06")
    usdt = next(s for s in day_jul6["summary"] if s["crypto"] == "usdt")
    assert usdt["balance_start"] == 1000.0
    assert usdt["balance_end"] == 700.0
    assert usdt["day_delta"] == -300.0
    assert usdt["sent_in_buy"] == 150.0
    assert usdt["recv_in_sell"] == 30.0
    assert usdt["gap_in"] == 50.0
    assert usdt["gap_out"] == 0.0
    assert usdt["total_network_fees"] == 1.0
    assert usdt["vs_prev_day_end"] is None

    usdt7 = next(s for s in day_jul7["summary"] if s["crypto"] == "usdt")
    assert usdt7["vs_prev_day_end"] == -100.0
    assert usdt7["sent_in_buy"] == 80.0
    assert usdt7["recv_in_sell"] == 5.0
    assert usdt7["gap_in"] == 50.0

    shift2 = day_jul6["shifts"][1]
    assert shift2["balances"][0]["gap_from_prev"] == 50.0


def test_moscow_date_expr_sql():
    expr = moscow_date_expr("started_at")
    assert expr == "((started_at AT TIME ZONE 'Europe/Moscow')::date)"
    assert "Europe/Moscow" in MOSCOW_DATE_SQL
    assert "Europe/Moscow" in MOSCOW_TODAY_SQL


def test_match_orders_to_shift_uses_completion_not_created():
    from operator_stats import match_orders_to_shift, match_orders_to_shift_by_created

    shift = {
        "started_at": datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
        "ended_at": datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
    }
    # Created before shift, completed inside → counts for turnover
    early = {
        "order_id": "a",
        "fiat_amount": 15000,
        "created_at": datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc),
        "payout_confirmed_at": datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc),
    }
    # Created inside, completed after → not in turnover for this shift
    late = {
        "order_id": "b",
        "fiat_amount": 5000,
        "created_at": datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc),
        "payout_confirmed_at": datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc),
    }
    stats = match_orders_to_shift([early, late], shift)
    flow = match_orders_to_shift_by_created([early, late], shift)
    assert [o["order_id"] for o in stats] == ["a"]
    assert [o["order_id"] for o in flow] == ["b"]

    """Shift at 2026-06-30 23:30 Chicago ≈ 2026-07-01 07:30 MSK → July period."""
    # 2026-07-01 04:30 UTC = 2026-06-30 23:30 CDT (UTC-5) = 2026-07-01 07:30 MSK
    started = datetime(2026, 7, 1, 4, 30, tzinfo=timezone.utc)
    moscow_day = started.astimezone(ZoneInfo("Europe/Moscow")).date()
    chicago_day = started.astimezone(ZoneInfo("America/Chicago")).date()
    assert moscow_day == date(2026, 7, 1)
    assert chicago_day == date(2026, 6, 30)

    # Aggregation must bucket by Moscow, not Chicago.
    shifts = [
        {
            "id": 32,
            "started_at": started,
            "ended_at": datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            "balance_summary": [
                {
                    "crypto": "usdt",
                    "balance_start": 100.0,
                    "balance_end": 90.0,
                    "sent_in_buy": 10.0,
                    "recv_in_sell": 0.0,
                    "network_fees": 0.0,
                }
            ],
        }
    ]
    daily = build_daily_balance_stats(shifts, date(2026, 7, 1), date(2026, 7, 16))
    assert len(daily) == 1
    assert daily[0]["date"] == "2026-07-01"

    # Same shift must NOT appear when period is June only (Moscow).
    daily_june = build_daily_balance_stats(shifts, date(2026, 6, 1), date(2026, 6, 30))
    assert daily_june == []
