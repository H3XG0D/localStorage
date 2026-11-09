"""Owner analytics: wallet payout and BUY network fee expenses."""
import unittest

from services.owner_analytics import money_period_with_expenses


class OwnerWalletPayoutExpenseTests(unittest.TestCase):
    def test_net_profit_subtracts_review_and_wallet(self):
        m = money_period_with_expenses(
            deals=10,
            turnover=100_000.0,
            profit=5_000.0,
            review_bonus=200.0,
            wallet_payout=2_500.0,
        )
        self.assertEqual(m.review_bonus_rub, 200.0)
        self.assertEqual(m.wallet_payout_rub, 2_500.0)
        self.assertEqual(m.net_profit_rub, 2_300.0)

    def test_net_profit_subtracts_buy_network_fee(self):
        m = money_period_with_expenses(
            deals=5,
            turnover=50_000.0,
            profit=3_000.0,
            review_bonus=0.0,
            wallet_payout=0.0,
            buy_network_fee=150.0,
        )
        self.assertEqual(m.buy_network_fee_rub, 150.0)
        self.assertEqual(m.net_profit_rub, 2_850.0)

    def test_net_profit_subtracts_all_expenses(self):
        m = money_period_with_expenses(
            deals=5,
            turnover=50_000.0,
            profit=3_000.0,
            review_bonus=100.0,
            wallet_payout=200.0,
            buy_network_fee=50.0,
        )
        self.assertEqual(m.net_profit_rub, 2_650.0)

    def test_net_profit_subtracts_accruals(self):
        m = money_period_with_expenses(
            deals=5,
            turnover=50_000.0,
            profit=3_000.0,
            review_bonus=0.0,
            cashback_accrual=100.0,
            referral_accrual=50.0,
            partner_accrual=200.0,
        )
        self.assertEqual(m.cashback_accrual_rub, 100.0)
        self.assertEqual(m.referral_accrual_rub, 50.0)
        self.assertEqual(m.partner_accrual_rub, 200.0)
        self.assertEqual(m.net_profit_rub, 2_650.0)


if __name__ == "__main__":
    unittest.main()
