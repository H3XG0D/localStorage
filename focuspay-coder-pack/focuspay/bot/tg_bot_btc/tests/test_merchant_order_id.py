"""Тесты merchant ID."""
import unittest

from services.merchant_order_id import (
    resolve_merchant_api_id,
    resolve_merchant_api_id_with_legacy,
    resolve_merchant_display_id,
    resolve_payfast_uuid_system,
)


class MerchantApiIdTests(unittest.TestCase):
    def test_display_id_prefers_payfast_uuid(self):
        order = {
            "order_id": "19113895",
            "merchant_order_id": "19113895",
            "payment_snapshot": {"merchant_uuid": "c5791301-a4fe-478a-8fb0-f83a55bbf2fb"},
            "direction": "buy",
        }
        self.assertEqual(
            resolve_merchant_display_id(order),
            "c5791301-a4fe-478a-8fb0-f83a55bbf2fb",
        )

    def test_format_ops_buy_shows_payfast_label(self):
        from services.merchant_order_id import format_ops_order_id_html

        order = {
            "order_id": "19113895",
            "direction": "buy",
            "payment_snapshot": {"merchant_uuid": "c5791301-a4fe-478a-8fb0-f83a55bbf2fb"},
        }
        self.assertIn("Payfast:", format_ops_order_id_html(order))
        self.assertIn("c5791301", format_ops_order_id_html(order))

    def test_prefers_order_id(self):
        self.assertEqual(
            resolve_merchant_api_id({"order_id": "15844080", "merchant_order_id": "uuid-old"}),
            "15844080",
        )

    def test_legacy_pair(self):
        primary, legacy = resolve_merchant_api_id_with_legacy(
            {"order_id": "123", "merchant_order_id": "abc-uuid"}
        )
        self.assertEqual(primary, "123")
        self.assertEqual(legacy, "abc-uuid")

    def test_payfast_uuid_from_snapshot(self):
        order = {
            "order_id": "15844080",
            "merchant_order_id": "15844080",
            "payment_snapshot": {"merchant_uuid": "c5791301-a4fe-478a-8fb0-f83a55bbf2fb"},
        }
        self.assertEqual(
            resolve_payfast_uuid_system(order),
            "c5791301-a4fe-478a-8fb0-f83a55bbf2fb",
        )

    def test_payfast_uuid_from_legacy_snapshot_key(self):
        order = {
            "order_id": "15844080",
            "payment_snapshot": {"uuid_system": "legacy-payfast-uuid"},
        }
        self.assertEqual(resolve_payfast_uuid_system(order), "legacy-payfast-uuid")

    def test_payfast_uuid_ignores_invalid_snapshot_value(self):
        order = {
            "order_id": "15844080",
            "payment_snapshot": {"merchant_uuid": {"uuid": "invalid"}},
        }
        self.assertIsNone(resolve_payfast_uuid_system(order))

    def test_payfast_uuid_from_merchant_order_id(self):
        order = {
            "order_id": "15844080",
            "merchant_order_id": "c5791301-a4fe-478a-8fb0-f83a55bbf2fb",
        }
        self.assertEqual(
            resolve_payfast_uuid_system(order),
            "c5791301-a4fe-478a-8fb0-f83a55bbf2fb",
        )
