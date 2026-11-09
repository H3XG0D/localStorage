"""Банк отправителя в PDF, а не банк получателя из реквизита."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.receipt_bank_report import (
    identify_sender,
    match_sender_orders,
    sender_matches,
)

OZON_TO_VTB = """
Перевод СБП
Банк получателя ВТБ
Служба поддержки Ozon Банка
ООО «ОЗОН БАНК»
"""

VTB_TO_TBANK = """
Исходящий перевод СБП
Банк получателя Т-Банк
Сумма операции 2 516 ₽
Банк ВТБ (ПАО)
"""

SBER_TO_OZON = """
Операция
Перевод по СБП
Банк получателя
Ozon
Чек по операции
Номер документа
123
"""

TBANK_TO_ALFA = """
Итого
Банк получателя Альфа-Банк
Служба поддержки fb@tbank.ru
Квитанция № 1
"""

ALFA_TO_SBER = """
Сформирована
Квитанция о переводе по СБП
Банк получателя
Сбербанк
Счёт списания
"""

OTP_TO_SBER = """
Квитанция
Банк получателя Сбербанк
Акционерное общество «ОТП Банк»
АО «ОТП БАНК»
"""

GAZPROM_TO_TBANK = """
Банк получателя:
Т-Банк
e-mail: mailbox@gazprombank.ru
www.gazprombank.ru
"""

ROCKET_TO_TBANK = """
БАНК ПОЛУЧАТЕЛЯ
АО "ТБАНК"
БАНК ОТПРАВИТЕЛЯ
РОКЕТ
"""

SBER_INTERNAL = """
Чек по операции
Операция
Перевод клиенту СберБанка
Код авторизации
960464
"""

YOOMONEY = """
Номер кошелька
4100111
Перевод на карту
Перевод завершен
"""

CARD_TO_PSB = """
Перевод в другой банк по номеру карты
В банк
Promsvyazbank
"""


class IdentifySenderTest(unittest.TestCase):
    def test_ozon_receipt_to_vtb_is_ozon(self):
        self.assertEqual(identify_sender(OZON_TO_VTB, "Skia/PDF m105"), "Озон Банк")
        self.assertFalse(sender_matches("Озон Банк", ["%втб%", "%vtb%"]))
        self.assertTrue(sender_matches("Озон Банк", ["%озон%", "%ozon%"]))

    def test_vtb_app_receipt_is_vtb(self):
        sender = identify_sender(VTB_TO_TBANK, "openhtmltopdf.com")
        self.assertEqual(sender, "ВТБ")
        self.assertTrue(sender_matches(sender, ["%втб%", "%vtb%"]))
        self.assertFalse(sender_matches(sender, ["%т-банк%", "%tbank%"]))

    def test_sber_jasper_even_when_text_starts_from_the_bottom(self):
        sender = identify_sender(
            SBER_TO_OZON,
            "iText 2.1.7 by 1T3XT",
            "JasperReports Library version 6.18.1",
        )
        self.assertEqual(sender, "Сбербанк")
        self.assertFalse(sender_matches(sender, ["%озон%", "%ozon%"]))

    def test_tbank_email_not_the_recipient(self):
        sender = identify_sender(TBANK_TO_ALFA, "OpenPDF 1.3.30.jaspersoft.2")
        self.assertEqual(sender, "Т-Банк")
        self.assertFalse(sender_matches(sender, ["%альфа%", "%alfa%"]))

    def test_alfa_oracle_template_not_the_recipient(self):
        sender = identify_sender(ALFA_TO_SBER, "Oracle BI Publisher 12.2.1.4.0")
        self.assertEqual(sender, "Альфа-Банк")
        self.assertFalse(sender_matches(sender, ["%сбер%", "%sber%"]))
        # В боевом PDF слова разделены неразрывным пробелом.
        spaced = ALFA_TO_SBER.replace(" ", "\u00a0")
        self.assertEqual(identify_sender(spaced, "Oracle BI Publisher 12.2.1.4.0"), "Альфа-Банк")

    def test_otp_footer(self):
        self.assertEqual(identify_sender(OTP_TO_SBER, "iOS Version 16.4.1"), "ОТП Банк")

    def test_gazprom_domain(self):
        self.assertEqual(identify_sender(GAZPROM_TO_TBANK), "Газпромбанк")
        self.assertFalse(sender_matches("Газпромбанк", ["%т-банк%", "%tbank%"]))

    def test_explicit_sender_field_wins(self):
        self.assertEqual(identify_sender(ROCKET_TO_TBANK), "РОКЕТ")
        self.assertTrue(sender_matches("РОКЕТ", ["%рокет%"]))
        self.assertFalse(sender_matches("РОКЕТ", ["%тбанк%", "%tbank%"]))

    def test_sber_internal_title(self):
        self.assertEqual(identify_sender(SBER_INTERNAL, "iText 2.1.7 by 1T3XT"), "Сбербанк")

    def test_yoomoney_wallet(self):
        self.assertEqual(identify_sender(YOOMONEY, "iText 2.1.7 by 1T3XT"), "ЮMoney")

    def test_sber_card_transfer_uses_jasper_not_destination(self):
        sender = identify_sender(
            CARD_TO_PSB, "", "JasperReports Library version 6.18.1"
        )
        self.assertEqual(sender, "Сбербанк")
        self.assertFalse(sender_matches(sender, ["%псб%", "%psb%"]))

    def test_unknown_layout_is_skipped(self):
        self.assertIsNone(identify_sender("Квитанция\nСумма 100"))

    def test_match_reads_sender_not_bill_bank(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.pdf").write_bytes(b"%PDF-1.4")
            order = {
                "order_id": "A1",
                "receipt_file": "a.pdf",
                "fiat_amount": 1000,
                "payment_snapshot": '{"bill": {"bank": "ВТБ"}}',
            }
            with patch(
                "services.receipt_bank_report.read_receipt_markup",
                return_value=(OZON_TO_VTB, "Skia/PDF", ""),
            ):
                vtb = match_sender_orders([order], ["%втб%", "%vtb%"], root, 5)
                ozon = match_sender_orders([order], ["%озон%", "%ozon%"], root, 5)
        self.assertEqual(vtb, [])
        self.assertEqual(ozon[0]["_sender_bank"], "Озон Банк")
        self.assertEqual(ozon[0]["_recipient_bank"], "ВТБ")
        self.assertEqual(ozon[0]["_path"], root / "a.pdf")


if __name__ == "__main__":
    unittest.main()
