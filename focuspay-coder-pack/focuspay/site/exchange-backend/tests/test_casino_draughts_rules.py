"""Russian draughts wrapper: algebraic moves and 6.1.8 draws. No database."""
from __future__ import annotations

import inspect
import unittest
from decimal import Decimal

from draughts.boards.russian import Board as RussianBoard

import casino_draughts
import casino_draughts_rules
from casino_draughts import ALLOWS_BOT, LOCK_REF_KIND, settlement, timeout_winner
from casino_finance import _hold_order_ids, _spent_order_ids, casino_operation_ref
from casino_draughts_rules import DraughtsRulesError, assess, push_notation
from casino_holdem import rake_amount


def _alg(move, names) -> str:
    sep = ":" if move.captured_list else "-"
    return sep.join(names[square] for square in move.square_list)


class NotationTests(unittest.TestCase):
    def test_opening_is_algebraic_not_field_numbers(self):
        state = assess([])
        self.assertTrue(state.legal)
        self.assertTrue(all("-" in move.notation or ":" in move.notation for move in state.legal))
        self.assertTrue(all(not move.notation[0].isdigit() for move in state.legal))
        for module in (casino_draughts_rules, casino_draughts):
            imports = [
                line.strip()
                for line in inspect.getsource(module).splitlines()
                if line.startswith("import ") or line.startswith("from ")
            ]
            self.assertFalse(any("engines" in line or line.startswith("import random") for line in imports))
        self.assertFalse(ALLOWS_BOT)

    def test_short_capture_is_legal_beside_a_longer_one(self):
        state = assess([], start_fen="W:W21,22:B1,10,17")
        notations = {move.notation for move in state.legal}
        self.assertIn("c3:a5", notations)
        self.assertIn("a3:c5:e7", notations)

    def test_man_captures_backward(self):
        state = assess([], start_fen="W:W18:B22")
        self.assertEqual([move.notation for move in state.legal], ["d4:b2"])

    def test_king_flies(self):
        state = assess([], start_fen="W:WK29:B4")
        notations = {move.notation for move in state.legal}
        self.assertIn("a1-b2", notations)
        self.assertIn("a1-f6", notations)
        self.assertTrue(all(not move.capture for move in state.legal))

    def test_mid_capture_promotion_must_continue(self):
        state = assess([], start_fen="B:W25,26:B21")
        notations = {move.notation for move in state.legal}
        self.assertNotIn("a3:c1", notations)
        self.assertTrue(notations)
        self.assertTrue(all(move.notation.startswith("a3:c1:") for move in state.legal))
        landed = push_notation([], "a3:c1:e3", start_fen="B:W25,26:B21")
        self.assertEqual(landed.moves, ("a3:c1:e3",))
        king = next(piece for piece in landed.pieces if piece.square == "e3")
        self.assertEqual(king.kind, "king")
        self.assertEqual(king.side, "black")

    def test_illegal_notation_does_not_change_the_line(self):
        before = assess([])
        with self.assertRaises(DraughtsRulesError):
            push_notation([], "18-25")
        with self.assertRaises(DraughtsRulesError):
            push_notation([], "a1-b2")
        self.assertEqual(assess([]).moves, before.moves)
        self.assertEqual(len(assess([]).pieces), 24)


class DrawRuleTests(unittest.TestCase):
    def test_four_piece_king_dance_draws_on_the_15th_move_each(self):
        fen = "W:WK29,K18:BK3,K2"
        line = [
            "a1-b2", "d8-a5", "b2-a1", "a5-b4", "a1-b2", "b4-a3", "b2-a1", "a3-c1",
            "a1-c3", "c1-a3", "c3-a5", "a3-c1", "a5-b6", "c1-a3", "b6-a7", "a3-b4",
            "a7-b6", "b4-a5", "b6-a7", "a5-c7", "a7-b8", "c7-a5", "b8-e5", "a5-b4",
            "d4-a1", "b4-a3", "a1-c3", "a3-c1", "c3-a1", "c1-b2",
        ]
        early = assess(line[:28], start_fen=fen)
        self.assertEqual((early.white_moves, early.black_moves, early.status), (14, 14, "ongoing"))
        finished = assess(line, start_fen=fen)
        self.assertEqual(finished.status, "draw")
        self.assertEqual(finished.reason, "6.1.8.8")

    def test_six_piece_king_dance_survives_15_and_draws_at_25(self):
        fen = "W:WK16,K2,K10:BK1,K3,K4"
        line = [
            "d6-a3", "b8-a7", "a3-c1", "a7-b8", "c1-d2", "b8-a7", "d2-a5", "a7-b8",
            "a5-b6", "b8-a7", "b6-c7", "a7-b8", "c7-a5", "b8-d6", "a5-b6", "d6-a3",
            "b6-a5", "a3-b2", "a5-b6", "b2-a1", "b6-a5", "a1-e5", "a5-b6", "e5-b2",
            "b6-a5", "b2-a1", "a5-b6", "a1-c3", "b6-a7", "c3-a1", "a7-b8", "a1-b2",
            "b8-a7", "b2-a3", "a7-b6", "a3-b4", "b6-a5", "b4-a3", "a5-c7", "a3-b2",
            "c7-b8", "b2-a1", "b8-a7", "a1-b2", "a7-e3", "b2-a1", "d8-a5", "a1-b2",
            "a5-b6", "b2-a1",
        ]
        names = RussianBoard().SQUARE_NAMES
        halfway = assess(line[:30], start_fen=fen)
        self.assertEqual((halfway.white_moves, halfway.black_moves, halfway.status), (15, 15, "ongoing"))
        replay = RussianBoard.from_fen(fen)
        for text in line[:30]:
            replay.push(next(item for item in replay.legal_moves if _alg(item, names) == text))
        self.assertTrue(replay.is_draw)
        finished = assess(line, start_fen=fen)
        self.assertEqual((finished.white_moves, finished.black_moves), (25, 25))
        self.assertEqual(finished.status, "draw")
        self.assertEqual(finished.reason, "6.1.8.8")

    def test_two_kings_draw_after_five_moves_each(self):
        fen = "W:WK29:BK28"
        line = ["a1-b2", "h2-g1", "b2-a1", "g1-h2", "a1-c3", "h2-g1", "c3-b2", "g1-h2", "b2-a1", "h2-g1"]
        self.assertEqual(assess(line[:8], start_fen=fen).status, "ongoing")
        finished = assess(line, start_fen=fen)
        self.assertEqual(finished.status, "draw")
        self.assertEqual(finished.reason, "6.1.8.6")

    def test_repeated_position_is_a_draw_before_the_move_limit(self):
        fen = "W:WK1,K2:BK3,K4"
        cycle = ["b8-a7", "f8-d6", "a7-b8", "d6-f8"]
        once = assess(cycle, start_fen=fen)
        self.assertEqual(once.status, "ongoing")
        twice = assess(cycle * 2, start_fen=fen)
        self.assertEqual(twice.status, "draw")
        self.assertEqual(twice.reason, "threefold")


class MoneyTests(unittest.TestCase):
    def test_draw_returns_both_stakes_and_win_uses_holdem_rake(self):
        stake = Decimal("100")
        percent = Decimal("5")
        cap = Decimal("50")
        drawn = settlement(stake, "draw", percent, cap)
        self.assertEqual(drawn["rake"], Decimal("0.00"))
        self.assertEqual(drawn["white"], stake)
        self.assertEqual(drawn["black"], stake)
        won = settlement(stake, "white", percent, cap)
        rake = rake_amount(Decimal("200"), percent, cap)
        self.assertEqual(won["rake"], rake)
        self.assertEqual(won["white"], Decimal("200") - rake)
        self.assertEqual(won["black"], Decimal("0.00"))
        self.assertEqual(timeout_winner("white"), "black")
        timed = settlement(stake, timeout_winner("white"), percent, cap)
        self.assertEqual(timed["black"], Decimal("200") - rake)
        self.assertEqual(timed["white"], Decimal("0.00"))

    def test_rake_respects_the_holdem_cap(self):
        won = settlement(Decimal("10000"), "black", Decimal("5"), Decimal("50"))
        self.assertEqual(won["rake"], Decimal("50.00"))
        self.assertEqual(won["black"], Decimal("19950.00"))

    def test_stake_lock_fits_ledger_order_id(self):
        table_id = "d" + "ab" * 8
        ref = casino_operation_ref(LOCK_REF_KIND, table_id, "999")
        derived = (*_hold_order_ids(ref), *_spent_order_ids(ref))
        self.assertTrue(derived)
        self.assertLessEqual(max(len(item) for item in derived), 64)
        pay = casino_operation_ref("draughts-pay", table_id, "999:settle-white-w")
        self.assertLessEqual(len(pay), 64)
        broken = casino_operation_ref("draughts-lock", table_id, "999")
        self.assertGreater(len(f"spend-{broken}:partner"), 64)


if __name__ == "__main__":
    unittest.main()
