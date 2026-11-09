"""Длинные нарды: пункты правил, не короткие и не GNU."""
from __future__ import annotations

import random
import unittest
from decimal import Decimal

from casino_nardy import (
    BLACK,
    WHITE,
    Position,
    apply_steps,
    checkers_ok,
    format_move,
    has_illegal_prime,
    initial_position,
    legal_moves,
    point_number,
    result_kind,
    settlement,
    verify_log,
    Match,
)


def _pile(mapping: dict[int, int]) -> tuple[int, ...]:
    pile = [0] * 24
    for index, count in mapping.items():
        pile[index] = count
    return tuple(pile)


def _ends(pos: Position, player: int, dice: tuple[int, int], *, first_roll: bool) -> list[Position]:
    return [apply_steps(pos, player, move) for move in legal_moves(pos, player, dice, first_roll=first_roll)]


class OpeningRules(unittest.TestCase):
    def test_point_numbers_match_the_wikipedia_board(self):
        self.assertEqual(point_number(0), 24)
        self.assertEqual(point_number(12), 12)
        self.assertEqual(point_number(18), 6)
        self.assertEqual(point_number(23), 1)
        self.assertEqual(point_number(6), 18)
        self.assertEqual(point_number(11), 13)

    def test_opening_66_puts_two_checkers_on_18_and_burns_the_rest(self):
        # Википедия / Ахундов: 6-6 с головы две шашки, дальше голова соперника.
        ends = _ends(initial_position(), WHITE, (6, 6), first_roll=True)
        self.assertTrue(ends)
        for pos in ends:
            self.assertEqual(pos.white[0], 13)
            self.assertEqual(pos.white[6], 2)
            self.assertEqual(sum(pos.white), 15)

    def test_opening_44_puts_two_checkers_on_16(self):
        ends = _ends(initial_position(), WHITE, (4, 4), first_roll=True)
        self.assertTrue(ends)
        for pos in ends:
            self.assertEqual(pos.white[0], 13)
            self.assertEqual(pos.white[8], 2)

    def test_opening_33_can_split_21_and_15_or_both_on_18(self):
        ends = {pos.white for pos in _ends(initial_position(), WHITE, (3, 3), first_roll=True)}
        both_on_18 = _pile({0: 13, 6: 2})
        split = _pile({0: 13, 3: 1, 9: 1})
        self.assertIn(both_on_18, ends)
        self.assertIn(split, ends)

    def test_opening_55_is_one_checker_because_it_jumps_the_enemy_head(self):
        ends = _ends(initial_position(), WHITE, (5, 5), first_roll=True)
        self.assertTrue(ends)
        for pos in ends:
            self.assertEqual(pos.white[0], 14)
            self.assertEqual(pos.white[20], 1)

    def test_opening_22_stays_one_checker(self):
        moves = legal_moves(initial_position(), WHITE, (2, 2), first_roll=True)
        self.assertTrue(all(len(move) == 4 for move in moves))
        for pos in _ends(initial_position(), WHITE, (2, 2), first_roll=True):
            self.assertEqual(pos.white[0], 14)

    def test_black_opening_44_lands_on_point_4(self):
        # Арифметика круга: две четвёрки с 12 заканчиваются на пункте 4.
        # Фраза Ахундова «пункт 3» с этим и с «пункт 4 занят» не сходится.
        ends = _ends(initial_position(), BLACK, (4, 4), first_roll=True)
        self.assertTrue(ends)
        for pos in ends:
            self.assertEqual(pos.black[12], 13)
            self.assertEqual(pos.black[20], 2)

    def test_wikipedia_white_55_then_black_44_plays_one_four(self):
        white = _ends(initial_position(), WHITE, (5, 5), first_roll=True)[0]
        moves = legal_moves(white, BLACK, (4, 4), first_roll=True)
        self.assertTrue(moves)
        for move in moves:
            self.assertEqual(len(move), 1)
            self.assertEqual((move[0].src, move[0].die, move[0].dst), (12, 4, 16))
            self.assertIn("12→8", format_move(move))


class MoveLaws(unittest.TestCase):
    def test_cannot_land_on_an_opponent_checker(self):
        pos = Position(_pile({5: 1}), _pile({8: 1, 12: 14}), 14, 0)
        for move in legal_moves(pos, WHITE, (3, 1), first_roll=False):
            self.assertTrue(all(step.dst != 8 for step in move))

    def test_full_move_beats_a_single_die(self):
        pos = Position(_pile({5: 15}), _pile({12: 15}), 0, 0)
        moves = legal_moves(pos, WHITE, (2, 3), first_roll=False)
        self.assertTrue(moves)
        self.assertTrue(all(len(move) == 2 for move in moves))

    def test_when_only_one_die_fits_the_higher_one_is_required(self):
        pos = Position(_pile({5: 1}), _pile({10: 1, 12: 14}), 14, 0)
        moves = legal_moves(pos, WHITE, (2, 3), first_roll=False)
        self.assertTrue(moves)
        self.assertTrue(all(len(move) == 1 and move[0].die == 3 for move in moves))

    def test_lower_die_still_plays_when_the_higher_is_blocked(self):
        pos = Position(_pile({5: 1}), _pile({8: 1, 12: 14}), 14, 0)
        moves = legal_moves(pos, WHITE, (3, 1), first_roll=False)
        self.assertTrue(moves)
        self.assertTrue(all(move[0].die == 1 for move in moves))

    def test_six_prime_in_front_of_every_enemy_checker_is_refused(self):
        # Сначала встать на 13 при живых 14–18 — глухой заслон. Даже если второй
        # костью его потом разобрать, промежуток запрещён (п. 20.5).
        sealed = Position(_pile({0: 9, 13: 1, 14: 1, 15: 1, 16: 1, 17: 1, 18: 1}), _pile({12: 15}), 0, 0)
        self.assertTrue(has_illegal_prime(sealed, WHITE))
        pos = Position(_pile({0: 9, 7: 1, 14: 1, 15: 1, 16: 1, 17: 1, 18: 1}), _pile({12: 15}), 0, 0)
        moves = legal_moves(pos, WHITE, (6, 5), first_roll=False)
        self.assertTrue(moves)
        self.assertFalse(any(move[0].src == 7 and move[0].die == 6 for move in moves))

    def test_prime_is_legal_once_an_enemy_checker_is_past_it(self):
        # Чёрная шашка уже на 19 (индекс 5), прайм 13–18 её не запирает.
        white = _pile({0: 8, 7: 1, 13: 1, 14: 1, 15: 1, 16: 1, 17: 1})
        black = _pile({5: 1, 12: 14})
        pos = Position(white, black, 0, 0)
        moves = legal_moves(pos, WHITE, (6, 1), first_roll=False)
        self.assertTrue(any(step.src == 7 and step.dst == 13 for move in moves for step in move))

    def test_no_bear_off_while_a_checker_is_outside_home(self):
        pos = Position(_pile({0: 1, 23: 14}), _pile({12: 15}), 0, 0)
        for move in legal_moves(pos, WHITE, (1, 6), first_roll=False):
            self.assertTrue(all(step.dst >= 0 for step in move))
            self.assertEqual(apply_steps(pos, WHITE, move).white_off, 0)

    def test_exact_and_overshoot_bear_off(self):
        pos = Position(_pile({23: 15}), _pile({12: 15}), 0, 0)
        moves = legal_moves(pos, WHITE, (6, 5), first_roll=False)
        self.assertTrue(moves)
        for move in moves:
            self.assertEqual(len(move), 2)
            self.assertTrue(all(step.dst < 0 for step in move))
        self.assertEqual(apply_steps(pos, WHITE, moves[0]).white_off, 2)

    def test_inside_home_move_is_kept_when_bearing_is_also_possible(self):
        # 14 на краю, одна перед домом. Дубль 1: можно снять или идти внутри.
        pos = Position(_pile({17: 1, 23: 14}), _pile({12: 15}), 0, 0)
        moves = legal_moves(pos, WHITE, (1, 1), first_roll=False)
        self.assertTrue(any(any(step.dst < 0 for step in move) for move in moves))
        self.assertTrue(any(all(step.dst >= 0 for step in move) for move in moves))

    def test_rank_six_die_one_moves_inside_instead_of_bearing_low(self):
        pos = Position(_pile({18: 15}), _pile({12: 15}), 0, 0)
        moves = legal_moves(pos, WHITE, (1, 2), first_roll=False)
        self.assertTrue(moves)
        self.assertTrue(all(step.dst >= 0 for move in moves for step in move))


class MoneyAndMatch(unittest.TestCase):
    def test_oin_returns_the_spare_stake_and_mars_takes_both(self):
        oin = settlement(Decimal("100"), "oin", Decimal("5"), Decimal("500"))
        self.assertEqual(oin["rake"], Decimal("5.00"))
        self.assertEqual(oin["winner"], Decimal("295.00"))
        self.assertEqual(oin["loser"], Decimal("100.00"))
        mars = settlement(Decimal("100"), "mars", Decimal("5"), Decimal("500"))
        self.assertEqual(mars["rake"], Decimal("10.00"))
        self.assertEqual(mars["winner"], Decimal("390.00"))
        self.assertEqual(mars["loser"], Decimal("0.00"))
        self.assertEqual(oin["winner"] + oin["loser"] + oin["rake"], Decimal("400.00"))

    def test_mars_when_the_loser_has_not_borne_off(self):
        pos = Position(_pile({}), _pile({12: 15}), 15, 0)
        self.assertEqual(result_kind(pos, WHITE), "mars")
        pos_oin = Position(_pile({}), _pile({12: 14}), 15, 1)
        self.assertEqual(result_kind(pos_oin, WHITE), "oin")

    def test_seed_replays_the_same_dice(self):
        match = Match.start(seed="nardy-test-seed", table_id="table-1")
        self.assertNotEqual(match.start_white, match.start_black)
        self.assertTrue(verify_log(match))
        again = Match.from_dict(match.to_dict(), seed=match.seed, table_id=match.table_id, client_seed=match.client_seed)
        self.assertEqual(again.moves(), match.moves())

    def test_random_games_keep_fifteen_checkers_and_finish(self):
        rng = random.Random(7)
        for _ in range(3):
            pos = initial_position()
            first = [True, True]
            turn = WHITE
            finished = False
            for _turn_no in range(800):
                if pos.white_off == 15 or pos.black_off == 15:
                    finished = True
                    break
                dice = (rng.randint(1, 6), rng.randint(1, 6))
                options = legal_moves(pos, turn, dice, first_roll=first[turn])
                move = rng.choice(options)
                pos = apply_steps(pos, turn, move) if move else pos
                self.assertTrue(checkers_ok(pos))
                first[turn] = False
                turn = BLACK if turn == WHITE else WHITE
            self.assertTrue(finished, "партия не кончилась за 800 ходов")


class SpectatorView(unittest.TestCase):
    def test_stranger_sees_the_board_without_seed_or_moves(self):
        from casino_nardy_table import _view

        match = Match.start(seed="secret-seed-value", table_id="n-watch")
        self.assertTrue(match.moves())
        table = {
            "table_id": "n-watch",
            "status": "running",
            "stake_rub": Decimal("100"),
            "white_user_id": 11,
            "black_user_id": 22,
            "state_version": 3,
            "commit_hash": "commit",
            "client_seed": "focuspay-nardy",
            "server_seed": "secret-seed-value",
            "seed_revealed_at": None,
            "action_deadline_at": None,
            "game_state": match.to_dict(),
        }
        view = _view(table, None)
        self.assertIsNone(view["your_side"])
        self.assertIsNone(view["server_seed"])
        self.assertEqual(view["legal"], [])
        self.assertEqual(len(view["points"]), 24)
        self.assertIsNotNone(view["dice"])
        on_turn = 11 if match.turn == WHITE else 22
        side = "white" if match.turn == WHITE else "black"
        seated = _view(table, on_turn)
        self.assertEqual(seated["your_side"], side)
        self.assertTrue(seated["legal"])
        self.assertIsNone(seated["server_seed"])


if __name__ == "__main__":
    unittest.main()
