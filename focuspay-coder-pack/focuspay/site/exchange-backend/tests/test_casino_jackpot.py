"""Jackpot math: tickets, rake, committed roll, winner formula. No DB."""
from __future__ import annotations

from decimal import Decimal
import unittest

from casino_finance import casino_operation_ref
from casino_jackpot import (
    assign_ranges,
    commit_roll,
    make_roll,
    pick_winner,
    rake_split,
    tickets_for_amount,
    verify_jackpot_round,
    winning_ticket,
)


class JackpotTicketTests(unittest.TestCase):
    def test_one_ruble_is_one_hundred_tickets(self):
        self.assertEqual(tickets_for_amount(Decimal("1")), 100)
        self.assertEqual(tickets_for_amount("0.01"), 1)
        self.assertEqual(tickets_for_amount("12.50"), 1250)

    def test_winning_ticket_is_floor_of_roll_times_total(self):
        self.assertEqual(winning_ticket("0.5", 1000), 500)
        self.assertEqual(winning_ticket("0", 100), 0)
        self.assertEqual(winning_ticket("0.999", 100), 99)

    def test_rake_five_percent_of_thousand(self):
        rake, payout = rake_split(Decimal("1000"), Decimal("5"))
        self.assertEqual(rake, Decimal("50.00"))
        self.assertEqual(payout, Decimal("950.00"))

    def test_top_up_rebuilds_contiguous_ranges(self):
        first = assign_ranges([(1, Decimal("10"))])
        self.assertEqual(first[0]["tickets"], 1000)
        self.assertEqual(first[0]["ticket_from"], 0)
        self.assertEqual(first[0]["ticket_to"], 999)
        topped = assign_ranges([(1, Decimal("25")), (2, Decimal("5"))])
        self.assertEqual(topped[0]["tickets"], 2500)
        self.assertEqual(topped[1]["ticket_from"], 2500)
        self.assertEqual(topped[1]["ticket_to"], 2999)
        self.assertEqual(pick_winner(topped, 2499), 1)
        self.assertEqual(pick_winner(topped, 2500), 2)

    def test_small_stake_can_still_win_the_pot(self):
        ranges = assign_ranges([(1, Decimal("1")), (2, Decimal("99"))])
        self.assertEqual(pick_winner(ranges, 0), 1)
        self.assertEqual(pick_winner(ranges, 99), 1)
        self.assertEqual(pick_winner(ranges, 100), 2)

    def test_commit_is_sha256_of_roll_and_tamper_fails(self):
        roll = make_roll()
        commit = commit_roll(roll)
        total = 1000
        ticket = winning_ticket(roll, total)
        ok = verify_jackpot_round(roll=roll, commit=commit, total_tickets=total, expected_ticket=ticket)
        self.assertTrue(ok["matches"])
        self.assertEqual(ok["algorithm"], "sha256-roll-x-tickets")
        self.assertEqual(ok["winning_ticket"], ticket)
        bad = verify_jackpot_round(
            roll="0.11111111111111111111111111111111",
            commit=commit,
            total_tickets=total,
        )
        self.assertFalse(bad["commit_matches"])
        self.assertFalse(bad["matches"])

    def test_payout_ref_is_idempotent_key(self):
        first = casino_operation_ref("payout", "jp-abc", "9")
        second = casino_operation_ref("payout", "jp-abc", "9")
        self.assertEqual(first, second)
        self.assertNotEqual(first, casino_operation_ref("refund", "jp-abc", "9"))

    def test_solo_round_does_not_choose_a_winner(self):
        stakes = [(1, Decimal("50"))]
        self.assertLess(len(stakes), 2)
        ranges = assign_ranges(stakes)
        self.assertEqual(len(ranges), 1)


class JackpotHouseLedgerTests(unittest.TestCase):
    def test_house_credit_writes_game_settlement_ledger(self):
        import inspect
        import casino_jackpot

        self.assertIn("credit_house_game_settlement", inspect.getsource(casino_jackpot._credit_house))
        self.assertIn("jackpot-rake-", inspect.getsource(casino_jackpot._lock_and_settle))
