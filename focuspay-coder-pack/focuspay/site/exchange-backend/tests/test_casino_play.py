"""House play quote, tape privacy, stake bound copy."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from casino_finance import canonical_casino_settings
from casino_play import (
    HIGH_STAKE_RUB,
    build_play_quote,
    build_tape_row,
    filter_tape_rows,
    house_bots_cub_odds,
    stake_bound_error,
)


def _settings():
    return canonical_casino_settings(
        [
            {"key": "enabled_games", "value": {"cub": True, "raffle": False}},
            {"key": "min_bet_rub", "value": {"amount": 10}},
            {"key": "max_bet_rub", "value": {"amount": 100000}},
            {"key": "commission_rate_wagering_complete", "value": {"percent": 5}},
        ]
    )


class PlayQuoteTests(unittest.TestCase):
    def test_win_on_win_is_gross_minus_commission(self):
        quote = build_play_quote(
            _settings(),
            stake_rub=Decimal("100"),
            payout_multiplier=Decimal("2"),
            commission_rate=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
            enabled=True,
            win_probability=Decimal("0.5"),
        )
        self.assertEqual(quote["gross_payout_rub"], 200.0)
        self.assertEqual(quote["commission_rub"], 5.0)
        self.assertEqual(quote["win_on_win_rub"], 195.0)
        self.assertNotEqual(quote["win_on_win_rub"], quote["gross_payout_rub"])
        self.assertIsNone(quote["bound_error"])

    def test_card_house_quote_is_195_without_cub_probability(self):
        cards = build_play_quote(
            _settings(),
            stake_rub=Decimal("100"),
            payout_multiplier=Decimal("2"),
            commission_rate=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
            enabled=True,
            game_type="blackjack",
        )
        self.assertEqual(cards["game_type"], "blackjack")
        self.assertEqual(cards["win_on_win_rub"], 195.0)
        self.assertIsNone(cards["win_probability"])

    def test_below_and_above_limits_have_human_copy(self):
        self.assertEqual(stake_bound_error(Decimal("9"), Decimal("10"), Decimal("500")), "Ставка ниже минимума 10.00 ₽")
        self.assertEqual(stake_bound_error(Decimal("501"), Decimal("10"), Decimal("500")), "Ставка выше максимума 500.00 ₽")
        quote = build_play_quote(
            _settings(),
            stake_rub=Decimal("5"),
            payout_multiplier=Decimal("2"),
            commission_rate=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100"),
            enabled=True,
        )
        self.assertEqual(quote["bound_error"], "Ставка ниже минимума 10.00 ₽")


class HouseBotOddsTests(unittest.TestCase):
    def test_two_bots_are_x3_and_one_in_three(self):
        odds = house_bots_cub_odds(2)
        self.assertEqual(odds, (Decimal("3"), Decimal(1) / Decimal(3)))

    def test_three_bots_are_x4_and_one_in_four(self):
        odds = house_bots_cub_odds(3)
        self.assertEqual(odds, (Decimal("4"), Decimal("0.25")))

    def test_six_bots_are_x7_and_one_in_seven(self):
        odds = house_bots_cub_odds(6)
        self.assertEqual(odds, (Decimal("7"), Decimal(1) / Decimal(7)))

    def test_one_x1_and_zero_bots_keep_cub_policy(self):
        self.assertIsNone(house_bots_cub_odds(0))
        self.assertIsNone(house_bots_cub_odds(1))
        self.assertIsNone(house_bots_cub_odds(7))

    def test_three_bots_quote_100_pays_385_after_commission(self):
        multiplier, probability = house_bots_cub_odds(3)
        quote = build_play_quote(
            _settings(),
            stake_rub=Decimal("100"),
            payout_multiplier=multiplier,
            commission_rate=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
            enabled=True,
            win_probability=probability,
        )
        self.assertEqual(quote["payout_multiplier"], 4.0)
        self.assertEqual(quote["win_probability"], 0.25)
        self.assertEqual(quote["gross_payout_rub"], 400.0)
        self.assertEqual(quote["commission_rub"], 15.0)
        self.assertEqual(quote["win_on_win_rub"], 385.0)

    def test_two_bots_quote_100_pays_290_after_commission(self):
        multiplier, probability = house_bots_cub_odds(2)
        quote = build_play_quote(
            _settings(),
            stake_rub=Decimal("100"),
            payout_multiplier=multiplier,
            commission_rate=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
            enabled=True,
            win_probability=probability,
        )
        self.assertEqual(quote["payout_multiplier"], 3.0)
        self.assertEqual(quote["win_probability"], float(Decimal(1) / Decimal(3)))
        self.assertEqual(quote["gross_payout_rub"], 300.0)
        self.assertEqual(quote["commission_rub"], 10.0)
        self.assertEqual(quote["win_on_win_rub"], 290.0)


class PlayTapeTests(unittest.TestCase):
    def test_row_hides_creator_id_and_marks_mine(self):
        row = {
            "game_id": "cub-1",
            "game_type": "cub",
            "creator_id": 940002,
            "winner_id": 940002,
            "bet_rub": Decimal("100"),
            "payout_rub": Decimal("195"),
            "finished_at": datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
        }
        mine = build_tape_row(row, viewer_id=940002)
        other = build_tape_row(row, viewer_id=7)
        self.assertNotIn("creator_id", mine)
        self.assertTrue(mine["is_mine"])
        self.assertFalse(other["is_mine"])
        self.assertEqual(mine["player_label"], "Вы")
        self.assertEqual(other["player_label"], "Игрок")

    def test_high_tab_uses_duel_high_band_floor(self):
        self.assertEqual(HIGH_STAKE_RUB, Decimal("5000"))
        rows = [
            {"game_id": "low", "game_type": "cub", "creator_id": 1, "winner_id": None, "bet_rub": Decimal("4999.99"), "payout_rub": 0, "finished_at": None},
            {"game_id": "high", "game_type": "cub", "creator_id": 2, "winner_id": 2, "bet_rub": Decimal("5000"), "payout_rub": 0, "finished_at": None},
        ]
        high = filter_tape_rows(rows, tab="high", viewer_id=1)
        mine = filter_tape_rows(rows, tab="mine", viewer_id=1)
        self.assertEqual([item["game_id"] for item in high], ["high"])
        self.assertEqual([item["game_id"] for item in mine], ["low"])


class PlayRouteImportTests(unittest.TestCase):
    def test_user_and_public_play_routes_exist(self):
        from routers import public_casino, user_casino

        public_paths = {getattr(route, "path", None) for route in public_casino.router.routes}
        user_paths = {getattr(route, "path", None) for route in user_casino.router.routes}
        self.assertIn("/casino/play/quote", public_paths)
        self.assertIn("/casino/play/tape", public_paths)
        self.assertIn("/casino/play", user_paths)
        self.assertIn("/casino/play/action", user_paths)
        self.assertIn("/casino/play/pending", user_paths)
        self.assertIn("/casino/fairness/session", user_paths)
        self.assertIn("/casino/fairness/rotate", user_paths)
        self.assertIn("/casino/fairness/client-seed", user_paths)
        self.assertIn("/casino/players/me/history", user_paths)
        self.assertIn("/casino/players/{player_id}/history", user_paths)
        self.assertIn("/casino/players/me/history/grouped", user_paths)
        self.assertIn("/casino/players/{player_id}/history/grouped", user_paths)
        self.assertIn("/casino/poker/tables", user_paths)
        self.assertIn("/casino/poker/tables/{table_id}", user_paths)
        self.assertIn("/casino/poker/tables/{table_id}/sit", user_paths)
        self.assertIn("/casino/poker/tables/{table_id}/leave", user_paths)
        self.assertIn("/casino/poker/tables/{table_id}/act", user_paths)
        self.assertIn("/casino/poker/tables/{table_id}/events", user_paths)
        self.assertIn("/casino/poker/tables", public_paths)


if __name__ == "__main__":
    unittest.main()
