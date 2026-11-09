import unittest
from unittest.mock import patch

from partner_referral_profit import partner_service_profit_metrics, profit_by_campaign_id


class TestPartnerServiceProfitMetrics(unittest.TestCase):
    def test_net_is_gross_minus_accrued(self):
        result = partner_service_profit_metrics(gross=1000, accrued=150)
        self.assertEqual(result["service_profit_gross_rub"], 1000.0)
        self.assertEqual(result["service_profit_net_rub"], 850.0)

    def test_zero_values(self):
        result = partner_service_profit_metrics(gross=0, accrued=0)
        self.assertEqual(result["service_profit_gross_rub"], 0.0)
        self.assertEqual(result["service_profit_net_rub"], 0.0)


class TestProfitByCampaignId(unittest.TestCase):
    @patch("partner_referral_profit._gross_profit_from_orders")
    def test_groups_orders_by_campaign(self, mock_compute):
        mock_compute.side_effect = lambda orders: sum(float(o["fiat_amount"]) for o in orders)

        rows = [
            {"campaign_id": 1, "fiat_amount": 100},
            {"campaign_id": 1, "fiat_amount": 50},
            {"campaign_id": 2, "fiat_amount": 200},
        ]
        result = profit_by_campaign_id(rows)

        self.assertEqual(result[1], 150.0)
        self.assertEqual(result[2], 200.0)
        self.assertEqual(mock_compute.call_count, 2)


if __name__ == "__main__":
    unittest.main()
