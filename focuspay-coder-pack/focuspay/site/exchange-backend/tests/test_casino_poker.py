"""Hold'em buy-in bounds, rake cap, escrow invariant — no database."""
from __future__ import annotations

from decimal import Decimal
import unittest

from casino_poker import buyin_bounds, escrow_total, holdem_config_from_rows


class PokerMoneyTests(unittest.TestCase):
    def test_buyin_is_20_to_100_big_blinds(self):
        lo, hi = buyin_bounds(Decimal("20"), 20, 100)
        self.assertEqual(lo, Decimal("400.00"))
        self.assertEqual(hi, Decimal("2000.00"))

    def test_buyin_swaps_inverted_bb_counts(self):
        lo, hi = buyin_bounds(Decimal("10"), 100, 20)
        self.assertEqual(lo, Decimal("200.00"))
        self.assertEqual(hi, Decimal("1000.00"))

    def test_escrow_is_stacks_plus_pot(self):
        total = escrow_total({1: Decimal("90.00"), 3: Decimal("50.00")}, Decimal("40.00"))
        self.assertEqual(total, Decimal("180.00"))

    def test_config_reads_registry_defaults_and_enabled_flag(self):
        cfg = holdem_config_from_rows({}, enabled=True)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.small_blind, Decimal("10.00"))
        self.assertEqual(cfg.big_blind, Decimal("20.00"))
        self.assertEqual(cfg.rake_percent, Decimal("5.00"))
        self.assertEqual(cfg.rake_cap, Decimal("50.00"))
        self.assertEqual(cfg.timeout_seconds, 30)
        self.assertEqual(cfg.min_buyin, Decimal("400.00"))
        self.assertEqual(cfg.max_buyin, Decimal("2000.00"))
        off = holdem_config_from_rows(
            {
                "holdem_small_blind_rub": {"amount": 5},
                "holdem_big_blind_rub": {"amount": 10},
                "holdem_rake_percent": {"percent": 4},
                "holdem_rake_cap_rub": {"amount": 0},
                "holdem_action_timeout_seconds": {"value": 12},
                "holdem_min_buyin_bb": {"value": 10},
                "holdem_max_buyin_bb": {"value": 40},
            },
            enabled=False,
        )
        self.assertFalse(off.enabled)
        self.assertEqual(off.min_buyin, Decimal("100.00"))
        self.assertEqual(off.max_buyin, Decimal("400.00"))
        self.assertEqual(off.timeout_seconds, 12)
        self.assertEqual(off.rake_cap, Decimal("0.00"))
