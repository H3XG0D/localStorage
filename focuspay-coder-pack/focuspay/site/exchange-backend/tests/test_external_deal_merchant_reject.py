"""Тесты обработки отказа мерчанта по чеку (кабинет внештатника)."""
import unittest

from external_deal_payin import merchant_reject_detail, merchant_wants_video


class MerchantReceiptRejectTests(unittest.TestCase):
    def test_wants_video_from_body(self):
        self.assertTrue(merchant_wants_video({"error": "PDF не пройден, нужно видео"}))
        self.assertTrue(merchant_wants_video("запросить у клиента видео"))
        self.assertFalse(merchant_wants_video({"error": "invalid file"}))

    def test_reject_detail_video(self):
        msg = merchant_reject_detail({}, video=True)
        self.assertIn("видео", msg.lower())
        self.assertIn("focus_operator", msg)

    def test_reject_detail_pdf(self):
        msg = merchant_reject_detail({}, video=False)
        self.assertIn("отклонил", msg.lower())
        self.assertIn("focus_operator", msg)


if __name__ == "__main__":
    unittest.main()
