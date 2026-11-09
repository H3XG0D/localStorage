"""V2 equal-stake blackjack: two-card street deal, player hit/stand, highest legal hand wins."""
from __future__ import annotations

import unittest

from casino_cards import blackjack_hand_score
from datetime import datetime, timedelta, timezone

from casino_v2_cards import (
    BACCARA_CARD_MS,
    BACCARA_STREET_GAP_MS,
    BLACKJACK_STREET_CARDS,
    auto_hit_blackjack_to_seventeen,
    baccarat_reveal_ms,
    baccarat_table_decision,
    blackjack_all_done,
    blackjack_rank,
    blackjack_reveal_ms,
    blackjack_seat_done,
    blackjack_street_hands,
    blackjack_table_decision,
    card_reveal_ms,
    card_table_decision,
    deal_v2_blackjack_hands,
    deal_v2_card_hands,
    next_card_table_action,
    seat_shoe_side,
)


class V2BlackjackPureTests(unittest.TestCase):
    def test_seat_sides_are_committed_shoe_keys(self):
        self.assertEqual(seat_shoe_side(1), "seat1")
        self.assertEqual(seat_shoe_side(6), "seat6")

    def test_bust_ranks_below_any_legal_hand(self):
        self.assertEqual(blackjack_rank(21), 21)
        self.assertEqual(blackjack_rank(17), 17)
        self.assertEqual(blackjack_rank(22), -1)
        self.assertGreater(blackjack_rank(4), blackjack_rank(25))

    def test_highest_legal_hand_wins(self):
        decision = blackjack_table_decision(
            {
                1: ["K♠", "9♦"],
                2: ["A♠", "K♥"],
                3: ["K♥", "Q♦", "5♣"],
            }
        )
        self.assertEqual(decision["kind"], "winner")
        self.assertEqual(decision["winner_seat_nos"], [2])
        self.assertEqual(decision["scores"][2], 21)
        self.assertGreater(decision["scores"][3], 21)

    def test_equal_legal_scores_split_the_pot(self):
        decision = blackjack_table_decision(
            {
                1: ["K♠", "9♦"],
                2: ["K♥", "9♣"],
            }
        )
        self.assertEqual(decision["kind"], "tie_split")
        self.assertEqual(decision["winner_seat_nos"], [1, 2])

    def test_all_bust_is_a_split(self):
        decision = blackjack_table_decision(
            {
                1: ["K♠", "Q♦", "5♣"],
                2: ["K♥", "Q♥", "6♦"],
            }
        )
        self.assertEqual(decision["kind"], "tie_split")
        self.assertEqual(decision["winner_seat_nos"], [1, 2])

    def test_deal_starts_with_two_cards_not_seventeen(self):
        first = deal_v2_blackjack_hands("seed-a", "tbl-1", [1, 2, 3])
        second = deal_v2_blackjack_hands("seed-a", "tbl-1", [1, 2, 3])
        self.assertEqual(first, second)
        self.assertNotEqual(first[1], first[2])
        for cards in first.values():
            self.assertEqual(len(cards), BLACKJACK_STREET_CARDS)

    def test_blackjack_street_reveal_matches_two_cards_around_table(self):
        hands = {1: ["K♠", "9♦"], 2: ["A♠", "8♥"], 3: ["2♣", "4♦"]}
        expected = 5 * BACCARA_CARD_MS + BACCARA_STREET_GAP_MS
        self.assertEqual(expected, 2750)
        self.assertEqual(blackjack_reveal_ms(hands), expected)
        self.assertEqual(card_reveal_ms("blackjack", hands), expected)
        self.assertEqual(blackjack_street_hands({1: ["K♠", "9♦", "5♣"]})[1], ["K♠", "9♦"])

    def test_blackjack_waits_for_street_then_enters_hitting(self):
        hands = {1: ["K♠", "9♦"], 2: ["A♠", "8♥"]}
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        delay = blackjack_reveal_ms(hands)
        waiting = next_card_table_action(
            "blackjack",
            hands,
            now=now,
            dealt_at=now,
            roster_has_human=True,
        )
        self.assertEqual(waiting["kind"], "wait_reveal")
        hitting = next_card_table_action(
            "blackjack",
            hands,
            now=now + timedelta(milliseconds=delay),
            dealt_at=now,
            roster_has_human=True,
        )
        self.assertEqual(hitting["kind"], "hitting")

    def test_bust_closes_seat_without_stand(self):
        self.assertTrue(blackjack_seat_done(["K♠", "Q♦", "5♣"], stood=False))
        self.assertFalse(blackjack_seat_done(["K♠", "9♦"], stood=False))

    def test_all_done_when_stood_or_bust(self):
        bust_hands = {1: ["K♠", "9♦"], 2: ["K♥", "Q♦", "5♣"]}
        self.assertFalse(blackjack_all_done(bust_hands, set()))
        self.assertTrue(blackjack_all_done(bust_hands, {1}))
        open_hands = {1: ["K♠", "9♦"], 2: ["A♠", "8♥"]}
        self.assertFalse(blackjack_all_done(open_hands, set()))
        self.assertTrue(blackjack_all_done(open_hands, {1, 2}))

    def test_bot_auto_hit_reaches_seventeen(self):
        hands = deal_v2_blackjack_hands("seed-bot", "tbl-bot", [1])
        cards = auto_hit_blackjack_to_seventeen("seed-bot", "tbl-bot", hands[1], seat_no=1)
        self.assertGreaterEqual(blackjack_hand_score(cards), 17)


class V2BaccaratPureTests(unittest.TestCase):
    def test_higher_mod10_wins(self):
        decision = baccarat_table_decision(
            {
                1: ["A♠", "8♦"],
                2: ["K♥", "2♣"],
            }
        )
        self.assertEqual(decision["kind"], "winner")
        self.assertEqual(decision["winner_seat_nos"], [1])
        self.assertEqual(decision["scores"][1], 9)
        self.assertEqual(decision["scores"][2], 2)

    def test_equal_scores_split(self):
        decision = baccarat_table_decision(
            {
                1: ["A♠", "8♦"],
                2: ["4♥", "5♣"],
            }
        )
        self.assertEqual(decision["kind"], "tie_split")
        self.assertEqual(decision["winner_seat_nos"], [1, 2])

    def test_card_table_decision_routes_baccarat(self):
        decision = card_table_decision("baccara", {1: ["9♠", "K♦"], 2: ["A♥", "2♣"]})
        self.assertEqual(decision["winner_seat_nos"], [1])

    def test_deal_is_stable_per_seat(self):
        first = deal_v2_card_hands("baccara", "seed-b", "tbl-b", [1, 2])
        second = deal_v2_card_hands("baccara", "seed-b", "tbl-b", [1, 2])
        self.assertEqual(first, second)
        self.assertNotEqual(first[1], first[2])
        for cards in first.values():
            self.assertGreaterEqual(len(cards), 2)
            self.assertLessEqual(len(cards), 3)

    def test_unique_winner_waits_for_street_reveal_before_settle(self):
        hands = {1: ["9♠", "K♦"], 2: ["A♥", "2♣"]}
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        expected_ms = 3 * BACCARA_CARD_MS + BACCARA_STREET_GAP_MS
        self.assertEqual(baccarat_reveal_ms(hands), expected_ms)
        self.assertEqual(expected_ms, 1910)
        waiting = next_card_table_action(
            "baccara",
            hands,
            now=now,
            dealt_at=now,
            roster_has_human=True,
        )
        self.assertEqual(waiting["kind"], "wait_reveal")
        ready_at = now + timedelta(milliseconds=expected_ms)
        settled = next_card_table_action(
            "baccara",
            hands,
            now=ready_at,
            dealt_at=now,
            roster_has_human=True,
        )
        self.assertEqual(settled["kind"], "settle")
        self.assertEqual(settled["outcome_kind"], "winner")
        self.assertEqual(settled["winners"], [1])

    def test_tie_waits_then_redeals(self):
        hands = {1: ["A♠", "8♦"], 2: ["4♥", "5♣"]}
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        waiting = next_card_table_action(
            "baccara",
            hands,
            now=now,
            dealt_at=now,
            roster_has_human=True,
        )
        self.assertEqual(waiting["kind"], "wait_reveal")
        later = next_card_table_action(
            "baccara",
            hands,
            now=now + timedelta(seconds=10),
            dealt_at=now,
            roster_has_human=True,
        )
        self.assertEqual(later["kind"], "redeal")
        self.assertEqual(later["winners"], [1, 2])
        bot_only = next_card_table_action(
            "baccara",
            hands,
            now=now + timedelta(seconds=10),
            dealt_at=now,
            roster_has_human=False,
        )
        self.assertEqual(bot_only["kind"], "redeal")

    def test_blackjack_tie_still_offers_draw_choice(self):
        hands = {1: ["K♠", "9♦"], 2: ["K♥", "9♣"]}
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        later = next_card_table_action(
            "blackjack",
            hands,
            now=now,
            dealt_at=now - timedelta(seconds=10),
            roster_has_human=True,
            phase="hitting",
            stood_seats={1, 2},
        )
        self.assertEqual(later["kind"], "draw_choice")
        self.assertEqual(later["winners"], [1, 2])
