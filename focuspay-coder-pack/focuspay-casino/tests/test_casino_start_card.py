from datetime import datetime
from io import BytesIO
import unittest
from zoneinfo import ZoneInfo

from PIL import Image

from casino_start_card import (
    CARD_SIZE,
    build_card_data,
    countdown_to_next_monday_0600,
    generate_start_card,
)


class CasinoStartCardTests(unittest.TestCase):
    def test_generates_png_at_expected_size(self):
        card = generate_start_card(
            {"name": "Анна", "username": "anna"},
            {
                "available_rub": "1250.50",
                "wagering": {"remaining_rub": "100"},
                "current_week": {
                    "wager_rub": "5000",
                    "loss_rub": "700",
                    "cashback_percent": "3",
                    "estimated_cashback_rub": "21",
                },
            },
        )

        self.assertTrue(card.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(card)) as image:
            self.assertEqual(image.size, CARD_SIZE)
            self.assertEqual(image.format, "PNG")

    def test_countdown_is_calculated_until_monday_moscow_time(self):
        now = datetime(2026, 8, 25, 5, 30, tzinfo=ZoneInfo("Europe/Moscow"))

        self.assertEqual(countdown_to_next_monday_0600(now), "6 дн. 00:30")

    def test_incomplete_data_is_safe_and_hides_telegram_id(self):
        data = build_card_data(
            {"name": "<b>123456789</b>", "username": None},
            {"available_rub": "invalid", "current_week": None, "wagering": "invalid"},
            now=datetime(2026, 8, 24, 7, tzinfo=ZoneInfo("Europe/Moscow")),
        )

        self.assertEqual(data.player_name, "Игрок")
        self.assertEqual(data.available_balance, "0,00 ₽")
        self.assertEqual(data.weekly_turnover, "0,00 ₽")
        self.assertEqual(data.wagering_remaining, "0,00 ₽")
        self.assertIsNone(data.next_tier_progress)
        self.assertEqual(data.countdown, "6 дн. 23:00")
        self.assertNotIn("<", data.player_name)
        self.assertNotIn("123456789", data.player_name)


if __name__ == "__main__":
    unittest.main()
