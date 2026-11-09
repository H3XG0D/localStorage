import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from order_source import (
    ORDER_SOURCE_BOT,
    ORDER_SOURCE_LEGACY,
    ORDER_SOURCE_MINIAPP,
    ORDER_SOURCE_OPERATOR,
    ORDER_SOURCE_SITE,
    ORDER_VIA_TG_MINIAPP,
    channel_note,
    coerce_public_order_source,
    normalize_order_source,
    order_source_for_via,
    order_source_label,
    uses_bot_receipt_route,
)


class OrderSourceTests(unittest.TestCase):
    def test_sources_are_stable_and_human_readable(self):
        self.assertEqual(normalize_order_source(ORDER_SOURCE_BOT), "bot")
        self.assertEqual(normalize_order_source(ORDER_SOURCE_SITE), "site")
        self.assertEqual(normalize_order_source(ORDER_SOURCE_OPERATOR), "manual_operator")
        self.assertEqual(order_source_label("bot"), "Telegram-бот")
        self.assertEqual(order_source_label("tg_miniapp"), "Миниаппка")
        self.assertEqual(order_source_label("site"), "Сайт")
        self.assertEqual(order_source_label("manual_operator"), "Оператор")

    def test_miniapp_via_is_its_own_source(self):
        self.assertEqual(order_source_for_via(ORDER_VIA_TG_MINIAPP), ORDER_SOURCE_MINIAPP)
        self.assertEqual(order_source_for_via(None), ORDER_SOURCE_SITE)
        self.assertEqual(order_source_for_via("site"), ORDER_SOURCE_SITE)
        self.assertTrue(uses_bot_receipt_route(ORDER_SOURCE_MINIAPP))
        self.assertTrue(uses_bot_receipt_route(ORDER_SOURCE_BOT))
        self.assertFalse(uses_bot_receipt_route(ORDER_SOURCE_SITE))
        self.assertEqual(coerce_public_order_source("bot"), "bot")
        self.assertEqual(coerce_public_order_source("manual_operator"), "site")
        self.assertEqual(channel_note("bot", "через оператора"), "Telegram · через оператора")
        self.assertEqual(channel_note("site"), "Сайт")
        self.assertEqual(channel_note("bot"), "Telegram")
        self.assertEqual(channel_note("tg_miniapp", "пользователь нажал «Оплатил»"), "Миниаппка · пользователь нажал «Оплатил»")
        self.assertEqual(channel_note("tg_miniapp"), "Миниаппка")

    def test_empty_and_unknown_sources_are_safe(self):
        self.assertEqual(normalize_order_source(None), ORDER_SOURCE_LEGACY)
        self.assertEqual(normalize_order_source("  "), ORDER_SOURCE_LEGACY)
        self.assertEqual(order_source_label("external_import"), "external_import")


if __name__ == "__main__":
    unittest.main()
