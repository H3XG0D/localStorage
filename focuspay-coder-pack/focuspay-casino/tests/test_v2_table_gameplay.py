import unittest

from games import v2_table_gameplay as gameplay


class V2TableGameplayTests(unittest.TestCase):
    def test_apply_roll_and_leader_detection(self) -> None:
        state = {"seat_nos": [1, 2], "rolls": {}}
        state = gameplay.apply_roll(state, seat_no=1, roll_index=0, value=4, required_rolls=1)
        state = gameplay.apply_roll(state, seat_no=2, roll_index=0, value=6, required_rolls=1)
        totals = gameplay.seat_totals(state["rolls"], [1, 2], 1)
        self.assertEqual(totals, {1: 4, 2: 6})
        self.assertEqual(gameplay.leader_seat_nos(totals), [2])
        self.assertEqual(gameplay.outcome_kind_for_totals(totals), "winner")

    def test_tie_break_clears_only_leader_rolls(self) -> None:
        state = {
            "seat_nos": [1, 2, 3],
            "rolls": {"s1r0": 5, "s2r0": 5, "s3r0": 1},
        }
        leaders = gameplay.leader_seat_nos(gameplay.seat_totals(state["rolls"], [1, 2, 3], 1))
        self.assertEqual(leaders, [1, 2])
        next_state = gameplay.tie_break_state(state, leaders)
        self.assertEqual(next_state["phase"], "tie_break")
        self.assertEqual(next_state["rolls"], {"s3r0": 1})
        next_state = gameplay.apply_roll(next_state, seat_no=1, roll_index=0, value=3, required_rolls=1)
        self.assertEqual(next_state["phase"], "tie_break")
        next_state = gameplay.apply_roll(next_state, seat_no=2, roll_index=0, value=4, required_rolls=1)
        self.assertEqual(next_state["phase"], "scoring")
        self.assertEqual(gameplay.occupied_seat_nos(next_state), [1, 2])
        self.assertEqual(gameplay.leader_seat_nos(gameplay.seat_totals(next_state["rolls"], [1, 2], 1)), [2])


if __name__ == "__main__":
    unittest.main()
