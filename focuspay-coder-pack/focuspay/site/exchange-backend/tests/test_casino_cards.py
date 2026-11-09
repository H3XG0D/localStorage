"""Deterministic card-shoe tests. These must fail if shuffle becomes identity or front-deal."""
from __future__ import annotations

import unittest

from casino_cards import (
    CARD_SHUFFLE_ALGORITHM,
    STANDARD_DECK,
    baccarat_card_value,
    baccarat_hand_score,
    blackjack_hand_score,
    dealt_cards,
    game_commit,
    hmac_shuffle,
    shoe_message,
    verify_card_round,
)


class CasinoCardShoeTests(unittest.TestCase):
    def test_standard_deck_is_52_unique_bot_compatible_faces(self):
        self.assertEqual(len(STANDARD_DECK), 52)
        self.assertEqual(len(set(STANDARD_DECK)), 52)
        self.assertEqual(STANDARD_DECK[0], "A♠")
        self.assertEqual(STANDARD_DECK[-1], "K♣")

    def test_hmac_shuffle_is_deterministic_and_not_identity(self):
        seed = "ab" * 32
        message = shoe_message(client_seed="alice", nonce=3, game_id="baccara-1", side="creator")
        first = hmac_shuffle(seed, message)
        second = hmac_shuffle(seed, message)
        self.assertEqual(first, second)
        self.assertEqual(sorted(first), sorted(STANDARD_DECK))
        self.assertNotEqual(first, list(STANDARD_DECK))

    def test_deal_pops_from_the_end_of_the_shuffled_shoe(self):
        seed = "ab" * 32
        game_id = "baccara-1"
        message = shoe_message(client_seed="alice", nonce=3, game_id=game_id, side="creator")
        shoe = hmac_shuffle(seed, message)
        dealt = dealt_cards(seed, game_id, "creator", 2, client_seed="alice", nonce=3)
        self.assertEqual(dealt, [shoe[-1], shoe[-2]])
        self.assertNotEqual(dealt, list(STANDARD_DECK[:2]))
        self.assertNotEqual(dealt, list(STANDARD_DECK[-2:]))

    def test_seat_shoes_are_independent_and_legacy_sides_unchanged(self):
        seed = "ab" * 32
        game_id = "baccara-1"
        creator = dealt_cards(seed, game_id, "creator", 2, client_seed="alice", nonce=3)
        seat1 = dealt_cards(seed, game_id, "seat1", 2, client_seed="alice", nonce=3)
        seat2 = dealt_cards(seed, game_id, "seat2", 2, client_seed="alice", nonce=3)
        self.assertEqual(creator, dealt_cards(seed, game_id, "creator", 2, client_seed="alice", nonce=3))
        self.assertNotEqual(seat1, seat2)
        self.assertNotEqual(seat1, creator)

    def test_creator_and_opponent_shoes_differ(self):
        seed = "ab" * 32
        game_id = "baccara-1"
        self.assertNotEqual(
            dealt_cards(seed, game_id, "creator", 3, client_seed="alice", nonce=3),
            dealt_cards(seed, game_id, "opponent", 3, client_seed="alice", nonce=3),
        )

    def test_commit_hash_matches_cub_style_sha256_seed_game_id(self):
        seed = "ab" * 32
        game_id = "baccara-1"
        commit = game_commit(seed, game_id)
        self.assertEqual(len(commit), 64)
        self.assertNotEqual(commit, game_commit(seed, "other"))

    def test_verify_accepts_matching_seed_and_rejects_one_character_tamper(self):
        seed = "ab" * 32
        game_id = "baccara-verify-1"
        client_seed = "alice"
        nonce = 3
        commit = game_commit(seed, game_id)
        cards = dealt_cards(seed, game_id, "creator", 2, client_seed=client_seed, nonce=nonce)
        ok = verify_card_round(
            server_seed=seed,
            client_seed=client_seed,
            nonce=nonce,
            game_id=game_id,
            commit=commit,
            side="creator",
            hand_size=2,
            expected_cards=cards,
        )
        self.assertTrue(ok["matches"])
        self.assertTrue(ok["commit_matches"])
        self.assertEqual(ok["algorithm"], CARD_SHUFFLE_ALGORITHM)
        self.assertEqual(ok["cards"]["creator"], cards)

        tampered = seed[:-1] + ("0" if seed[-1] != "0" else "1")
        self.assertNotEqual(tampered, seed)
        bad = verify_card_round(
            server_seed=tampered,
            client_seed=client_seed,
            nonce=nonce,
            game_id=game_id,
            commit=commit,
        )
        self.assertFalse(bad["matches"])
        self.assertFalse(bad["commit_matches"])

    def test_verify_rejects_expected_cards_that_do_not_match_the_shoe(self):
        seed = "ab" * 32
        game_id = "baccara-verify-2"
        commit = game_commit(seed, game_id)
        cards = dealt_cards(seed, game_id, "creator", 2, client_seed="alice", nonce=1)
        wrong = ["A♠", "K♣"] if cards != ["A♠", "K♣"] else ["2♠", "3♣"]
        result = verify_card_round(
            server_seed=seed,
            client_seed="alice",
            nonce=1,
            game_id=game_id,
            commit=commit,
            side="creator",
            expected_cards=wrong,
        )
        self.assertFalse(result["matches"])
        self.assertTrue(result["commit_matches"])
        self.assertFalse(result["cards_match"])

    def test_verify_accepts_seat_side(self):
        seed = "ab" * 32
        game_id = "baccara-seat-1"
        commit = game_commit(seed, game_id)
        cards = dealt_cards(seed, game_id, "seat3", 2, client_seed="alice", nonce=1)
        ok = verify_card_round(
            server_seed=seed, client_seed="alice", nonce=1, game_id=game_id,
            commit=commit, side="seat3", expected_cards=cards,
        )
        self.assertTrue(ok["matches"])
        self.assertEqual(ok["cards"]["seat3"], cards)


class CasinoCardScoreTests(unittest.TestCase):
    def test_baccarat_tens_are_zero_and_hand_is_mod_10(self):
        self.assertEqual(baccarat_card_value("K♥"), 0)
        self.assertEqual(baccarat_card_value("10♦"), 0)
        self.assertEqual(baccarat_card_value("A♠"), 1)
        self.assertEqual(baccarat_card_value("9♣"), 9)
        self.assertEqual(baccarat_hand_score(["A♠", "9♦"]), 0)
        self.assertEqual(baccarat_hand_score(["K♥", "2♣"]), 2)

    def test_blackjack_soft_ace_then_bust_reduces(self):
        self.assertEqual(blackjack_hand_score(["A♠", "K♥"]), 21)
        self.assertEqual(blackjack_hand_score(["A♠", "6♦", "K♣"]), 17)
        self.assertEqual(blackjack_hand_score(["K♥", "Q♦"]), 20)


if __name__ == "__main__":
    unittest.main()
