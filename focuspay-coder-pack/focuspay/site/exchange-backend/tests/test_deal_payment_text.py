"""Текст реквизитов для Telegram — без pay_link и служебных полей Payfast."""
import unittest

from payin_bill_display import format_client_payment_text


class DealPaymentTextContractTests(unittest.TestCase):
    def test_build_text_no_pay_link(self):
        deal = {
            "client_pays_rub": 12000,
            "sub_token": "SBPRUB",
            "payment": {
                "bill": {"bank": "Test", "fio": "+79991234567", "reciver": "Ivan"},
                "fiat_amount": 12000,
                "pay_link": "https://payfast.example/pay/secret",
            },
        }
        text = format_client_payment_text(
            amount_rub=deal["payment"]["fiat_amount"],
            sub_token=deal["sub_token"],
            bill=deal["payment"]["bill"],
        )
        self.assertNotIn("payfast", text.lower())
        self.assertNotIn("https://", text)
        self.assertNotIn("Ссылка:", text)
        self.assertIn("МТС Банка", text)
        self.assertIn("Уралсиба", text)
        self.assertIn("одним платежом", text)
        self.assertIn("12 000", text)


if __name__ == "__main__":
    unittest.main()
