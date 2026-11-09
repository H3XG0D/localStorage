"""Pure battle logic — no I/O, no wallet."""
from __future__ import annotations

from typing import Literal

Side = Literal["red", "blue"]


def calc_odds(red_total: float, blue_total: float) -> tuple[float, float]:
    bank = red_total + blue_total
    if bank <= 0:
        return 0.5, 0.5
    return red_total / bank, blue_total / bank


def should_refund(red_total: float, blue_total: float) -> bool:
    return red_total <= 0 or blue_total <= 0


def pick_winner(red_total: float, blue_total: float, rng: float) -> Side:
    """rng must be in [0, 1)."""
    if should_refund(red_total, blue_total):
        raise ValueError("cannot pick winner when one side is empty")
    red_pct, _ = calc_odds(red_total, blue_total)
    return "red" if rng < red_pct else "blue"


def calc_bank(red_total: float, blue_total: float) -> float:
    return round(red_total + blue_total, 2)


def calc_payout_pool(red_total: float, blue_total: float, rake: float) -> float:
    return round(calc_bank(red_total, blue_total) * (1 - rake), 2)


def split_payout(
    winner_bets: list[tuple[str, float]],
    red_total: float,
    blue_total: float,
    rake: float,
) -> dict[str, float]:
    """Distribute payout pool among winning-side bettors proportionally."""
    if not winner_bets:
        return {}

    payout_pool = calc_payout_pool(red_total, blue_total, rake)
    winning_side_total = sum(amount for _, amount in winner_bets)
    if winning_side_total <= 0:
        return {}

    raw = [
        (user_id, payout_pool * amount / winning_side_total)
        for user_id, amount in winner_bets
    ]
    rounded = {user_id: float(int(round(amount))) for user_id, amount in raw}
    remainder = round(payout_pool - sum(rounded.values()), 2)
    if remainder != 0:
        top_user = max(winner_bets, key=lambda x: x[1])[0]
        rounded[top_user] = round(rounded[top_user] + remainder, 2)
    return rounded


def validate_bet(amount: float, min_bet: float = 50, max_bet: float = 5000) -> None:
    if amount < min_bet:
        raise ValueError(f"minimum bet is {min_bet} ₽")
    if amount > max_bet:
        raise ValueError(f"maximum bet is {max_bet} ₽ per round")
