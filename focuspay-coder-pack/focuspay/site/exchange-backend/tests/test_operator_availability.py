import unittest

from operator_availability import evaluate_shift_gate, missing_operator_roles


class OperatorAvailabilityTests(unittest.TestCase):
    def test_requires_both_roles(self):
        self.assertEqual(
            missing_operator_roles([{"operator_roles": ["client"]}]),
            ("finance",),
        )
        self.assertEqual(
            missing_operator_roles([{"operator_roles": ["finance"]}]),
            ("client",),
        )

    def test_dual_role_operator_covers_both_roles(self):
        self.assertEqual(
            missing_operator_roles([
                {"operator_role": "client", "operator_roles": ["client", "finance"]},
            ]),
            (),
        )

    def test_legacy_operator_without_roles_is_client(self):
        self.assertEqual(missing_operator_roles([{"id": 1}]), ("finance",))
        self.assertEqual(
            missing_operator_roles([{"operator_role": "finance", "operator_roles": []}]),
            ("client",),
        )

    def test_active_covering_shift_allows_buy(self):
        gate = evaluate_shift_gate(
            [{"operator_roles": ["client", "finance"], "telegram_user_id": 111}]
        )
        self.assertTrue(gate.allow)
        self.assertEqual(gate.reason, "ok")
        self.assertEqual(gate.telegram_user_ids, (111,))

    def test_no_shift_blocks_buy(self):
        gate = evaluate_shift_gate([])
        self.assertFalse(gate.allow)
        self.assertEqual(gate.reason, "no_shift")
        self.assertEqual(gate.missing_roles, ("client", "finance"))

    def test_two_open_shifts_are_recognized_for_buy(self):
        gate = evaluate_shift_gate(
            [
                {"operator_roles": ["client"], "telegram_user_id": 111},
                {"operator_roles": ["finance"], "telegram_user_id": 222},
            ]
        )
        self.assertTrue(gate.allow)
        self.assertEqual(gate.active_count, 2)
        self.assertEqual(set(gate.telegram_user_ids), {111, 222})

    def test_username_is_not_treated_as_canonical_shift_id(self):
        gate = evaluate_shift_gate(
            [{"operator_roles": ["client", "finance"], "telegram_user_id": "Rrrrram"}]
        )
        self.assertTrue(gate.allow)
        self.assertEqual(gate.telegram_user_ids, ())
        self.assertEqual(gate.unbound_count, 1)

    def test_two_client_shifts_still_incomplete(self):
        gate = evaluate_shift_gate(
            [
                {"operator_roles": ["client"], "telegram_user_id": 111},
                {"operator_roles": ["client"], "telegram_user_id": 222},
            ]
        )
        self.assertFalse(gate.allow)
        self.assertEqual(gate.reason, "incomplete_shift")
        self.assertEqual(gate.missing_roles, ("finance",))
        self.assertEqual(set(gate.telegram_user_ids), {111, 222})


if __name__ == "__main__":
    unittest.main()
