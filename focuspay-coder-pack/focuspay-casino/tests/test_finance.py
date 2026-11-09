from decimal import Decimal
import unittest

from finance import (
    calculate_head_to_head_settlement,
    setting_decimal,
    settlement_payout_rub,
)


class HeadToHeadSettlementTests(unittest.TestCase):
    def test_commission_is_charged_on_losing_stake(self):
        amounts = calculate_head_to_head_settlement(
            stake_per_player="100",
            commission_rate_percent="15.0",
        )

        self.assertEqual(amounts.stake_per_player, Decimal("100.00"))
        self.assertEqual(amounts.pot, Decimal("200.00"))
        self.assertEqual(amounts.commission, Decimal("15.00"))
        self.assertEqual(amounts.payout, Decimal("185.00"))

    def test_money_is_rounded_half_up_to_kopecks(self):
        amounts = calculate_head_to_head_settlement(
            stake_per_player="0.10",
            commission_rate_percent="5",
        )

        self.assertEqual(amounts.commission, Decimal("0.01"))
        self.assertEqual(amounts.payout, Decimal("0.19"))

    def test_nested_backend_setting_uses_whole_percent(self):
        value = setting_decimal(
            {"commission_rate": {"percent": 15.0}},
            key="commission_rate",
            nested_key="percent",
            default="10",
        )

        self.assertEqual(value, Decimal("15.0"))

    def test_invalid_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_head_to_head_settlement(
                stake_per_player="100",
                commission_rate_percent="101",
            )

    def test_settlement_payout_uses_trusted_backend_value(self):
        payout = settlement_payout_rub({"payout_rub": "185.00"})

        self.assertEqual(payout, Decimal("185.00"))

    def test_settlement_payout_rejects_missing_or_invalid_value(self):
        with self.assertRaises(ValueError):
            settlement_payout_rub({})
        with self.assertRaises(ValueError):
            settlement_payout_rub({"payout_rub": "0"})


if __name__ == "__main__":
    unittest.main()
