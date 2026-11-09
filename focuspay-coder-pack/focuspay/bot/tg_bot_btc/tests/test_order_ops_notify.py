"""Tests for ops notifications and buyer stats block."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services.order_ops_notify import (
    _format_buyer_stats_block,
    _resolve_buyer_stats_sync,
    _trust_level,
    build_ops_keyboard,
    format_device_signal_lines,
    format_ops_message,
    format_reuse_who_html,
    sanitize_telegram_html,
    telegram_open_url,
    telegram_username_url,
)


class TrustLevelTests(unittest.TestCase):
    def test_trust_boundaries(self):
        self.assertIn("Новый", _trust_level(0))
        self.assertIn("Начинающий", _trust_level(1))
        self.assertIn("Начинающий", _trust_level(3))
        self.assertIn("Постоянный", _trust_level(4))
        self.assertIn("Постоянный", _trust_level(9))
        self.assertIn("Доверенный", _trust_level(10))
        self.assertIn("Доверенный", _trust_level(19))
        self.assertIn("VIP", _trust_level(20))


class BuyerStatsBlockTests(unittest.TestCase):
    def test_format_ops_message_includes_buyer_block(self):
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto": "btc",
            "fiat_amount": 15000,
            "crypto_amount": 0.001,
            "user_id": 123,
        }
        stats = {
            "paid_count": 5,
            "last_paid_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            "total_volume_rub": 87500.0,
        }
        text = format_ops_message("awaiting_receipt", order, buyer_stats=stats)
        self.assertIn("Покупатель", text)
        self.assertIn("Сделок", text)
        self.assertIn("87500", text.replace(" ", ""))
        self.assertIn("Постоянный", text)

    def test_format_buyer_stats_block_new_user(self):
        block = _format_buyer_stats_block(
            {"paid_count": 0, "last_paid_at": None, "total_volume_rub": 0}
        )
        self.assertIn("Новый", block)
        self.assertIn("—", block)


class ResolveBuyerStatsSyncTests(unittest.TestCase):
    def test_returns_provided_stats_without_db(self):
        stats = {"paid_count": 3, "last_paid_at": None, "total_volume_rub": 1000.0}
        order = {"user_id": 999}
        result = _resolve_buyer_stats_sync(order, stats)
        self.assertEqual(result, stats)


class BuyerProfileLinkTests(unittest.TestCase):
    def test_format_ops_message_includes_profile_link(self):
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto": "ltc",
            "fiat_amount": 4800,
            "crypto_amount": 1.1,
            "user_id": 5180993642,
        }
        text = format_ops_message(
            "awaiting_receipt",
            order,
            username="testuser",
            first_name="Иван",
        )
        self.assertIn("/ops/client/5180993642", text)
        self.assertNotIn("tg://user?id=5180993642", text)
        self.assertIn("t.me/testuser", text)
        self.assertIn("Иван", text)
        self.assertNotIn("/ops/chat?user=", text)

    def test_format_ops_message_without_username_opens_telegram(self):
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "CREATED",
            "crypto": "btc",
            "fiat_amount": 4901,
            "crypto_amount": 0.0006575,
            "user_id": 6468339772,
        }
        text = format_ops_message("created", order, first_name="Fig Vam")
        self.assertIn("tg://user?id=6468339772", text)
        self.assertIn("Fig Vam", text)

    def test_build_ops_keyboard_includes_profile_button(self):
        kb = build_ops_keyboard("ORD-1", user_id=5180993642)
        flat = [btn for row in kb["inline_keyboard"] for btn in row]
        profile_btn = next(b for b in flat if b.get("text") == "👤 Профиль клиента")
        tg_btn = next(b for b in flat if b.get("text") == "💬 Telegram")
        self.assertEqual(tg_btn["url"], "tg://user?id=5180993642")
        self.assertIn("/ops/client/5180993642", profile_btn["url"])

    def test_build_ops_keyboard_prefers_username_telegram(self):
        kb = build_ops_keyboard("ORD-1", user_id=5180993642, username="testuser")
        flat = [btn for row in kb["inline_keyboard"] for btn in row]
        tg_btn = next(b for b in flat if b.get("text") == "💬 Telegram")
        self.assertEqual(tg_btn["url"], "https://t.me/testuser")


class ReuseWhoLinkTests(unittest.TestCase):
    def test_reuse_who_has_telegram_links(self):
        html = format_reuse_who_html(
            [
                {
                    "user_id": 111222333,
                    "username": "matched_guy",
                    "order_id": "OPABC",
                    "status": "PAID",
                }
            ]
        )
        self.assertNotIn("tg://user?id=111222333", html)
        self.assertNotIn("написать", html)
        self.assertIn("t.me/matched_guy", html)
        self.assertIn("/ops/client/111222333", html)
        self.assertIn("OPABC", html)

    def test_web_only_no_fake_telegram(self):
        html = format_reuse_who_html(
            [
                {
                    "user_id": -33,
                    "username": "saski1998",
                    "order_id": "185627172032",
                    "status": None,
                }
            ]
        )
        self.assertIn("нет TG-аккаунта", html)
        self.assertIn("только сайт", html)
        self.assertNotIn("t.me/saski1998", html)
        self.assertNotIn("tg://user?id=-33", html)
        self.assertIn("uid=-33", html)

    def test_device_signal_shows_who_line(self):
        order = {
            "order_id": "ORD-X",
            "user_id": 1,
            "payment_snapshot": {
                "device_ip_reuse": True,
                "device_reuse_count": 1,
                "device_ip_matches": [
                    {
                        "user_id": 999888777,
                        "username": "old_acc",
                        "order_id": "OPOLD",
                        "status": "PAID",
                    }
                ],
                "device_signal": {
                    "ip": "1.2.3.4",
                    "fingerprint": "abcdef0123456789",
                    "platform": "ios",
                    "screen": "390x844",
                    "timezone": "Europe/Moscow",
                },
            },
        }
        order["device_signal"] = order["payment_snapshot"]["device_signal"]
        lines = format_device_signal_lines(order)
        joined = "\n".join(lines)
        self.assertIn("IP совпал с:", joined)
        self.assertIn("t.me/old_acc", joined)

    def test_common_fp_soft_label(self):
        order = {
            "order_id": "ORD-Y",
            "user_id": 1,
            "device_signal": {
                "ip": "1.2.3.4",
                "fingerprint": "059a84f769ef12608c31f379840d62b0",
                "platform": "iPhone",
                "screen": "393x852@3",
                "timezone": "Europe/Moscow",
            },
            "payment_snapshot": {
                "device_fp_reuse": True,
                "device_fp_common": True,
                "device_fp_user_count": 3,
                "device_reuse_count": 2,
                "device_fp_matches": [
                    {"user_id": 5662001541, "username": "WINN3R7", "order_id": "64080334"},
                ],
            },
        }
        joined = "\n".join(format_device_signal_lines(order))
        self.assertIn("Общий FP модели", joined)
        self.assertNotIn("⚠️ FP reuse", joined)


class TelegramLinkSafetyTests(unittest.TestCase):
    def test_username_url_omits_unknown_usernames(self):
        self.assertEqual(telegram_username_url("@test_user"), "https://t.me/test_user")
        self.assertIsNone(telegram_username_url(None))

    def test_telegram_open_url_falls_back_to_user_id(self):
        self.assertEqual(telegram_open_url(6468339772), "tg://user?id=6468339772")
        self.assertEqual(
            telegram_open_url(6468339772, "figvam"),
            "https://t.me/figvam",
        )
        self.assertIsNone(telegram_open_url(-33))
        self.assertIsNone(telegram_open_url(-33, "webuser"))

    def test_sanitizer_escapes_unsupported_start_tag(self):
        sanitized = sanitize_telegram_html("Риск: свежий в боте (<24ч)")
        self.assertIn("&lt;24ч)", sanitized)
        self.assertNotIn("(<24ч)", sanitized)

    def test_sanitizer_preserves_safe_generated_markup(self):
        sanitized = sanitize_telegram_html(
            '<b>Риск</b> · <a href="https://focuspay.org/ops/orders?q=1">Заявка</a>'
        )
        self.assertIn("<b>Риск</b>", sanitized)
        self.assertIn('<a href="https://focuspay.org/ops/orders?q=1">Заявка</a>', sanitized)

    def test_receipt_note_is_safe_for_html_parse_mode(self):
        order = {
            "order_id": "ORD-1",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto": "btc",
            "fiat_amount": 4800,
            "crypto_amount": 0.001,
            "user_id": 123,
        }
        with patch(
            "services.order_ops_notify.format_receipt_upload_delay_line",
            return_value=None,
        ), patch(
            "services.order_ops_notify.format_start_age_line",
            return_value=None,
        ):
            text = format_ops_message(
                "receipt_ops_review",
                order,
                note="⚠️ Риск: свежий в боте (<24ч)",
            )
        self.assertIn("&lt;24ч)", text)
        self.assertNotIn("(<24ч)", text)


class ReceiptReviewKeyboardTests(unittest.TestCase):
    def test_payfast_asks_to_send_merchant(self):
        from services.order_ops_notify import build_receipt_review_keyboard

        kb = build_receipt_review_keyboard("O1", "sig")
        self.assertEqual(kb["inline_keyboard"][0][0]["text"], "✅ Отправить мерчанту")

    def test_payin_rail_asks_to_accept_locally(self):
        from services.order_ops_notify import build_receipt_review_keyboard

        kb = build_receipt_review_keyboard("O1", "sig", payin_rail=True)
        self.assertEqual(kb["inline_keyboard"][0][0]["text"], "✅ Принять чек")
        self.assertNotIn("мерчанту", kb["inline_keyboard"][0][0]["text"])


if __name__ == "__main__":
    unittest.main()
