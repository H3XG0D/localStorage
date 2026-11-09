"""Telegram rejects docker-internal PUBLIC_SITE_URL on inline buttons."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.support_urls import support_chat_url, telegram_web_url


class TelegramWebUrlTests(unittest.TestCase):
    def test_production_https_ok(self):
        self.assertEqual(
            telegram_web_url("https://focuspay.org/?chat=1"),
            "https://focuspay.org/?chat=1",
        )

    def test_staging_gateway_rejected(self):
        self.assertIsNone(telegram_web_url("http://gateway:8080/?chat=1"))
        self.assertIsNone(telegram_web_url("http://gateway:8080"))

    def test_localhost_and_private_ip_rejected(self):
        self.assertIsNone(telegram_web_url("http://localhost:8080/?chat=1"))
        self.assertIsNone(telegram_web_url("http://127.0.0.1:18081/?chat=1"))
        self.assertIsNone(telegram_web_url("http://10.0.0.8/ops"))

    def test_single_label_host_rejected(self):
        self.assertIsNone(telegram_web_url("http://backend:8000"))
        self.assertIsNone(telegram_web_url("https://nginx"))

    def test_tg_scheme_ok(self):
        self.assertEqual(telegram_web_url("tg://user?id=1"), "tg://user?id=1")

    def test_empty_rejected(self):
        self.assertIsNone(telegram_web_url(""))
        self.assertIsNone(telegram_web_url(None))

    def test_href_omits_anchor_for_gateway(self):
        from services.support_urls import telegram_href

        self.assertEqual(telegram_href("чат", "http://gateway:8080/?chat=1"), "чат")
        self.assertIn(
            "href=",
            telegram_href("чат", "https://focuspay.org/?chat=1"),
        )

    def test_support_chat_url_on_staging_is_not_telegram_safe(self):
        with patch.dict(os.environ, {"PUBLIC_SITE_URL": "http://gateway:8080"}):
            self.assertEqual(support_chat_url(), "http://gateway:8080/?chat=1")
            self.assertIsNone(telegram_web_url(support_chat_url()))
