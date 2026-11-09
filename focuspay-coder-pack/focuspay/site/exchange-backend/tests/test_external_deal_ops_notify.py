"""Тесты ops-уведомлений по сделкам кабинета."""
import unittest
from datetime import datetime, timezone

from external_deal_ops_notify import format_deal_ops_notify, format_exchanger_ops_stats_block


class DealOpsNotifyTests(unittest.TestCase):
    def test_confirm_paid_format(self):
        deal = {
            "id": 2,
            "client_pays_rub": 1200,
            "merchant_order_id": "abc-uuid-123",
            "payment_snapshot": {"merchant_uuid": "abc-uuid-123"},
        }
        exchanger = {"exchanger_name": "nch", "username": "kanglo"}
        text = format_deal_ops_notify("confirm_paid", deal, exchanger)
        self.assertIn("сделка #2", text)
        self.assertIn("nch", text)
        self.assertIn("1 200", text)
        self.assertIn("EXT-2", text)
        self.assertNotIn("abc-uuid-123", text)
        self.assertIn("@kanglo", text)
        self.assertIn("ждём чек", text)

    def test_video_requested_event(self):
        deal = {"id": 5, "client_pays_rub": 500, "payment": {"merchant_uuid": "u-5"}}
        exchanger = {"exchanger_name": "Test", "username": "ex1"}
        text = format_deal_ops_notify("video_requested", deal, exchanger)
        self.assertIn("🎥", text)
        self.assertIn("напишите оператору", text)

    def test_created_includes_client_pay_text(self):
        deal = {"id": 1, "client_pays_rub": 1000}
        exchanger = {"exchanger_name": "Ex", "username": "ex1"}
        text = format_deal_ops_notify("created", deal, exchanger)
        self.assertIn("20 минут", text)
        self.assertIn("одним платежом", text)

    def test_new_client_label_from_deal(self):
        deal = {"id": 7, "client_pays_rub": 5000, "client_is_new": True}
        exchanger = {
            "exchanger_name": "Kanglo",
            "username": "kanglo",
            "is_trusted_client": True,
        }
        text = format_deal_ops_notify("receipt", deal, exchanger)
        self.assertIn("Клиент: новый", text)
        self.assertNotIn("доверенный", text)

    def test_repeat_client_label_from_deal(self):
        deal = {"id": 8, "client_pays_rub": 3000, "client_is_new": False}
        exchanger = {"exchanger_name": "New", "is_trusted_client": False}
        text = format_deal_ops_notify("confirm_paid", deal, exchanger)
        self.assertIn("Клиент: повторный", text)

    def test_created_crypto_payout_intent(self):
        deal = {
            "id": 12,
            "client_pays_rub": 5000,
            "payout_on_credit": True,
            "payout_wallet": "TXwallet123456",
            "crypto": "usdt",
        }
        exchanger = {"exchanger_name": "Shop", "username": "shop1"}
        text = format_deal_ops_notify("created", deal, exchanger)
        self.assertIn("После зачисления", text)
        self.assertIn("USDT", text)
        self.assertIn("TXwallet123456", text)

    def test_trusted_profile_does_not_affect_client_label(self):
        deal = {"id": 9, "client_pays_rub": 4000, "client_is_new": False}
        exchanger = {"exchanger_name": "T", "is_trusted_client": True}
        text = format_deal_ops_notify("created", deal, exchanger)
        self.assertIn("Клиент: повторный", text)

    def test_auto_confirmed_event(self):
        deal = {"id": 10, "client_pays_rub": 8000, "client_is_new": True}
        exchanger = {"exchanger_name": "K", "is_trusted_client": True}
        text = format_deal_ops_notify("auto_confirmed", deal, exchanger)
        self.assertIn("автоматически", text)

    def test_exchanger_stats_block(self):
        stats = {
            "confirmed_count": 12,
            "total_turnover_rub": 150000.0,
            "last_confirmed_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        block = format_exchanger_ops_stats_block(stats)
        self.assertIn("Внештатник", block)
        self.assertIn("Подтверждено сделок: <b>12</b>", block)
        self.assertIn("150 000 ₽", block)

    def test_stats_block_in_notify(self):
        deal = {"id": 11, "client_pays_rub": 6000, "client_is_new": True}
        exchanger = {"exchanger_name": "test", "username": "test"}
        stats = {
            "confirmed_count": 3,
            "total_turnover_rub": 18000.0,
            "last_confirmed_at": None,
        }
        text = format_deal_ops_notify("created", deal, exchanger, ops_stats=stats)
        self.assertIn("Подтверждено сделок: <b>3</b>", text)
        self.assertIn("18 000 ₽", text)


if __name__ == "__main__":
    unittest.main()
