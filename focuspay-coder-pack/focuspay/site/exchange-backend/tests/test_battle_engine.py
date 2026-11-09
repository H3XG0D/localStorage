import pytest

from battle_engine import (
    calc_bank,
    calc_odds,
    calc_payout_pool,
    pick_winner,
    should_refund,
    split_payout,
    validate_bet,
)


def test_split_two_winners_on_red():
    winner_bets = [("you", 100.0), ("friend", 200.0)]
    payouts = split_payout(winner_bets, red_total=300, blue_total=500, rake=0.05)
    assert payouts["you"] == 253.0
    assert payouts["friend"] == 507.0
    assert sum(payouts.values()) == 760.0


def test_rake_deducted():
    pool = calc_payout_pool(red_total=300, blue_total=500, rake=0.05)
    assert calc_bank(300, 500) == 800
    assert pool == 760.0


def test_one_side_only_refunds():
    assert should_refund(300, 0) is True
    assert should_refund(0, 500) is True
    assert should_refund(100, 200) is False


def test_proportional_odds_rng():
    red_pct, blue_pct = calc_odds(300, 500)
    assert red_pct == pytest.approx(0.375)
    assert blue_pct == pytest.approx(0.625)
    assert pick_winner(300, 500, 0.0) == "red"
    assert pick_winner(300, 500, 0.375) == "blue"
