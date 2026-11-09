"""NLHE engine: ranking, streets, side pots, all-in, 2- and 6-seat tables, auto-fold."""
from __future__ import annotations

from decimal import Decimal
import json
import unittest

from treys import Card, Evaluator

from casino_cards import (
    STANDARD_DECK,
    game_commit,
    holdem_shuffled_deck,
    verify_holdem_round,
)
from casino_holdem import (
    _showdown,
    apply_action,
    apply_rake,
    apply_timeout,
    best_seven,
    cards_were_shown,
    deal_holdem,
    hand_name,
    hand_seed_public,
    legal_actions,
    next_button,
    public_view,
    rake_amount,
    rank_five,
    side_pots,
    start_hand,
    HandState,
    SeatState,
)


def _money(value: str | int) -> Decimal:
    return Decimal(str(value))


def _stacks(*amounts: str) -> dict[int, Decimal]:
    return {index + 1: _money(amount) for index, amount in enumerate(amounts)}


def _identity_deck() -> list[str]:
    return list(STANDARD_DECK)


class HoldemRankerTests(unittest.TestCase):
    def test_royal_flush_beats_quads_with_concrete_tuples(self):
        royal = rank_five(["A♠", "K♠", "Q♠", "J♠", "10♠"])
        quads = rank_five(["9♥", "9♦", "9♣", "9♠", "A♥"])
        self.assertEqual(royal[0], 8)
        self.assertEqual(quads[0], 7)
        self.assertGreater(royal, quads)
        self.assertEqual(hand_name(royal), "straight_flush")

    def test_wheel_straight_is_five_high_not_ace_high(self):
        wheel = rank_five(["A♣", "2♦", "3♥", "4♠", "5♣"])
        six_high = rank_five(["2♣", "3♦", "4♥", "5♠", "6♣"])
        self.assertEqual(wheel, (4, 5))
        self.assertEqual(six_high, (4, 6))
        self.assertGreater(six_high, wheel)

    def test_seven_card_uses_best_five_not_the_pair_on_board_only(self):
        score = best_seven(["A♠", "A♥", "K♦", "Q♣", "J♠", "9♥", "2♣"])
        self.assertEqual(hand_name(score), "pair")
        broadway = best_seven(["A♠", "K♠", "Q♦", "J♣", "10♥", "2♣", "3♦"])
        self.assertEqual(hand_name(broadway), "straight")
        self.assertGreater(broadway, score)


class HoldemDealAndFairnessTests(unittest.TestCase):
    def test_shared_shoe_deals_unique_cards_for_six_seats(self):
        deck = _identity_deck()
        holes, burns, board = deal_holdem(deck, [1, 2, 3, 4, 5, 6])
        dealt = [card for pair in holes.values() for card in pair] + burns + board
        self.assertEqual(len(dealt), 12 + 3 + 5)
        self.assertEqual(len(set(dealt)), 20)
        self.assertEqual(len(board), 5)
        self.assertEqual(len(burns), 3)
        self.assertEqual(holes[1][0], STANDARD_DECK[-1])

    def test_hmac_holdem_shoe_is_not_identity_and_verify_rejects_tamper(self):
        seed = "ab" * 32
        hand_id = "holdem-hand-1"
        commit = game_commit(seed, hand_id)
        deck = holdem_shuffled_deck(seed, client_seed="alice", nonce=4, hand_id=hand_id)
        self.assertNotEqual(deck, list(STANDARD_DECK))
        holes, _burns, board = deal_holdem(list(deck), [1, 2])
        ok = verify_holdem_round(
            server_seed=seed,
            client_seed="alice",
            nonce=4,
            hand_id=hand_id,
            commit=commit,
            seat_order=[1, 2],
            expected_board=board,
        )
        self.assertTrue(ok["matches"])
        self.assertEqual(ok["holes"]["1"], list(holes[1]))
        bad = verify_holdem_round(
            server_seed=seed[:-1] + "c",
            client_seed="alice",
            nonce=4,
            hand_id=hand_id,
            commit=commit,
            seat_order=[1, 2],
            expected_board=board,
        )
        self.assertFalse(bad["matches"])
        self.assertFalse(bad["commit_matches"])


class HoldemPlayTests(unittest.TestCase):
    def test_heads_up_call_down_button_is_sb_and_acts_first(self):
        state = start_hand(
            hand_id="hu-1",
            stacks=_stacks("1000", "1000"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        self.assertEqual(state.to_act, 1)
        self.assertEqual(state.seats[1].street_bet, _money("10"))
        self.assertEqual(state.seats[2].street_bet, _money("20"))
        apply_action(state, 1, "call")
        self.assertEqual(state.to_act, 2)
        apply_action(state, 2, "check")
        self.assertEqual(state.street, "flop")
        self.assertEqual(len(state.board), 3)
        while state.street not in {"complete", "showdown"}:
            acting = state.to_act
            self.assertIsNotNone(acting)
            legal = legal_actions(state)
            if "check" in legal["actions"]:
                apply_action(state, int(acting), "check")
            else:
                apply_action(state, int(acting), "call")
        self.assertEqual(state.street, "complete")
        self.assertEqual(money_sum(state), _money("2000"))
        self.assertIsNotNone(state.winners)
        self.assertGreater(len(state.winners or []), 0)

    def test_fold_preflop_awards_blinds_to_bb(self):
        state = start_hand(
            hand_id="fold-1",
            stacks=_stacks("500", "500"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        apply_action(state, 1, "fold")
        self.assertEqual(state.street, "complete")
        self.assertEqual(state.seats[1].stack, _money("490"))
        self.assertEqual(state.seats[2].stack, _money("510"))
        self.assertEqual(state.winners[0]["seat_no"], 2)
        self.assertEqual(state.winners[0]["reason"], "fold")

    def test_raise_below_min_is_rejected_with_stacks_unchanged(self):
        state = start_hand(
            hand_id="raise-1",
            stacks=_stacks("1000", "1000"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        with self.assertRaisesRegex(ValueError, "raise too small"):
            apply_action(state, 1, "raise", _money("30"))
        self.assertEqual(state.seats[1].stack, _money("990"))
        self.assertEqual(state.to_act, 1)

    def test_side_pots_split_main_and_overbet(self):
        state = HandState(
            hand_id="pots",
            street="showdown",
            button=1,
            small_blind=_money("5"),
            big_blind=_money("10"),
            seats={
                1: SeatState(seat_no=1, stack=_money("0"), committed=_money("100"), all_in=True),
                2: SeatState(seat_no=2, stack=_money("0"), committed=_money("50"), all_in=True),
                3: SeatState(seat_no=3, stack=_money("0"), committed=_money("50"), all_in=True),
            },
        )
        pots = side_pots(state)
        self.assertEqual(len(pots), 2)
        self.assertEqual(pots[0].amount, _money("150"))
        self.assertEqual(sorted(pots[0].eligible), [1, 2, 3])
        self.assertEqual(pots[1].amount, _money("50"))
        self.assertEqual(pots[1].eligible, [1])

    def test_three_way_all_in_builds_side_pots_then_awards_exactly_the_money(self):
        state = start_hand(
            hand_id="sp-1",
            stacks=_stacks("100", "50", "50"),
            button=1,
            small_blind=_money("5"),
            big_blind=_money("10"),
            deck=_identity_deck(),
        )
        # seats: 1 button/SB in 3-handed? 3 players: SB=next(1)=2, BB=3, UTG=1
        self.assertEqual(state.to_act, 1)
        apply_action(state, 1, "all_in")
        apply_action(state, 2, "all_in")
        if state.street != "complete":
            apply_action(state, 3, "all_in")
        self.assertEqual(state.street, "complete")
        self.assertEqual(money_sum(state), _money("200"))
        stacks = [state.seats[n].stack for n in (1, 2, 3)]
        self.assertEqual(sum(stacks, Decimal("0")), _money("200"))
        self.assertTrue(any(row.get("reason") == "showdown" for row in state.winners or []))

    def test_six_seats_deal_and_utg_fold_around_to_bb(self):
        stacks = {n: _money("200") for n in range(1, 7)}
        state = start_hand(
            hand_id="six-1",
            stacks=stacks,
            button=1,
            small_blind=_money("2"),
            big_blind=_money("4"),
            deck=_identity_deck(),
        )
        self.assertEqual(len(state.seats), 6)
        self.assertEqual(state.to_act, 4)  # UTG after BB=3
        for seat in (4, 5, 6, 1):
            self.assertEqual(state.to_act, seat)
            apply_action(state, seat, "fold")
        self.assertEqual(state.to_act, 2)
        apply_action(state, 2, "fold")
        self.assertEqual(state.street, "complete")
        self.assertEqual(state.winners[0]["seat_no"], 3)
        self.assertEqual(money_sum(state), _money("1200"))

    def test_timeout_checks_when_free_and_folds_facing_a_bet(self):
        state = start_hand(
            hand_id="to-1",
            stacks=_stacks("200", "200"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        apply_timeout(state)
        self.assertEqual(state.street, "complete")
        self.assertTrue(state.seats[1].folded)
        self.assertEqual(state.seats[2].stack, _money("210"))

        flop_state = start_hand(
            hand_id="to-2",
            stacks=_stacks("200", "200"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        apply_action(flop_state, 1, "call")
        apply_action(flop_state, 2, "check")
        self.assertEqual(flop_state.street, "flop")
        acting = flop_state.to_act
        apply_timeout(flop_state)
        self.assertNotEqual(flop_state.to_act, acting)

    def test_rake_five_percent_capped_and_stacks_still_sum(self):
        self.assertEqual(rake_amount(_money("100"), _money("5"), _money("3")), _money("3"))
        self.assertEqual(rake_amount(_money("100"), _money("5"), _money("0")), _money("5"))
        state = start_hand(
            hand_id="rake-1",
            stacks=_stacks("100", "100"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        apply_action(state, 1, "fold")
        taken = apply_rake(state, _money("5"), _money("10"))
        self.assertEqual(taken, _money("1.00"))  # 5% of 20
        self.assertEqual(money_sum(state) + taken, _money("200"))

    def test_json_roundtrip_keeps_button_and_holes(self):
        state = start_hand(
            hand_id="json-1",
            stacks=_stacks("80", "80", "80"),
            button=2,
            small_blind=_money("1"),
            big_blind=_money("2"),
            deck=_identity_deck(),
        )
        clone = HandState.from_dict(state.to_dict())
        self.assertEqual(clone.button, 2)
        self.assertEqual(clone.seats[1].hole, state.seats[1].hole)
        view = public_view(state, viewer_seat=1)
        self.assertIsNotNone(view["seats"][0]["hole"])
        other = next(row for row in view["seats"] if row["seat_no"] != 1)
        self.assertIsNone(other["hole"])
        self.assertFalse(clone.cards_shown)
        self.assertIsNone(clone.board_visible)

    def test_next_button_skips_busted_seat(self):
        self.assertEqual(next_button([1, 3, 5], 1), 3)
        self.assertEqual(next_button([1, 3, 5], 5), 1)


def money_sum(state: HandState) -> Decimal:
    return sum((seat.stack for seat in state.seats.values()), Decimal("0"))


def _view_json(state: HandState, viewer_seat: int | None) -> str:
    return json.dumps(public_view(state, viewer_seat=viewer_seat), ensure_ascii=False)


def _drive_checks(state: HandState) -> None:
    guard = 0
    while state.street not in {"complete", "showdown"} and state.to_act is not None:
        guard += 1
        if guard > 40:
            raise AssertionError("hand did not finish")
        acting = int(state.to_act)
        actions = list(legal_actions(state, acting)["actions"])
        if "check" in actions:
            apply_action(state, acting, "check")
        elif "call" in actions:
            apply_action(state, acting, "call")
        else:
            raise AssertionError(actions)


class HoldemPrivacyTests(unittest.TestCase):
    def test_two_viewers_never_see_the_other_pocket_before_showdown_or_after_fold(self):
        state = start_hand(
            hand_id="priv-fold",
            stacks=_stacks("500", "500"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        hole_a = list(state.seats[1].hole or ())
        hole_b = list(state.seats[2].hole or ())
        view_a = _view_json(state, 1)
        for card in hole_b:
            self.assertNotIn(card, view_a)
        for card in hole_a:
            self.assertIn(card, view_a)
        spectator = _view_json(state, None)
        for card in hole_a + hole_b + list(state.board_full) + list(state.burns):
            self.assertNotIn(card, spectator)

        apply_action(state, 1, "fold")
        self.assertEqual(state.street, "complete")
        self.assertFalse(state.cards_shown)
        self.assertEqual(state.winners[0]["reason"], "fold")
        folded = public_view(state, viewer_seat=1)
        folded_json = json.dumps(folded, ensure_ascii=False)
        for card in hole_b + list(state.board_full) + list(state.burns):
            self.assertNotIn(card, folded_json)
        for card in hole_a:
            self.assertIn(card, folded_json)
        self.assertLess(len(folded["board"]), 5)
        self.assertEqual(folded["board"], [])
        opponent = _view_json(state, 2)
        for card in hole_a:
            self.assertNotIn(card, opponent)
        for card in hole_b:
            self.assertIn(card, opponent)

    def test_flop_fold_keeps_dealt_board_and_hides_the_winner_pocket(self):
        state = start_hand(
            hand_id="priv-flop",
            stacks=_stacks("400", "400"),
            button=1,
            small_blind=_money("10"),
            big_blind=_money("20"),
            deck=_identity_deck(),
        )
        apply_action(state, 1, "call")
        apply_action(state, 2, "check")
        self.assertEqual(state.street, "flop")
        dealt = list(state.board)
        self.assertEqual(len(dealt), 3)
        folder = int(state.to_act)
        winner = 2 if folder == 1 else 1
        apply_action(state, folder, "fold")
        self.assertFalse(state.cards_shown)
        view = public_view(state, viewer_seat=folder)
        self.assertEqual(view["board"], dealt)
        blob = json.dumps(view, ensure_ascii=False)
        for card in list(state.seats[winner].hole or ()) + list(state.board_full[3:]) + list(state.burns):
            self.assertNotIn(card, blob)

    def test_showdown_shows_live_pockets_and_keeps_a_folded_pocket_hidden(self):
        state = start_hand(
            hand_id="priv-show",
            stacks=_stacks("300", "300", "300"),
            button=1,
            small_blind=_money("5"),
            big_blind=_money("10"),
            deck=_identity_deck(),
        )
        folded_hole = list(state.seats[1].hole or ())
        apply_action(state, 1, "fold")
        self.assertNotEqual(state.street, "complete")
        _drive_checks(state)
        self.assertTrue(state.cards_shown)
        self.assertEqual(state.street, "complete")
        view_a = _view_json(state, 2)
        for card in list(state.seats[3].hole or ()):
            self.assertIn(card, view_a)
        for card in folded_hole:
            self.assertNotIn(card, view_a)
        spectator = _view_json(state, None)
        for card in list(state.seats[2].hole or ()) + list(state.seats[3].hole or ()):
            self.assertIn(card, spectator)
        for card in folded_hole:
            self.assertNotIn(card, spectator)
        self.assertNotIn("board_full", public_view(state, viewer_seat=2))
        self.assertNotIn("burns", public_view(state, viewer_seat=2))

    def test_legacy_rows_show_cards_only_when_the_winner_reason_is_showdown(self):
        state = start_hand(
            hand_id="priv-legacy",
            stacks=_stacks("80", "80"),
            button=1,
            small_blind=_money("1"),
            big_blind=_money("2"),
            deck=_identity_deck(),
        )
        raw = state.to_dict()
        raw.pop("cards_shown")
        raw.pop("board_visible")
        raw["street"] = "complete"
        raw["winners"] = [{"seat_no": 2, "reason": "fold", "amount": "2.00"}]
        self.assertFalse(cards_were_shown(raw))
        self.assertFalse(HandState.from_dict(raw).cards_shown)
        raw["winners"] = [{"seat_no": 2, "reason": "showdown", "amount": "2.00"}]
        self.assertTrue(cards_were_shown(raw))
        self.assertFalse(hand_seed_public(False, "seed"))
        self.assertFalse(hand_seed_public(True, None))
        self.assertTrue(hand_seed_public(True, "seed"))


_TREYS_SUIT = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}
_TREYS = Evaluator()


def _treys_card(face: str) -> int:
    text = face.strip()
    if text.startswith("10"):
        rank, suit = "T", text[2:]
    else:
        rank, suit = text[:1], text[1:]
    return Card.new(rank + _TREYS_SUIT[suit])


def _treys_score(hole: list[str], board: list[str]) -> int:
    return _TREYS.evaluate([_treys_card(card) for card in board], [_treys_card(card) for card in hole])


def _award(holes: dict[int, list[str]], board: list[str], committed: dict[int, str], *, button: int = 1, folded: set[int] | None = None) -> HandState:
    hidden = folded or set()
    state = HandState(
        hand_id="judge",
        street="river",
        button=button,
        small_blind=_money("1"),
        big_blind=_money("2"),
        board_full=list(board),
        seats={
            num: SeatState(
                seat_no=num,
                stack=_money("0"),
                hole=(cards[0], cards[1]),
                committed=_money(amount),
                folded=num in hidden,
            )
            for num, cards in holes.items()
            for amount in (committed[num],)
        },
    )
    _showdown(state)
    return state


class HoldemTreysJudgeTests(unittest.TestCase):
    def test_wheel_loses_to_six_high_and_the_pot_follows_treys(self):
        board = ["A♠", "2♥", "3♦", "4♣", "9♠"]
        wheel = ["5♣", "K♥"]
        six = ["6♣", "5♦"]
        self.assertLess(best_seven(wheel + board), best_seven(six + board))
        self.assertLess(_treys_score(six, board), _treys_score(wheel, board))
        state = _award({1: wheel, 2: six}, board, {1: "40", 2: "40"})
        self.assertEqual(state.seats[2].stack, _money("80"))
        self.assertEqual(state.seats[1].stack, _money("0"))
        self.assertTrue(all(row["reason"] == "showdown" for row in state.winners or []))

    def test_kicker_orders_the_same_pair_like_treys(self):
        board = ["A♠", "9♥", "4♦", "3♣", "2♠"]
        king = ["A♥", "K♠"]
        queen = ["A♦", "Q♠"]
        self.assertGreater(best_seven(king + board), best_seven(queen + board))
        self.assertLess(_treys_score(king, board), _treys_score(queen, board))
        state = _award({1: king, 2: queen}, board, {1: "25", 2: "25"})
        self.assertEqual(state.seats[1].stack, _money("50"))
        self.assertEqual(state.seats[2].stack, _money("0"))

    def test_split_pot_matches_a_treys_tie_and_odd_kopek_goes_left_of_the_button(self):
        board = ["A♠", "K♥", "Q♦", "J♣", "10♠"]
        left = ["2♣", "3♦"]
        right = ["4♥", "5♣"]
        self.assertEqual(best_seven(left + board), best_seven(right + board))
        self.assertEqual(_treys_score(left, board), _treys_score(right, board))
        even = _award({1: left, 2: right}, board, {1: "10", 2: "10"})
        self.assertEqual(even.seats[1].stack, _money("10"))
        self.assertEqual(even.seats[2].stack, _money("10"))

        junk = {
            1: ["2♣", "3♦"],
            2: ["4♥", "5♣"],
            3: ["6♠", "7♥"],
            4: ["8♣", "9♦"],
            5: ["2♥", "3♣"],
        }
        for num in (1, 2, 3):
            self.assertEqual(_treys_score(junk[num], board), _treys_score(junk[1], board))
        odd = _award(
            junk,
            board,
            {1: "0.02", 2: "0.02", 3: "0.02", 4: "0.02", 5: "0.02"},
            button=1,
            folded={4, 5},
        )
        self.assertEqual(odd.seats[2].stack, _money("0.04"))
        self.assertEqual(odd.seats[3].stack, _money("0.03"))
        self.assertEqual(odd.seats[1].stack, _money("0.03"))
        self.assertEqual(money_sum(odd), _money("0.10"))

    def test_side_pot_pays_the_short_stack_main_and_treys_winner_the_side(self):
        board = ["2♠", "7♥", "9♦", "J♣", "K♠"]
        holes = {
            1: ["K♥", "5♣"],
            2: ["A♠", "A♥"],
            3: ["Q♠", "Q♥"],
        }
        committed = {1: "100", 2: "50", 3: "100"}
        main = [1, 2, 3]
        side = [1, 3]
        self.assertEqual(min(main, key=lambda num: _treys_score(holes[num], board)), 2)
        self.assertEqual(min(side, key=lambda num: _treys_score(holes[num], board)), 1)
        state = _award(holes, board, committed)
        self.assertEqual(state.seats[2].stack, _money("150"))
        self.assertEqual(state.seats[1].stack, _money("100"))
        self.assertEqual(state.seats[3].stack, _money("0"))
        self.assertEqual(money_sum(state), _money("250"))


if __name__ == "__main__":
    unittest.main()
