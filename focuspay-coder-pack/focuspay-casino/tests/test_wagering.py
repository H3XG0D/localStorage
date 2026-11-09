import unittest

from wagering import (
    deposit_wagering_for_amount,
    deposit_wagering_preview,
    deposit_wagering_rules,
    help_wagering_line,
    wagering_hint,
)


class WageringHintTests(unittest.TestCase):
    def test_deposit_preview_uses_house_take_not_raw_percent_of_deposit(self):
        house, stake = deposit_wagering_preview(
            1000.0, wagering_percent=21.0, commission_percent=15.0
        )
        self.assertEqual(house, 210.0)
        self.assertEqual(stake, 1400.0)

    def test_shows_stake_needed_and_remaining_house_take(self):
        text = wagering_hint(
            {
                "locked_rub": "1000.00",
                "remaining_rub": "1400.00",
                "remaining_stake_rub": "1400.00",
                "remaining_house_take_rub": "210.00",
                "commission_rate_percent": "15.00",
            },
            currency_symbol="₽",
        )

        self.assertIn("1000.00 ₽", text)
        self.assertIn("1400.00 ₽", text)
        self.assertIn("210.00 ₽", text)
        self.assertIn("комиссии с ваших ставок", text)
        self.assertIn("Средства всё это время остаются доступны в играх.", text)
        self.assertNotIn("сыграйте ещё примерно на", text.lower())

    def test_legacy_payload_still_shows_remaining_as_stake(self):
        text = wagering_hint(
            {"locked_rub": "150.25", "remaining_rub": "31.55"},
            currency_symbol="₽",
        )

        self.assertIn("150.25 ₽", text)
        self.assertIn("31.55 ₽", text)
        self.assertNotIn("комиссии с ваших ставок", text)

    def test_shows_reduced_commission_after_completion(self):
        text = wagering_hint(
            {"locked_rub": "150.25", "remaining_rub": "0"},
            currency_symbol="₽",
        )

        self.assertIn("Отыгрыш выполнен", text)
        self.assertIn("5%", text)

    def test_ignores_invalid_status(self):
        self.assertEqual(
            wagering_hint(
                {"locked_rub": "not-a-number", "remaining_rub": "31.55"},
                currency_symbol="₽",
            ),
            "",
        )

    def test_deposit_copy_explains_house_take_and_stake(self):
        rules = deposit_wagering_rules(
            wagering_percent=21.0, commission_percent=15.0, currency_symbol="₽"
        )
        self.assertIn("21% плюса", rules)
        self.assertIn("210.00 ₽ комиссии", rules)
        self.assertIn("1400.00 ₽ ставок", rules)
        amount = deposit_wagering_for_amount(
            1000.0,
            wagering_percent=21.0,
            commission_percent=15.0,
            currency_symbol="₽",
        )
        self.assertIn("210.00 ₽", amount)
        self.assertIn("1400.00 ₽", amount)
        self.assertIn(
            "1400.00 ₽ ставок",
            help_wagering_line(
                wagering_percent=21.0,
                commission_percent=15.0,
                currency_symbol="₽",
            ),
        )


if __name__ == "__main__":
    unittest.main()
