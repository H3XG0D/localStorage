from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from payin_diagnostics import diagnose, estimate, utc

NOW = datetime(2026, 9, 15, 21, 40, tzinfo=timezone.utc)  # 00:40 Wednesday MSK


def card(amount=10000, **kwargs):
    return dict(id=1, operator_id=1, method="sbp", amount_rub=amount,
                paid_rub=0, reserved_rub=0, max_checks=5, used_checks=0,
                status="OPEN", confirmed_at=NOW - timedelta(hours=2),
                created_at=NOW - timedelta(hours=2), deadline_at=NOW + timedelta(hours=3),
                **kwargs)


def event(minutes=10, days=1, amount=5000, method="SBPRUB", status="PAID"):
    return dict(created_at=(NOW - timedelta(days=days) + timedelta(minutes=minutes)).replace(tzinfo=None),
                fiat_amount=Decimal(amount), sub_token=method, status=status)


def test_naive_orders_are_utc_not_moscow():
    assert utc(datetime(2026, 9, 15, 21, 40)) == NOW


def test_empty_is_unknown_not_zero_percent():
    out = estimate(card(), [], now=NOW)
    assert out["traffic"]["probability_60m"] is None
    assert out["traffic"]["payment_conversion"] is None
    assert out["traffic"]["confidence"] == "none"


def test_zero_event_windows_are_in_denominator_and_midnight_is_supported():
    t = estimate(card(), [event()], now=NOW)["traffic"]
    assert t["comparison_windows"] == 35
    assert t["probability_15m"] == round(1/35, 4)
    assert t["matching_created"] == 1


def test_probabilities_use_arrival_time_and_conversion_only_resolved():
    data = [event(minutes=10), event(minutes=25, status="CANCELED"),
            event(minutes=50, days=2, status="PENDING")]
    t = estimate(card(), data, now=NOW)["traffic"]
    assert t["probability_15m"] == t["probability_30m"] == round(1/35, 4)
    assert t["probability_60m"] == round(2/35, 4)
    assert t["payment_conversion"] == .5


def test_same_weekday_only_when_enough_events():
    data = [event(days=7, minutes=i + 1) for i in range(8)]
    t = estimate(card(), data, now=NOW)["traffic"]
    assert t["comparison_windows"] == 5
    assert t["source"] == "general_buy_history"
    assert t["probability_15m"] == .2


def test_method_fallback_matches_bot_and_crypto_is_not_a_filter():
    sbp = estimate(card(), [event(method="CARDRUB")], now=NOW)["traffic"]
    r = card()
    r["method"] = "card"
    only_card = estimate(r, [event(method="SBPRUB")], now=NOW)["traffic"]
    assert sbp["matching_created"] == 1
    assert only_card["matching_created"] == 0
    assert sbp["all_crypto"] is True


@pytest.mark.parametrize("amount,checks", [(5000, 1), (10000, 2), (20000, 4)])
def test_sequences_really_close_remaining_amount(amount, checks):
    r = card(amount)
    # Avoid the 45-minute follow-up hunt: an older first payment.
    r["first_paid_at"] = NOW - timedelta(hours=2)
    sequences = estimate(r, [event()], now=NOW)["traffic"]["payment_sequences"]
    assert any(len(seq) == checks and sum(seq) == amount for seq in sequences)


def test_insufficient_limit_does_not_invent_closure():
    r = card(20000)
    r["max_checks"] = 2
    assert estimate(r, [event()], now=NOW)["traffic"]["payment_sequences"] == []


def test_reserved_expired_queued_and_limit_are_explicit():
    r = card()
    r.update(reserved_rub=5000, has_open_reserve=True, status="QUEUED",
             confirmed_at=None, deadline_at=NOW, used_checks=5)
    out = estimate(r, [event()], now=NOW)
    assert out["readiness"]["ready"] is False
    assert len(out["readiness"]["reasons"]) == 5
    assert out["readiness"]["free_rub"] == 5000


@pytest.mark.asyncio
async def test_loader_excludes_manual_orders_and_reports_assignment_not_delivery():
    conn = AsyncMock()
    conn.fetch.return_value = [event()]
    conn.fetchrow.return_value = dict(assigned_count=1, paid_count=0, canceled_count=0,
        first_assigned_at=NOW, last_assigned_at=NOW, first_paid_at=None,
        last_order_id="synthetic", inconsistent_count=0)
    result = await diagnose(conn, card(), now=NOW)
    sql = conn.fetch.call_args.args[0]
    assert "NOT LIKE 'OP%'" in sql
    assert "AT TIME ZONE" not in sql
    assert result["issuance"]["health"] == "working"
    assert "delivered" not in result["issuance"]
    conn.fetchrow.return_value["inconsistent_count"] = 1
    assert (await diagnose(conn, card(), now=NOW))["issuance"]["health"] == "error"
