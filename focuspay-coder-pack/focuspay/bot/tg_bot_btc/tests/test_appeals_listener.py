import unittest

from services.appeals_messages import (
    parse_appeals_success_receipt_request,
    parse_appeals_video_request,
    parse_reki_pdf_failed,
)


class AppealsParseTest(unittest.TestCase):
    def test_success_receipt_waiting_status(self):
        text = (
            "⚠️ Ждем чек в успешном статусе\n\n"
            "🆔 ID заявки: 465b7e30-3974-47e1-96e2-debb72ac7882\n"
            "🆔 Ваш id заявки: 29596203\n\n"
            "📄 Необходимо предоставить чек в течении 12 часов.\n\n"
            "После получения доказательства — повторно отправьте чек на проверку."
        )
        self.assertEqual(parse_appeals_success_receipt_request(text), "29596203")

    def test_success_receipt_uuid_only(self):
        text = (
            "Ждем чек в успешном статусе\n"
            "ID заявки: fac453f1-585a-44d1-8d8c-fa34caa66acf\n"
        )
        self.assertEqual(
            parse_appeals_success_receipt_request(text),
            "fac453f1-585a-44d1-8d8c-fa34caa66acf",
        )

    def test_success_receipt_ignores_generic_pdf_video(self):
        text = (
            "Осталось 10 минут до отмены заявки. "
            "Необходимо запросить у клиента PDF или видео подтверждение перевода."
        )
        self.assertIsNone(parse_appeals_success_receipt_request(text))

    def test_success_receipt_ignores_video_template(self):
        text = (
            "Проверка pdf не пройдена\n"
            "ID заявки: 15257569\n"
            "Необходимо запросить у клиента видео подтверждение."
        )
        self.assertIsNone(parse_appeals_success_receipt_request(text))

    def test_pdf_failed_video_requested(self):
        text = (
            "⚠️ Проверка pdf не пройдена\n\n"
            "🆔 ID заявки: fac453f1-585a-44d1-8d8c-fa34caa66acf\n\n"
            "📄 Необходимо запросить у клиента видео подтверждение перевода."
        )
        self.assertEqual(
            parse_appeals_video_request(text),
            "fac453f1-585a-44d1-8d8c-fa34caa66acf",
        )

    def test_numeric_order_id(self):
        text = (
            "Проверка PDF не пройдена\n"
            "ID заявки: 15257569\n"
            "Необходимо запросить у клиента видео подтверждение."
        )
        self.assertEqual(parse_appeals_video_request(text), "15257569")

    def test_ignores_pdf_or_video_warning(self):
        text = (
            "Осталось 10 минут до отмены заявки. "
            "Необходимо запросить у клиента PDF или видео подтверждение перевода."
        )
        self.assertIsNone(parse_appeals_video_request(text))

    def test_ignores_unrelated(self):
        self.assertIsNone(parse_appeals_video_request("Чек отправлен мерчанту"))

    def test_reki_pdf_failed_keeps_both_ids(self):
        text = (
            "⚠️ Проверка pdf не пройдена\n\n"
            "🆔 ID заявки: ce8c63d1-5230-47d6-b8e7-4610d4b6991b\n"
            "🆔 Ваш id заявки: 29166406\n\n"
            "📄 Необходимо запросить у клиента видео подтверждение перевода.\n\n"
            "После получения доказательства — повторно отправьте видео на проверку."
        )
        self.assertEqual(
            parse_reki_pdf_failed(text),
            ("ce8c63d1-5230-47d6-b8e7-4610d4b6991b", "29166406"),
        )

    def test_reki_pdf_failed_ignores_generic_warning(self):
        text = (
            "Осталось 10 минут до отмены заявки. "
            "Необходимо запросить у клиента PDF или видео подтверждение перевода."
        )
        self.assertIsNone(parse_reki_pdf_failed(text))


if __name__ == "__main__":
    unittest.main()
