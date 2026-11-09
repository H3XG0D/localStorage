"""Читаемая выдача реквизита внештатнику / его клиенту."""
from __future__ import annotations

import unittest

from external_deal_payin import deal_public_out
from payin_bill_display import format_client_payment_text, public_payin_bill


DIRTY_CARD_BILL = {
    "bank": "Т-Банк (Тинькоф)",
    "reciver": "5213243950274447",
    "fio": "892880",
    "token": "P2P",
    "limit_sum": 11620,
    "sub_token": "CARDRUB",
}


class PublicPayinBillTests(unittest.TestCase):
    def test_keeps_only_client_fields(self):
        out = public_payin_bill(DIRTY_CARD_BILL)
        self.assertEqual(
            out,
            {
                "bank": "Т-Банк (Тинькоф)",
                "reciver": "5213243950274447",
                "fio": "892880",
            },
        )

    def test_aliases(self):
        out = public_payin_bill(
            {"bankName": "Сбер", "receiver": "+79991234567", "holderName": "Иван"}
        )
        self.assertEqual(out["bank"], "Сбер")
        self.assertEqual(out["reciver"], "+79991234567")
        self.assertEqual(out["fio"], "Иван")


class ClientPaymentTextTests(unittest.TestCase):
    def test_card_matches_cabinet_copy(self):
        text = format_client_payment_text(
            amount_rub=744,
            sub_token="CARDRUB",
            bill=DIRTY_CARD_BILL,
        )
        self.assertIn("⚡ Реквизит выдан", text)
        self.assertIn("▸ Сумма: 744 ₽", text)
        self.assertIn("▸ Реквизит: 5213243950274447", text)
        self.assertIn("▸ Банк: Т-Банк (Тинькоф)", text)
        self.assertIn("▸ Получатель: 892880", text)
        self.assertIn("▸ Способ: Карта", text)
        self.assertIn("▸ Срок оплаты: 20 минут", text)
        self.assertIn("Уралсиба", text)
        self.assertIn("МТС Банка", text)
        self.assertIn("одним платежом", text)
        self.assertIn("PDF", text)
        self.assertNotIn("token", text.lower())
        self.assertNotIn("limit", text.lower())
        self.assertNotIn("sub token", text.lower())
        self.assertNotIn("P2P", text)
        self.assertNotIn("CARDRUB", text)
        self.assertNotIn("payyment24", text.lower())

    def test_sbp_phone_from_fio(self):
        text = format_client_payment_text(
            amount_rub=12000,
            sub_token="SBPRUB",
            bill={"bank": "Test", "fio": "+79991234567", "reciver": "Ivan"},
        )
        self.assertIn("Способ: СБП", text)
        self.assertIn("Реквизит: +7 999 123 45 67", text)
        self.assertIn("Получатель: Ivan", text)
        self.assertIn("только на указанный банк", text)
        self.assertNotIn("payfast", text.lower())


class DealPublicOutBillTests(unittest.TestCase):
    def test_strips_payfast_internals_and_adds_payment_text(self):
        out = deal_public_out(
            {
                "id": 11,
                "status": "awaiting_receipt",
                "amount_rub": 744,
                "client_pays_rub": 744,
                "sub_token": "CARDRUB",
                "payment_snapshot": {
                    "bill": DIRTY_CARD_BILL,
                    "fiat_amount": 744,
                    "pay_link": "https://payfast.example/pay/secret",
                },
            }
        )
        bill = out["payment"]["bill"]
        self.assertEqual(set(bill), {"bank", "reciver", "fio"})
        self.assertNotIn("token", bill)
        self.assertNotIn("limit_sum", bill)
        self.assertNotIn("sub_token", bill)
        self.assertIn("Реквизит: 5213243950274447", out["payment_text"])
        self.assertIn("Уралсиба", out["payment_text"])
        self.assertIn("Заявка: #11", out["payment_text"])
        self.assertNotIn("P2P", out["payment_text"])
        self.assertNotIn("11620", out["payment_text"])


if __name__ == "__main__":
    unittest.main()
