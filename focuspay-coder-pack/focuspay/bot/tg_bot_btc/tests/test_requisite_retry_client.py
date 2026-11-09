"""Тексты кнопки повторного запроса реквизитов."""
from __future__ import annotations

import unittest

from services.requisite_retry_client import (
    RETRY_CALLBACK,
    retry_expired_text,
    retry_keyboard,
    retry_saved_text,
    retry_still_empty_text,
    retry_wait_text,
)


class RetryCopyTests(unittest.TestCase):
    def test_saved_notice_mentions_window_and_cooldown(self):
        text = retry_saved_text()
        self.assertIn("30 минут", text)
        self.assertIn("5 минут", text)

    def test_button_callback_is_stable(self):
        markup = retry_keyboard()
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.callback_data, RETRY_CALLBACK)
        self.assertIn("Повторить", button.text)

    def test_expired_and_wait_are_distinct(self):
        self.assertIn("вышло", retry_expired_text())
        self.assertIn("через", retry_wait_text("Повторить запрос можно через 4 мин."))
        self.assertIn("5 минут", retry_still_empty_text())


if __name__ == "__main__":
    unittest.main()
