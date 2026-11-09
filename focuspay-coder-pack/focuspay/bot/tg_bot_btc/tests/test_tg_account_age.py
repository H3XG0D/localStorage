"""Тесты оценки возраста TG-аккаунта по user_id."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from services.tg_account_age import estimate_age_days, estimate_creation_date


class TgAccountAgeTests(unittest.TestCase):
    def test_known_old_id(self):
        # ~2016 anchor zone
        created = estimate_creation_date(100_000_000)
        self.assertIsNotNone(created)
        assert created is not None
        self.assertEqual(created.tzinfo, timezone.utc)
        age = estimate_age_days(
            100_000_000,
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(age)
        assert age is not None
        self.assertGreater(age, 365 * 8)

    def test_very_new_id_under_7_days(self):
        # экстраполяция за последним якорем → «свежий»
        now = datetime(2025, 6, 15, tzinfo=timezone.utc)
        age = estimate_age_days(8_200_000_000, now=now)
        self.assertIsNotNone(age)
        assert age is not None
        self.assertLess(age, 7)

    def test_mid_range_reasonable(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        age = estimate_age_days(5_000_000_000, now=now)
        self.assertIsNotNone(age)
        assert age is not None
        # якорь ~2023-07 → ~3 года
        self.assertGreater(age, 900)
        self.assertLess(age, 1500)

    def test_invalid_id(self):
        self.assertIsNone(estimate_creation_date(0))
        self.assertIsNone(estimate_age_days(-1))


if __name__ == "__main__":
    unittest.main()
