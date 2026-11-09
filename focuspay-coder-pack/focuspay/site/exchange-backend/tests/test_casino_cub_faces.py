"""Presentation d6 faces for web cub. Money still follows HMAC < threshold."""
from __future__ import annotations

import unittest

from casino_cub_faces import (
    LOSE_PAIRS,
    WIN_PAIRS,
    cub_pips_from_rng,
    cub_presentation_pips,
)
from casino_finance import canonical_casino_settings
from casino_play import build_play_quote
from decimal import Decimal


class CubPresentationPipsTests(unittest.TestCase):
    def test_pair_tables_cover_strict_wins_and_losses_without_ties(self):
        self.assertEqual(len(WIN_PAIRS), 15)
        self.assertEqual(len(LOSE_PAIRS), 15)
        self.assertEqual(len(set(WIN_PAIRS)), 15)
        self.assertEqual(len(set(LOSE_PAIRS)), 15)
        for player, house in WIN_PAIRS:
            self.assertGreater(player, house)
            self.assertGreaterEqual(player, 1)
            self.assertLessEqual(player, 6)
            self.assertGreaterEqual(house, 1)
            self.assertLessEqual(house, 6)
        for player, house in LOSE_PAIRS:
            self.assertLess(player, house)

    def test_same_digest_is_stable_and_matches_won(self):
        digest = 0xC0FFEE
        win = cub_presentation_pips(digest, won=True)
        lose = cub_presentation_pips(digest, won=False)
        self.assertEqual(win, cub_presentation_pips(digest, won=True))
        self.assertEqual(lose, cub_presentation_pips(digest, won=False))
        self.assertGreater(win[0], win[1])
        self.assertLess(lose[0], lose[1])
        self.assertNotEqual(win, lose)

    def test_every_slot_agrees_with_won(self):
        for index in range(15):
            player, house = cub_presentation_pips(index, won=True)
            self.assertGreater(player, house, msg=index)
            player, house = cub_presentation_pips(index, won=False)
            self.assertLess(player, house, msg=index)

    def test_from_rng_prefers_stored_then_digest(self):
        stored = cub_pips_from_rng({"player_pips": 6, "house_pips": 1, "won": False, "digest_hex": "ab"})
        self.assertEqual(stored, {"player_pips": 6, "house_pips": 1})
        derived = cub_pips_from_rng({"won": True, "digest_hex": "0f"})
        self.assertEqual(derived, dict(zip(("player_pips", "house_pips"), cub_presentation_pips(15, won=True))))
        self.assertEqual(cub_pips_from_rng({}), {})
        self.assertEqual(cub_pips_from_rng({"won": True, "digest_hex": "zz"}), {})


class CubPayoutUnchangedTests(unittest.TestCase):
    def test_quote_win_on_win_still_195_at_5_percent(self):
        settings = canonical_casino_settings(
            [
                {"key": "enabled_games", "value": {"cub": True, "raffle": False}},
                {"key": "min_bet_rub", "value": {"amount": 10}},
                {"key": "max_bet_rub", "value": {"amount": 100000}},
                {"key": "commission_rate_wagering_complete", "value": {"percent": 5}},
            ]
        )
        quote = build_play_quote(
            settings,
            stake_rub=Decimal("100"),
            payout_multiplier=Decimal("2"),
            commission_rate=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
            enabled=True,
            win_probability=Decimal("0.5"),
        )
        self.assertEqual(quote["win_on_win_rub"], 195.0)
        self.assertEqual(quote["gross_payout_rub"], 200.0)
        self.assertEqual(quote["commission_rub"], 5.0)


if __name__ == "__main__":
    unittest.main()
