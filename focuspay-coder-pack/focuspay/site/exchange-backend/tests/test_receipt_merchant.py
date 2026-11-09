"""Тесты merchant ID и receipt validation."""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from merchant_order_id import resolve_merchant_api_id, resolve_merchant_api_id_with_legacy
from receipt_validation import is_valid_pdf_bytes, is_valid_video_bytes


class MerchantApiIdTests(unittest.TestCase):
    def test_prefers_order_id(self):
        self.assertEqual(
            resolve_merchant_api_id({"order_id": "15844080", "merchant_order_id": "uuid-old"}),
            "15844080",
        )

    def test_legacy_fallback(self):
        primary, legacy = resolve_merchant_api_id_with_legacy(
            {"order_id": "15844080", "merchant_order_id": "uuid-old"}
        )
        self.assertEqual(primary, "15844080")
        self.assertEqual(legacy, "uuid-old")

    def test_legacy_from_snapshot(self):
        primary, legacy = resolve_merchant_api_id_with_legacy(
            {
                "order_id": "15844080",
                "merchant_order_id": "15844080",
                "payment_snapshot": {"merchant_uuid": "abc-uuid-system"},
            }
        )
        self.assertEqual(primary, "15844080")
        self.assertEqual(legacy, "abc-uuid-system")


class ReceiptValidationTests(unittest.TestCase):
    def test_pdf_magic(self):
        self.assertTrue(is_valid_pdf_bytes(b"%PDF-1.4"))

    def test_video_iso_base_media_magic(self):
        self.assertTrue(is_valid_video_bytes(b"\x00\x00\x00\x18ftypmp42"))

    def test_video_ebml_magic_for_webm_and_mkv(self):
        self.assertTrue(is_valid_video_bytes(b"\x1a\x45\xdf\xa3\x93\x42\x82\x88webm"))

    def test_video_avi_magic(self):
        self.assertTrue(is_valid_video_bytes(b"RIFF\x00\x00\x00\x00AVI LIST"))

    def test_rejects_random(self):
        self.assertFalse(is_valid_video_bytes(b"not-a-video"))


class MerchantAlreadyPaidTests(unittest.TestCase):
    def test_detects_russian_already_paid(self):
        from merchant_api_helpers import payfast_set_check_already_paid

        self.assertTrue(
            payfast_set_check_already_paid(
                {"status": 400, "body": {"error": "Заявка уже успешно оплачена"}}
            )
        )
        self.assertFalse(
            payfast_set_check_already_paid({"status": 400, "body": {"error": "bad receipt"}})
        )


class ExternalReceiptSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_retryable_error_does_not_create_review(self):
        from external_deal_payin import attach_receipt_for_deal

        conn = AsyncMock()
        row = {"id": 6, "status": "awaiting_receipt", "paid_confirmed_at": "x", "merchant_order_id": "uuid-6", "payment_snapshot": {"merchant_uuid": "uuid-6"}}
        with patch("external_deal_payin.get_deal_for_exchanger", new=AsyncMock(return_value=row)), patch(
            "external_deal_payin.payin_set_check_for_order", new=AsyncMock(return_value={"status": 500, "body": {"error": "later"}})
        ):
            with self.assertRaises(HTTPException) as raised:
                await attach_receipt_for_deal(conn, 6, 1, "receipt-url", "")
        self.assertEqual(raised.exception.status_code, 503)
        conn.execute.assert_not_awaited()

    async def test_permanent_rejection_creates_review(self):
        from external_deal_payin import attach_receipt_for_deal

        conn = AsyncMock()
        row = {"id": 7, "status": "awaiting_receipt", "paid_confirmed_at": "x", "merchant_order_id": "uuid-7", "payment_snapshot": {"merchant_uuid": "uuid-7"}}
        with patch("external_deal_payin.get_deal_for_exchanger", new=AsyncMock(return_value=row)), patch(
            "external_deal_payin.payin_set_check_for_order", new=AsyncMock(return_value={"status": 400, "body": {"error": "bad receipt"}})
        ):
            with self.assertRaises(HTTPException):
                await attach_receipt_for_deal(conn, 7, 1, "receipt-url", "")
        self.assertIn("receipt_rejected_permanent", conn.execute.await_args.args)

    async def test_already_paid_is_success(self):
        from external_deal_payin import attach_receipt_for_deal

        conn = AsyncMock()
        row = {
            "id": 8,
            "status": "awaiting_receipt",
            "paid_confirmed_at": "x",
            "merchant_order_id": "uuid-8",
            "payment_snapshot": {"merchant_uuid": "uuid-8"},
        }
        pending = {**row, "status": "pending"}
        with patch(
            "external_deal_payin.get_deal_for_exchanger",
            new=AsyncMock(side_effect=[row, pending]),
        ), patch(
            "external_deal_payin.payin_set_check_for_order",
            new=AsyncMock(
                return_value={
                    "status": 400,
                    "body": {"error": "Заявка уже успешно оплачена"},
                }
            ),
        ), patch(
            "external_deal_payin.deal_public_out",
            return_value={"id": 8, "status": "pending"},
        ):
            out = await attach_receipt_for_deal(conn, 8, 1, "receipt-url", "")
        self.assertEqual(out["status"], "pending")
        self.assertEqual(out["message"], "Чек отправлен")
