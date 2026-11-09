"""Тесты таймера отправки PDF-чека в ops-уведомлениях."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.db import _parse_snapshot_datetime, get_receipt_requested_at
from services.order_ops_notify import (
    format_ops_message,
    format_receipt_upload_delay_line,
    format_receipt_upload_duration,
    format_relative_duration,
    format_start_age_line,
)


class FormatRelativeDurationTests(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(format_relative_duration(45), "45 сек назад")

    def test_minutes(self):
        self.assertEqual(format_relative_duration(180), "3 мин назад")

    def test_hours(self):
        self.assertEqual(format_relative_duration(4320), "1 ч 12 мин назад")

    def test_days(self):
        self.assertEqual(format_relative_duration(172800), "2 дн назад")


class FormatStartAgeLineTests(unittest.TestCase):
    def test_with_first_seen(self):
        now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
        order = {
            "bot_first_seen_at": (now - timedelta(minutes=3)).isoformat(),
        }
        with patch("services.order_ops_notify.datetime") as mock_dt:
            mock_dt.now.return_value = now
            line = format_start_age_line(order)
        self.assertEqual(line, "первый /start 3 мин назад")

    def test_ignores_last_seen_only(self):
        now = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
        order = {
            "bot_last_seen_at": (now - timedelta(minutes=3)).isoformat(),
        }
        self.assertIsNone(format_start_age_line(order))

    def test_missing(self):
        self.assertIsNone(format_start_age_line({}))


class FormatReceiptUploadDurationTests(unittest.TestCase):
    def test_seconds_only(self):
        self.assertEqual(format_receipt_upload_duration(5), "5 сек")
        self.assertEqual(format_receipt_upload_duration(0), "0 сек")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_receipt_upload_duration(75), "1 мин 15 сек")

    def test_exact_minutes(self):
        self.assertEqual(format_receipt_upload_duration(120), "2 мин")


class GetReceiptRequestedAtTests(unittest.TestCase):
    def test_from_dict_snapshot(self):
        order = {
            "payment_snapshot": {
                "receipt_requested_at": "2026-07-05T10:37:24.123456+00:00"
            }
        }
        dt = get_receipt_requested_at(order)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)

    def test_postgres_text_format_elapsed(self):
        order = {
            "required_receipt_type": 2,
            "payment_snapshot": {
                "receipt_requested_at": "2026-07-05 07:01:32-05",
                "receipt_ops_submitted_at": "2026-07-05T12:01:47+00:00",
            },
        }
        line = format_receipt_upload_delay_line(order)
        self.assertEqual(line, "⏱ PDF отправлен за 15 сек")

    def test_missing(self):
        self.assertIsNone(get_receipt_requested_at({}))


class FormatReceiptUploadDelayLineTests(unittest.TestCase):
    def test_pdf_with_timestamp(self):
        order = {
            "required_receipt_type": 2,
            "payment_snapshot": {
                "receipt_requested_at": "2026-07-05T12:01:32+00:00",
                "receipt_ops_submitted_at": "2026-07-05T12:01:47+00:00",
            },
        }
        line = format_receipt_upload_delay_line(order)
        self.assertEqual(line, "⏱ PDF отправлен за 15 сек")

    def test_pdf_with_timestamp_mock_now(self):
        now = datetime(2026, 7, 5, 10, 37, 39, tzinfo=timezone.utc)
        order = {
            "required_receipt_type": 2,
            "payment_snapshot": {
                "receipt_requested_at": (now - timedelta(seconds=15)).isoformat()
            },
        }
        with patch("services.order_ops_notify.datetime") as mock_dt:
            mock_dt.now.return_value = now
            line = format_receipt_upload_delay_line(order)
        self.assertEqual(line, "⏱ PDF отправлен за 15 сек")

    def test_video_skipped(self):
        order = {
            "required_receipt_type": 3,
            "payment_snapshot": {"receipt_requested_at": datetime.now(tz=timezone.utc).isoformat()},
        }
        self.assertIsNone(format_receipt_upload_delay_line(order))

    def test_no_timestamp(self):
        order = {"required_receipt_type": 2, "payment_snapshot": {}}
        self.assertIsNone(format_receipt_upload_delay_line(order))

    def test_prefers_revealed_over_requested(self):
        """Автопереход CREATED→чек ставит requested≈submitted → без revealed было бы 0 сек."""
        order = {
            "required_receipt_type": 2,
            "payment_snapshot": {
                "requisites_revealed_at": "2026-07-23T08:43:53.846916+00:00",
                "receipt_requested_at": "2026-07-23T08:44:45.189532Z",
                "receipt_ops_submitted_at": "2026-07-23T08:44:45.398232+00:00",
            },
        }
        line = format_receipt_upload_delay_line(order)
        # requested≈submitted (<3с) → fallback на revealed → ~51 сек
        self.assertEqual(line, "⏱ PDF отправлен за 51 сек")

    def test_prefers_requested_when_meaningful(self):
        """Нормальный путь: от «Я оплатил» до PDF, не от открытия реквизитов."""
        order = {
            "required_receipt_type": 2,
            "payment_snapshot": {
                "requisites_revealed_at": "2026-07-23T10:37:11.951230+00:00",
                "receipt_requested_at": "2026-07-23T10:39:01.221041Z",
                "receipt_ops_submitted_at": "2026-07-23T10:40:31.938458+00:00",
            },
        }
        line = format_receipt_upload_delay_line(order)
        self.assertEqual(line, "⏱ PDF отправлен за 1 мин 30 сек")


class FormatOpsMessageReceiptTimerTests(unittest.TestCase):
    def test_receipt_ops_review_includes_timer(self):
        now = datetime(2026, 7, 5, 10, 37, 39, tzinfo=timezone.utc)
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto": "ltc",
            "fiat_amount": 4000,
            "required_receipt_type": 2,
            "payment_snapshot": {
                "receipt_requested_at": (now - timedelta(seconds=15)).isoformat(),
                "bill": {"bank": "Сбербанк", "reciver": "79001234567", "fio": "Иван"},
            },
            "bot_first_seen_at": (now - timedelta(minutes=5)).isoformat(),
            "device_signal": {
                "ip": "1.2.3.4",
                "fingerprint": "abcdef0123456789ffff",
                "platform": "Android",
                "screen": "1080x2400@2.5",
                "timezone": "Europe/Moscow",
            },
        }
        with patch("services.order_ops_notify.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            text = format_ops_message(
                "receipt_ops_review",
                order,
                note="Проверьте чек перед отправкой мерчанту",
            )
        self.assertIn("PDF отправлен за 15 сек", text)
        self.assertIn("первый /start 5 мин назад", text)
        self.assertIn("Проверьте чек", text)
        self.assertIn("💳 Сбербанк", text)
        self.assertIn("79001234567", text)
        self.assertIn("Устройство", text)
        self.assertIn("1.2.3.4", text)

    def test_receipt_ops_review_without_start_age(self):
        now = datetime(2026, 7, 5, 10, 37, 39, tzinfo=timezone.utc)
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "required_receipt_type": 2,
            "payment_snapshot": {
                "receipt_requested_at": (now - timedelta(seconds=15)).isoformat()
            },
        }
        with patch("services.order_ops_notify.datetime") as mock_dt:
            mock_dt.now.return_value = now
            text = format_ops_message("receipt_ops_review", order)
        self.assertIn("PDF отправлен за 15 сек", text)
        self.assertNotIn("/start нажимал", text)

    def test_receipt_attached_includes_timer(self):
        now = datetime(2026, 7, 5, 10, 37, 50, tzinfo=timezone.utc)
        order = {
            "order_id": "ORD-2",
            "direction": "buy",
            "status": "PENDING",
            "crypto": "btc",
            "fiat_amount": 10000,
            "required_receipt_type": 2,
            "payment_snapshot": {
                "receipt_requested_at": (now - timedelta(seconds=30)).isoformat()
            },
        }
        with patch("services.order_ops_notify.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            text = format_ops_message("receipt_attached", order)
        self.assertIn("PDF отправлен за 30 сек", text)


if __name__ == "__main__":
    unittest.main()
