"""Срок горячего кошелька: темп 7 дней, порог, пустой остаток."""
from __future__ import annotations

import unittest

from hot_wallet_runway import assemble_runway, days_left, days_phrase, hours_left, hours_phrase


class DaysLeftTests(unittest.TestCase):
    def test_no_outflow_has_no_runway(self):
        self.assertIsNone(days_left(0.01, 0))
        self.assertEqual(days_phrase(None), "темпа нет")

    def test_under_a_day(self):
        self.assertEqual(days_phrase(0.4), "меньше суток")

    def test_rounds_to_whole_days(self):
        self.assertEqual(days_left(0.03, 0.07), 3)
        self.assertEqual(days_phrase(3), "хватит ≈ 3 дн")


class HoursPhraseTests(unittest.TestCase):
    def test_no_pace(self):
        self.assertIsNone(hours_left(None))
        self.assertEqual(hours_phrase(None), "темпа нет")

    def test_under_an_hour(self):
        self.assertEqual(hours_phrase(0.4), "меньше часа")

    def test_same_pace_as_days(self):
        self.assertEqual(hours_left(3), 72)
        self.assertEqual(hours_phrase(72), "хватит ≈ 72 ч")
        self.assertEqual(hours_phrase(9.6), "хватит ≈ 10 ч")


class AssembleRunwayTests(unittest.TestCase):
    def test_coin_line_uses_seven_day_crypto_pace(self):
        report = assemble_runway(
            coins=[{"coin": "btc", "spendable": 0.03, "rate_rub": 1_000_000}],
            outflow={"btc": {"buy_crypto": 0.07, "buy_rub": 70_000, "withdraw_rub": 0, "deals": 2}},
            min_hot_balance_rub=50_000,
            signer_ok=True,
        )
        btc = report["coins"][0]
        self.assertEqual(btc["days_left"], 3)
        self.assertEqual(btc["hours_left"], 72)
        self.assertEqual(btc["hours_phrase"], "хватит ≈ 72 ч")
        self.assertEqual(btc["phrase"], "хватит ≈ 3 дн")
        self.assertIn("BTC 0.03", btc["line"])
        self.assertIn("30 000 ₽", btc["line"])
        self.assertIn("хватит ≈ 3 дн", btc["line"])

    def test_withdrawal_rub_counts_toward_coin_pace(self):
        report = assemble_runway(
            coins=[{"coin": "btc", "spendable": 0.01, "rate_rub": 1_000_000}],
            outflow={"btc": {"buy_crypto": 0, "buy_rub": 0, "withdraw_rub": 7_000, "deals": 1}},
            min_hot_balance_rub=0,
            signer_ok=True,
        )
        btc = report["coins"][0]
        self.assertAlmostEqual(btc["outflow_crypto_7d"], 0.007)
        self.assertEqual(btc["days_left"], 10)
        self.assertEqual(btc["phrase"], "хватит ≈ 10 дн")

    def test_zero_pace_does_not_invent_days(self):
        report = assemble_runway(
            coins=[{"coin": "ltc", "spendable": 2, "rate_rub": 5_000}],
            outflow={},
            min_hot_balance_rub=0,
            signer_ok=True,
        )
        ltc = next(c for c in report["coins"] if c["coin"] == "ltc")
        self.assertIsNone(ltc["days_left"])
        self.assertEqual(ltc["phrase"], "темпа нет")

    def test_below_floor_stops_new_auto_orders(self):
        report = assemble_runway(
            coins=[
                {"coin": "btc", "spendable": 0.0001, "rate_rub": 100_000_000},
                {"coin": "ltc", "spendable": 10, "rate_rub": 1_000},
            ],
            outflow={},
            min_hot_balance_rub=50_000,
            signer_ok=True,
        )
        self.assertEqual(report["total_rub"], 20_000)
        self.assertTrue(report["below_floor"])
        self.assertIn("ниже порога", report["floor_phrase"])
        self.assertIn("50 000", report["floor_phrase"])
        self.assertIn("не стартуют", report["floor_phrase"])

    def test_days_until_floor_uses_ruble_pace(self):
        report = assemble_runway(
            coins=[
                {"coin": "btc", "spendable": 0.03, "rate_rub": 1_000_000},
                {"coin": "ltc", "spendable": 20, "rate_rub": 2_500},
            ],
            outflow={"btc": {"buy_crypto": 0.021, "buy_rub": 21_000, "withdraw_rub": 0, "deals": 3}},
            min_hot_balance_rub=50_000,
            signer_ok=True,
        )
        self.assertEqual(report["total_rub"], 80_000)
        self.assertFalse(report["below_floor"])
        self.assertEqual(report["days_until_floor"], 10)
        self.assertIn("до порога", report["floor_phrase"])
        self.assertIn("хватит ≈ 10 дн", report["floor_phrase"])

    def test_empty_coin_with_pace_is_finished(self):
        report = assemble_runway(
            coins=[{"coin": "btc", "spendable": 0, "rate_rub": 1_000_000}],
            outflow={"btc": {"buy_crypto": 0.01, "buy_rub": 10_000, "withdraw_rub": 0, "deals": 1}},
            min_hot_balance_rub=0,
            signer_ok=True,
        )
        self.assertEqual(report["coins"][0]["phrase"], "кончились")
        self.assertEqual(report["coins"][0]["hours_phrase"], "кончились")

    def test_signer_down_is_not_reported_as_empty(self):
        report = assemble_runway(
            coins=[],
            outflow={"btc": {"buy_crypto": 0.01, "buy_rub": 10_000, "withdraw_rub": 0, "deals": 1}},
            min_hot_balance_rub=50_000,
            signer_ok=False,
        )
        self.assertFalse(report["available"])
        self.assertEqual(report["coins"][0]["phrase"], "нет данных")
        self.assertIsNone(report["coins"][0]["hours_left"])
        self.assertEqual(report["coins"][0]["hours_phrase"], "нет данных")
        self.assertNotEqual(report["coins"][0]["phrase"], "кончились")
        self.assertIn("не на связи", report["floor_phrase"])


if __name__ == "__main__":
    unittest.main()
