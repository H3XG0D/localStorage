"""Regression for payout amounts displayed/recorded to eight decimal places."""
import unittest
from unittest.mock import patch

from services.buy_payout_validate import validate_buy_payout_crypto


class BuyPayoutRoundingTests(unittest.TestCase):
    def validate(self, amount, **overrides):
        order = dict(
            crypto="LTC", fiat_amount=3472, rate=5741.474412,
            crypto_amount=amount,
        )
        order.update(overrides)
        with patch("services.buy_payout_validate.buy_markup", return_value=1.2):
            return validate_buy_payout_crypto(order)

    def test_incident_rounded_amount_is_payable(self):
        self.assertEqual(self.validate(0.60472272), (True, None))

    def test_next_decimal_unit_is_still_blocked(self):
        self.assertEqual(
            self.validate(0.60472273), (False, "crypto_exceeds_paid")
        )

    def test_real_overpayment_is_blocked(self):
        self.assertEqual(self.validate(0.61), (False, "crypto_exceeds_paid"))

    def test_unrounded_and_rounded_down_amounts_remain_payable(self):
        for amount in (0.6047227159531231, 0.60472271):
            with self.subTest(amount=amount):
                self.assertEqual(self.validate(amount), (True, None))

    def test_cashback_and_discount_remain_part_of_coverage(self):
        self.assertEqual(
            self.validate(
                0.60472272, fiat_amount=3372,
                cashback_applied_rub=40, exchange_discount_applied_rub=60,
            ),
            (True, None),
        )

    def test_exact_cap_does_not_allow_one_extra_decimal_unit(self):
        self.assertEqual(
            self.validate(1.00000001, fiat_amount=100, rate=100),
            (False, "crypto_exceeds_paid"),
        )
