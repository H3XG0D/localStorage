import unittest
from datetime import datetime,timezone
from scripts.recover_referral_attributions import rebuild_economics, digest
from services.economics_snapshot import build_economics_snapshot

class HistoricalEconomicsTests(unittest.TestCase):
    def order(self,**kwargs):
        return dict(dict(order_id='old',direction='buy',crypto='btc',fiat_amount=1200,crypto_amount=.001,rate=1200000,card_fee_pct=.12,cashback_applied_rub=0,manual_spread_pct=None,created_at=datetime(2026,8,1)),**kwargs)
    def test_historical_profit_uses_twenty_percent_and_recorded_fee(self):
        s=rebuild_economics(self.order(),build_economics_snapshot)
        self.assertAlmostEqual(s['service_profit_rub'],56)
        self.assertEqual(s['referral_recovery_policy'],'historical_20')
    def test_cutoff_uses_moscow_midnight(self):
        s=rebuild_economics(self.order(created_at=datetime(2026,8,16,21,tzinfo=timezone.utc)),build_economics_snapshot)
        self.assertEqual(s['buy_markup'],1.21)
    def test_manual_fee_policy_and_explicit_spread(self):
        o=self.order(created_at=datetime(2026,8,20),card_fee_pct=.14)
        self.assertEqual(rebuild_economics(o,build_economics_snapshot)['buy_markup'],1.22)
        o['manual_spread_pct']=18
        self.assertEqual(rebuild_economics(o,build_economics_snapshot)['buy_markup'],1.18)
    def test_missing_required_data_and_sell_are_not_guessed(self):
        for override in ({'rate':0},{'crypto_amount':0},{'direction':'sell'}):
            self.assertIsNone(rebuild_economics(self.order(**override),build_economics_snapshot))
    def test_plan_digest_changes_with_amount(self):
        self.assertNotEqual(digest({'amount':'1.00'}),digest({'amount':'1.01'}))
