"""Тесты расчёта внештатных обменов.

Базовый пример (receive_fee=0, operator 10%):
  amount_rub=10000, markup=20%, card_fee=12%, usdt_rate=90, operator_percent=10

  client_pays = 10000 * 1.20 = 12000
  payfast_fee = 12000 * 0.12 = 1440
  net_profit_rub = 12000 - 1440 - 10000 = 560
  operator_earnings = 560 * 0.10 = 56
  principal_usdt = 10000 / 90 = 111.111111
  reward_usdt = 0
  total_credit_usdt = principal_usdt
  house_profit_usd = (560 - 56) / 90 = 5.6

Вывод:
  gross=500, fee=3 → net=497
"""
from __future__ import annotations

import unittest

from external_exchange_calc import DealCalcResult, PayoutCalcResult, calc_deal, calc_payout, preview_deal, preview_payout

RATE = 90.0
MARKUP = 20.0
CARD_FEE = 0.12
RCV_FEE = 0.0
OP_PCT = 10.0


class TestCalcDeal(unittest.TestCase):

    def _deal(
        self,
        amount_rub=10000.0,
        rate=RATE,
        markup=MARKUP,
        fee=CARD_FEE,
        op_pct=OP_PCT,
        rcv=RCV_FEE,
    ):
        return calc_deal(
            amount_rub,
            rate,
            markup_pct=markup,
            card_fee_pct=fee,
            receive_fee_usd=rcv,
            operator_percent=op_pct,
        )

    def test_client_pays(self):
        r = self._deal()
        self.assertAlmostEqual(r.client_pays_rub, 12000.0, places=2)

    def test_payfast_fee(self):
        r = self._deal()
        self.assertAlmostEqual(r.payfast_fee_rub, 1440.0, places=2)

    def test_net_profit_rub(self):
        r = self._deal()
        self.assertAlmostEqual(r.net_profit_rub, 560.0, places=2)

    def test_operator_earnings_rub(self):
        r = self._deal()
        self.assertAlmostEqual(r.operator_earnings_rub, 56.0, places=2)

    def test_reward_usdt_zero(self):
        r = self._deal()
        self.assertEqual(r.reward_usdt, 0.0)

    def test_principal_usdt(self):
        r = self._deal()
        self.assertAlmostEqual(r.principal_usdt, 111.111111, places=4)

    def test_total_credit_equals_principal(self):
        r = self._deal()
        self.assertAlmostEqual(r.total_credit_usdt, r.principal_usdt, places=6)

    def test_house_profit_usd(self):
        r = self._deal()
        expected = round((560.0 - 56.0) / RATE - RCV_FEE, 6)
        self.assertAlmostEqual(r.house_profit_usd, expected, places=4)
        self.assertGreater(r.house_profit_usd, 0)

    def test_admin_deal_no_operator(self):
        r = self._deal(op_pct=0.0)
        self.assertEqual(r.operator_earnings_rub, 0.0)
        self.assertAlmostEqual(r.house_profit_usd, round(560.0 / RATE, 6), places=4)

    def test_zero_reward_when_zero_percent(self):
        r = self._deal(op_pct=0.0)
        self.assertEqual(r.reward_usdt, 0.0)

    def test_custom_markup_15pct(self):
        r = calc_deal(
            10000,
            RATE,
            markup_pct=15.0,
            card_fee_pct=CARD_FEE,
            receive_fee_usd=RCV_FEE,
            operator_percent=0.0,
        )
        self.assertAlmostEqual(r.client_pays_rub, 11500.0, places=2)

    def test_zero_rate_raises(self):
        with self.assertRaises(ValueError):
            self._deal(rate=0.0)

    def test_negative_amount_raises(self):
        with self.assertRaises(ValueError):
            self._deal(amount_rub=-100.0)

    def test_large_deal(self):
        r = self._deal(amount_rub=100_000.0)
        self.assertGreater(r.principal_usdt, 1111.0)
        self.assertGreater(r.operator_earnings_rub, 0)

    def test_returns_dataclass(self):
        r = self._deal()
        self.assertIsInstance(r, DealCalcResult)

    def test_card_fee_14_pct(self):
        r = self._deal(fee=0.14)
        self.assertAlmostEqual(r.payfast_fee_rub, 12000.0 * 0.14, places=2)
        self.assertAlmostEqual(r.net_profit_rub, 12000.0 - 12000.0 * 0.14 - 10000.0, places=2)


class TestMarkupModes(unittest.TestCase):
    def test_on_deal_1000_at_20pct(self):
        r = calc_deal(
            1000,
            RATE,
            markup_pct=20.0,
            markup_mode="on_deal",
            card_fee_pct=CARD_FEE,
            receive_fee_usd=RCV_FEE,
            operator_percent=0.0,
        )
        self.assertAlmostEqual(r.amount_rub, 1000.0, places=2)
        self.assertAlmostEqual(r.client_pays_rub, 1200.0, places=2)
        self.assertEqual(r.markup_mode, "on_deal")

    def test_on_turnover_1000_at_15pct(self):
        r = calc_deal(
            1000,
            RATE,
            markup_pct=15.0,
            markup_mode="on_turnover",
            card_fee_pct=CARD_FEE,
            receive_fee_usd=RCV_FEE,
            operator_percent=0.0,
        )
        self.assertAlmostEqual(r.client_pays_rub, 1000.0, places=2)
        self.assertAlmostEqual(r.amount_rub, 850.0, places=2)
        self.assertAlmostEqual(r.principal_usdt, 850.0 / RATE, places=4)

    def test_on_turnover_1000_at_20pct(self):
        r = calc_deal(
            1000,
            RATE,
            markup_pct=20.0,
            markup_mode="on_turnover",
            card_fee_pct=CARD_FEE,
            receive_fee_usd=RCV_FEE,
            operator_percent=0.0,
        )
        self.assertAlmostEqual(r.client_pays_rub, 1000.0, places=2)
        self.assertAlmostEqual(r.amount_rub, 800.0, places=2)


class TestCalcPayout(unittest.TestCase):

    def test_basic_500_minus_3(self):
        r = calc_payout(500.0, fee_usd=3.0)
        self.assertAlmostEqual(r.net_usd, 497.0, places=4)
        self.assertAlmostEqual(r.fee_usd, 3.0, places=4)
        self.assertAlmostEqual(r.gross_usd, 500.0, places=4)

    def test_returns_dataclass(self):
        r = calc_payout(100.0, fee_usd=3.0)
        self.assertIsInstance(r, PayoutCalcResult)

    def test_zero_gross_raises(self):
        with self.assertRaises(ValueError):
            calc_payout(0.0, fee_usd=3.0)

    def test_negative_gross_raises(self):
        with self.assertRaises(ValueError):
            calc_payout(-50.0, fee_usd=3.0)

    def test_fee_gte_gross_raises(self):
        with self.assertRaises(ValueError):
            calc_payout(3.0, fee_usd=3.0)

    def test_fee_gt_gross_raises(self):
        with self.assertRaises(ValueError):
            calc_payout(2.99, fee_usd=3.0)

    def test_negative_fee_raises(self):
        with self.assertRaises(ValueError):
            calc_payout(100.0, fee_usd=-1.0)

    def test_zero_fee(self):
        r = calc_payout(100.0, fee_usd=0.0)
        self.assertAlmostEqual(r.net_usd, 100.0, places=4)


class TestPreviewDeal(unittest.TestCase):

    def test_returns_dict(self):
        result = preview_deal(
            10000.0,
            RATE,
            markup_pct=MARKUP,
            card_fee_pct=CARD_FEE,
            receive_fee_usd=RCV_FEE,
            operator_percent=OP_PCT,
        )
        self.assertIsNotNone(result)
        self.assertIn("total_credit_usdt", result)
        self.assertIn("house_profit_usd", result)
        self.assertIn("operator_earnings_rub", result)
        self.assertAlmostEqual(result["operator_earnings_rub"], 56.0, places=1)
        self.assertEqual(result["reward_usdt"], 0.0)
        self.assertIn("usdt_rate_rub", result)

    def test_zero_rate_returns_none(self):
        result = preview_deal(
            10000.0,
            0.0,
            markup_pct=MARKUP,
            card_fee_pct=CARD_FEE,
            receive_fee_usd=RCV_FEE,
            operator_percent=OP_PCT,
        )
        self.assertIsNone(result)

    def test_negative_amount_returns_none(self):
        result = preview_deal(
            -100.0,
            RATE,
            markup_pct=MARKUP,
            card_fee_pct=CARD_FEE,
            receive_fee_usd=RCV_FEE,
            operator_percent=OP_PCT,
        )
        self.assertIsNone(result)


class TestPreviewPayout(unittest.TestCase):
    MARKET = {"usdt": 90.0, "btc": 9_000_000.0, "ltc": 9_000.0}

    def test_btc_conversion(self):
        r = preview_payout(500.0, "btc", self.MARKET, fee_usd=3.0, payout_threshold_usd=500.0)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r["net_usd"], 497.0, places=4)
        self.assertAlmostEqual(r["crypto_rate_usd"], 100_000.0, places=0)
        self.assertAlmostEqual(r["crypto_amount"], 497.0 / 100_000.0, places=6)

    def test_usdt_is_one_to_one(self):
        r = preview_payout(100.0, "usdt", self.MARKET, fee_usd=3.0, payout_threshold_usd=500.0)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r["crypto_amount"], 97.0, places=4)


if __name__ == "__main__":
    unittest.main()
