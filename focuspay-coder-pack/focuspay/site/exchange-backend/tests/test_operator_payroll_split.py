from decimal import Decimal
import unittest

from operator_payroll_split import (
    assigned_operator_ids_for_role,
    resolve_role_pair_shares,
    resolve_shift_role_assignments,
    split_pool,
)


def _lines_for(result, role):
    return [line for line in result["lines"] if line["role"] == role]


class OperatorPayrollSplitTests(unittest.TestCase):
    def test_client_only_operator_takes_bot_client_pool_when_dual_covers_finance(self):
        ids = assigned_operator_ids_for_role(
            [
                {"operator_id": 9, "operator_roles": ["client"]},
                {
                    "operator_id": 2,
                    "operator_role": "client",
                    "operator_roles": ["client", "finance"],
                },
            ],
            "client",
        )
        self.assertEqual(ids, [9])

    def test_dual_role_operator_fills_missing_finance_role(self):
        assignments = resolve_shift_role_assignments([
            {"operator_id": 1, "operator_roles": ["client"]},
            {
                "operator_id": 2,
                "operator_role": "client",
                "operator_roles": ["client", "finance"],
            },
        ])
        by_id = {item["operator_id"]: item for item in assignments}
        self.assertEqual(by_id[1]["assigned_roles"], ["client"])
        self.assertEqual(by_id[2]["assigned_roles"], ["finance"])
        self.assertEqual(by_id[2]["assignment_reason"], "missing_role")

    def test_single_dual_role_operator_covers_both_without_two_payees(self):
        assignments = resolve_shift_role_assignments([
            {
                "operator_id": 7,
                "operator_role": "client",
                "operator_roles": ["client", "finance"],
            },
        ])
        self.assertEqual(assignments[0]["assigned_roles"], ["client", "finance"])

    def test_shift_rows_must_use_operator_id_key(self):
        """Claim flow maps DB rows via operator_id; bare `id` breaks lookup."""
        row = {"operator_id": 3, "operator_role": "client", "operator_roles": ["client"]}
        item = resolve_shift_role_assignments([row])[0]
        self.assertEqual(item["operator_id"], 3)
        self.assertIn("client", item["assigned_roles"])

    def test_grade_pair_share_examples(self):
        cases = (
            ("trainee", "senior", Decimal("20"), Decimal("80")),
            ("junior", "senior", Decimal("30"), Decimal("70")),
            ("senior", "senior", Decimal("40"), Decimal("60")),
        )
        for client_grade, finance_grade, expected_client, expected_finance in cases:
            result = resolve_role_pair_shares(
                [{"operator_id": 1, "role": "client", "grade": client_grade}],
                [{"operator_id": 2, "role": "finance", "grade": finance_grade}],
                30,
            )
            self.assertEqual(result["client_operator_share_percent"], expected_client)
            self.assertEqual(result["finance_operator_share_percent"], expected_finance)
            self.assertEqual(result["mode"], "grade_pair")

    def test_shift_distribution_fund_share_follows_finance_grade_advantage(self):
        role_shares = resolve_role_pair_shares(
            [{"operator_id": 1, "role": "client", "grade": "trainee", "weight": 1}],
            [{"operator_id": 2, "role": "finance", "grade": "senior", "weight": 1}],
            30,
        )
        client_share = role_shares["client_operator_share_percent"]
        finance_share = role_shares["finance_operator_share_percent"]
        self.assertEqual(client_share, Decimal("20"))
        self.assertEqual(finance_share, Decimal("80"))

        participants = [
            {"operator_id": 1, "role": "client", "grade": "trainee", "weight": 1},
            {"operator_id": 2, "role": "finance", "grade": "senior", "weight": 1},
        ]
        totals = {"client": Decimal("1"), "finance": Decimal("1")}
        fund_shares = {}
        for item in participants:
            role = item["role"]
            role_share = Decimal("100")
            fund_shares[item["operator_id"]] = role_share * (
                client_share if role == "client" else finance_share
            ) / Decimal("100")
        self.assertEqual(fund_shares[1], Decimal("20"))
        self.assertEqual(fund_shares[2], Decimal("80"))

    def test_missing_role_uses_legacy_fallback(self):
        result = resolve_role_pair_shares(
            [{"operator_id": 1, "role": "client", "grade": "trainee"}],
            [],
            30,
        )
        self.assertEqual(result["client_operator_share_percent"], Decimal("30"))
        self.assertEqual(result["finance_operator_share_percent"], Decimal("70"))
        self.assertEqual(result["mode"], "fallback")

    def test_pair_share_uses_grade_levels_not_payout_coefficients(self):
        result = resolve_role_pair_shares(
            [
                {"operator_id": 1, "role": "client", "grade": "trainee", "weight": 0.75},
                {"operator_id": 2, "role": "client", "grade": "senior", "weight": 1.25},
            ],
            [{"operator_id": 3, "role": "finance", "grade": "senior", "weight": 0.75}],
            30,
        )
        self.assertEqual(result["client_operator_share_percent"], Decimal("30"))
        self.assertEqual(result["finance_operator_share_percent"], Decimal("70"))

    def test_grade_pair_share_is_used_for_order_pool(self):
        result = split_pool(
            1000,
            30,
            80,
            source="telegram_auto",
            client_participants=[{"operator_id": 1, "role": "client", "grade": "trainee"}],
            finance_participants=[{"operator_id": 2, "role": "finance", "grade": "senior"}],
        )
        self.assertEqual(result["client_pool_rub"], Decimal("240.00"))
        self.assertEqual(result["finance_pool_rub"], Decimal("60.00"))

    def test_manual_order_assigns_client_and_finance_pools_to_their_roles(self):
        result = split_pool(
            1000,
            30,
            30,
            source="manual_operator",
            intake_operator_id=11,
            finance_participants=[{"operator_id": 22, "grade": "senior", "weight": 1.25}],
        )

        self.assertEqual(result["client_pool_rub"], Decimal("90.00"))
        self.assertEqual(result["finance_pool_rub"], Decimal("210.00"))
        self.assertEqual(_lines_for(result, "client")[0]["operator_id"], 11)
        self.assertEqual(_lines_for(result, "finance")[0]["operator_id"], 22)

    def test_grade_weights_split_pool_exactly(self):
        result = split_pool(
        1000,
        30,
        50,
        source="telegram_auto",
        client_participants=[
            {"operator_id": 1, "role": "client", "grade": "trainee", "weight": "0.75"},
            {"operator_id": 2, "role": "client", "grade": "junior", "weight": "1"},
            {"operator_id": 3, "role": "client", "grade": "senior", "weight": "1.25"},
        ],
        finance_participants=[{"operator_id": 4, "role": "finance", "weight": 1}],
        )

        client_lines = _lines_for(result, "client")
        self.assertEqual([line["amount_rub"] for line in client_lines], [
            Decimal("37.50"),
            Decimal("50.00"),
            Decimal("62.50"),
        ])
        self.assertEqual(sum((line["amount_rub"] for line in result["lines"]), Decimal("0")), result["pool_rub"])

    def test_empty_role_is_kept_as_unassigned_pool(self):
        result = split_pool(1000, 30, 30, source="telegram_auto", finance_participants=[9])

        unassigned = [line for line in result["lines"] if line["role"] == "unassigned"]
        self.assertEqual(len(unassigned), 1)
        self.assertEqual(unassigned[0]["unassigned_for"], "client")
        self.assertEqual(unassigned[0]["amount_rub"], result["client_pool_rub"])

    def test_rounding_remainder_is_assigned_without_losing_a_kopeck(self):
        result = split_pool(101, 30, "33.3", client_participants=[1, 2, 3])

        lines = _lines_for(result, "client")
        self.assertEqual([line["amount_rub"] for line in lines], [
            Decimal("3.36"),
            Decimal("3.36"),
            Decimal("3.37"),
        ])
        self.assertEqual(sum((line["amount_rub"] for line in result["lines"]), Decimal("0")), result["pool_rub"])

    def test_invalid_or_duplicate_participants_are_rejected(self):
        with self.assertRaises(ValueError):
            split_pool(100, 101, 50, client_participants=[1])
        with self.assertRaises(ValueError):
            split_pool(100, 30, 50, client_participants=[{"operator_id": 1, "weight": 0}])
        with self.assertRaises(ValueError):
            split_pool(100, 30, 50, client_participants=[1, 1])


if __name__ == "__main__":
    unittest.main()
