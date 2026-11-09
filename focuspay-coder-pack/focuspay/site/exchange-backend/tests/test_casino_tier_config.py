from decimal import Decimal
import unittest

from casino_tier_config import (
    DEFAULT_CASHBACK_VOLUME_TIERS,
    DEFAULT_COMMISSION_VOLUME_TIERS,
    parse_cashback_volume_tiers,
    parse_commission_volume_tiers,
    resolve_cashback_percent,
    resolve_commission_volume_tier,
)


class CasinoTierConfigTests(unittest.TestCase):
    def test_default_cashback_tiers_start_at_two_percent(self):
        self.assertEqual(resolve_cashback_percent(DEFAULT_CASHBACK_VOLUME_TIERS, "185"), Decimal("2"))
        self.assertEqual(resolve_cashback_percent(DEFAULT_CASHBACK_VOLUME_TIERS, "50000"), Decimal("5"))
        self.assertEqual(resolve_cashback_percent(DEFAULT_CASHBACK_VOLUME_TIERS, "150000"), Decimal("7"))

    def test_default_commission_tiers_follow_wagering_and_volume(self):
        tier = resolve_commission_volume_tier(DEFAULT_COMMISSION_VOLUME_TIERS, "0")
        self.assertEqual(tier.active_rate, Decimal("15"))
        self.assertEqual(tier.complete_rate, Decimal("5"))
        tier = resolve_commission_volume_tier(DEFAULT_COMMISSION_VOLUME_TIERS, "100000")
        self.assertEqual(tier.active_rate, Decimal("10"))
        self.assertEqual(tier.complete_rate, Decimal("3"))

    def test_parse_and_validate_custom_grids(self):
        cashback = parse_cashback_volume_tiers(
            [{"min_wager_rub": 0, "percent": 3}, {"min_wager_rub": 1000, "percent": 6}]
        )
        self.assertEqual(resolve_cashback_percent(cashback, 999), Decimal("3"))
        commission = parse_commission_volume_tiers(
            [{"min_wager_rub": 0, "active_rate": 14, "complete_rate": 4}]
        )
        self.assertEqual(resolve_commission_volume_tier(commission, 0).complete_rate, Decimal("4"))


if __name__ == "__main__":
    unittest.main()
