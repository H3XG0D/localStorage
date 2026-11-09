"""FocusLucky outbox → Telegram markup."""
from __future__ import annotations

import unittest

from services.raffle_notify import reply_markup_from_payload


class RaffleNotifyMarkupTests(unittest.TestCase):
    def test_watch_url_button(self):
        markup = reply_markup_from_payload(
            {
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "Смотреть розыгрыш", "url": "https://focuspay.org/casino/play/raffle"}]
                    ]
                }
            }
        )
        self.assertIsNotNone(markup)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, "Смотреть розыгрыш")
        self.assertEqual(button.url, "https://focuspay.org/casino/play/raffle")

    def test_missing_markup(self):
        self.assertIsNone(reply_markup_from_payload({}))


if __name__ == "__main__":
    unittest.main()
