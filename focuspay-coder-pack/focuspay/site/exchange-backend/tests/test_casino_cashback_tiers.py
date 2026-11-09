from decimal import Decimal
import unittest

from casino_cashback_tiers import cashback_amount, cashback_percent_for_wager
from casino_tier_config import DEFAULT_CASHBACK_VOLUME_TIERS


class CasinoCashbackTierTests(unittest.TestCase):
    def test_low_volume_uses_two_percent_cashback(self):
        self.assertEqual(cashback_percent_for_wager("185"), Decimal("2"))
        self.assertEqual(cashback_amount("185", "160"), Decimal("3.20"))

    def test_higher_volume_steps_up_cashback(self):
        self.assertEqual(cashback_percent_for_wager("50000"), Decimal("5"))
        self.assertEqual(cashback_percent_for_wager("100000"), Decimal("7"))
        self.assertEqual(cashback_percent_for_wager("500000"), Decimal("15"))

    def test_custom_tier_grid_can_be_passed_explicitly(self):
        tiers = DEFAULT_CASHBACK_VOLUME_TIERS[:2]
        self.assertEqual(cashback_percent_for_wager("60000", tiers), Decimal("5"))


if __name__ == "__main__":
    unittest.main()
