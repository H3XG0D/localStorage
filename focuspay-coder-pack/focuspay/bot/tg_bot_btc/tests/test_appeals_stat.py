""" /stat в группе споров: статистика клиента по Payfast ID. """
from __future__ import annotations

import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.appeals_stat import (
    appeals_stat_handler,
    can_run_stat,
    client_alias,
    fingerprint_alias_seed,
    format_stat_card,
    order_from_external_deal,
    parse_stat_ref,
    summary_from_client_stat,
)


def _silent_group_patches():
    stack = ExitStack()
    stack.enter_context(patch("handlers.appeals_stat.is_appeals_group_chat", return_value=False))
    stack.enter_context(patch("handlers.appeals_stat.is_ops_group_chat", return_value=False))
    stack.enter_context(
        patch("handlers.appeals_stat.is_external_deals_group_chat", return_value=False)
    )
    stack.enter_context(patch("handlers.appeals_stat.is_reports_group_chat", return_value=False))
    stack.enter_context(patch("handlers.appeals_stat.is_community_chat", return_value=False))
    stack.enter_context(patch("handlers.appeals_stat.is_news_chat", return_value=False))
    stack.enter_context(patch("handlers.appeals_stat.TELEGRAM_ADMIN_IDS", []))
    return stack


def _update(
    chat_id: int,
    *,
    args: list[str] | None = None,
    reply_caption: str | None = None,
    reply_text: str | None = None,
    user_id: int = 42,
):
    reply = None
    if reply_caption is not None or reply_text is not None:
        reply = SimpleNamespace(caption=reply_caption, text=reply_text)
    msg = SimpleNamespace(
        reply_text=AsyncMock(),
        reply_to_message=reply,
        chat=SimpleNamespace(id=chat_id),
    )
    update = SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=user_id),
    )
    context = SimpleNamespace(args=list(args or []))
    return update, msg, context


_ORDER = {
    "order_id": "29596203",
    "user_id": 1097952683,
    "status": "PAID",
    "fiat_amount": 12000,
    "crypto": "usdt",
    "direction": "buy",
    "merchant_order_id": "465b7e30-3974-47e1-96e2-debb72ac7882",
}

_SUMMARY = {
    "total_orders": 14,
    "buy_total": 10,
    "buy_paid": 7,
    "buy_failed": 3,
    "paid_orders": 7,
    "turnover_rub": 84500.0,
    "first_order_at": datetime(2026, 3, 12, tzinfo=timezone.utc),
    "last_paid_at": datetime.now(tz=timezone.utc) - timedelta(days=2),
    "conversion_pct": 70.0,
}

_ZERO_SUMMARY = {
    "total_orders": 1,
    "buy_total": 1,
    "buy_paid": 0,
    "buy_failed": 0,
    "paid_orders": 0,
    "turnover_rub": 0.0,
    "first_order_at": datetime(2026, 9, 5, tzinfo=timezone.utc),
    "last_paid_at": None,
    "conversion_pct": None,
}


class ParseStatRefTests(unittest.TestCase):
    def test_uuid(self):
        self.assertEqual(
            parse_stat_ref("465b7e30-3974-47e1-96e2-debb72ac7882"),
            "465b7e30-3974-47e1-96e2-debb72ac7882",
        )

    def test_hash_prefixed_order_id(self):
        self.assertEqual(parse_stat_ref("#29596203"), "29596203")

    def test_uuid_in_caption_text(self):
        text = (
            "🆔 ID заявки: 465b7e30-3974-47e1-96e2-debb72ac7882\n"
            "Необходимо запросить у клиента видео"
        )
        self.assertEqual(
            parse_stat_ref(text),
            "465b7e30-3974-47e1-96e2-debb72ac7882",
        )

    def test_empty(self):
        self.assertIsNone(parse_stat_ref(""))
        self.assertIsNone(parse_stat_ref(None))

    def test_client_alias_last_four(self):
        self.assertEqual(client_alias(1097952683), "#2683")
        self.assertEqual(client_alias(-1234), "#1234")

    def test_fingerprint_alias_stable_not_shop_name(self):
        a = fingerprint_alias_seed(3, "buyer-42")
        self.assertEqual(a, fingerprint_alias_seed(3, "buyer-42"))
        self.assertNotEqual(a, fingerprint_alias_seed(3, "buyer-99"))
        self.assertNotEqual(a, fingerprint_alias_seed(4, "buyer-42"))
        self.assertRegex(client_alias(a), r"^#\d{4}$")


class FormatStatCardTests(unittest.TestCase):
    def test_card_has_counts_and_no_user_id(self):
        text = format_stat_card(_ORDER, _SUMMARY)
        self.assertIn("Статистика по заявке", text)
        self.assertIn("465b7e30-3974-47e1-96e2-debb72ac7882", text)
        self.assertIn("70%", text)
        self.assertIn("(7/10)", text)
        self.assertIn("Оплаченных сделок", text)
        self.assertIn(">7<", text)
        self.assertIn("84 500", text)
        self.assertIn("12.03.2026", text)
        self.assertIn("#2683", text)
        self.assertNotIn("1097952683", text)
        self.assertNotIn("@", text)

    def test_zero_conversion_first_order(self):
        text = format_stat_card(_ORDER, _ZERO_SUMMARY)
        self.assertIn("нет данных (первая заявка)", text)
        self.assertIn("Новый", text)

    def test_external_deal_maps_like_buy_order(self):
        deal = {
            "id": 12,
            "exchanger_id": 3,
            "status": "confirmed",
            "client_pays_rub": 12000,
            "crypto": "usdt",
            "merchant_order_id": "465b7e30-3974-47e1-96e2-debb72ac7882",
            "customer_fingerprint": "buyer-42",
        }
        order = order_from_external_deal(deal)
        summary = summary_from_client_stat(
            {
                "paid_orders": 7,
                "total_orders": 14,
                "buy_paid": 7,
                "buy_failed": 3,
                "conversion_pct": 70.0,
                "turnover_rub": 84500,
                "first_order_at": "2026-03-12T00:00:00+00:00",
            }
        )
        self.assertEqual(order["status"], "PAID")
        text = format_stat_card(order, summary)
        self.assertIn("Payfast", text)
        self.assertIn("PAID", text)
        self.assertIn("70%", text)
        self.assertNotIn("внештатн", text.lower())
        self.assertNotIn("buyer-42", text)


class CanRunStatTests(unittest.TestCase):
    def test_admin_allowed_in_foreign_staff_chat(self):
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_ops_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_external_deals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_reports_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_community_chat", return_value=False),
            patch("handlers.appeals_stat.is_news_chat", return_value=False),
            patch("handlers.appeals_stat.TELEGRAM_ADMIN_IDS", [1097952683]),
        ):
            self.assertTrue(can_run_stat(-100111, 1097952683))
            self.assertFalse(can_run_stat(-100111, 42))

    def test_ops_group_allowed_without_appeals_id(self):
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_ops_group_chat", return_value=True),
            patch("handlers.appeals_stat.is_external_deals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_reports_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_community_chat", return_value=False),
            patch("handlers.appeals_stat.is_news_chat", return_value=False),
            patch("handlers.appeals_stat.TELEGRAM_ADMIN_IDS", []),
        ):
            self.assertTrue(can_run_stat(-5043279066, 42))

    def test_blocked_in_community_even_for_admin(self):
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_ops_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_external_deals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_reports_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_community_chat", return_value=True),
            patch("handlers.appeals_stat.is_news_chat", return_value=False),
            patch("handlers.appeals_stat.TELEGRAM_ADMIN_IDS", [1097952683]),
        ):
            self.assertFalse(can_run_stat(-100222, 1097952683))


class AppealsStatHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_silent_outside_appeals(self):
        update, msg, context = _update(-100111, args=["465b7e30-3974-47e1-96e2-debb72ac7882"])
        with _silent_group_patches():
            await appeals_stat_handler(update, context)
        msg.reply_text.assert_not_awaited()

    async def test_admin_in_foreign_chat_shows_card(self):
        update, msg, context = _update(
            -100111,
            args=["465b7e30-3974-47e1-96e2-debb72ac7882"],
            user_id=1097952683,
        )
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_ops_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_external_deals_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_reports_group_chat", return_value=False),
            patch("handlers.appeals_stat.is_community_chat", return_value=False),
            patch("handlers.appeals_stat.is_news_chat", return_value=False),
            patch("handlers.appeals_stat.TELEGRAM_ADMIN_IDS", [1097952683]),
            patch("handlers.appeals_stat.find_order_for_stat", new=AsyncMock(return_value=_ORDER)),
            patch(
                "handlers.appeals_stat.get_buyer_stat_summary",
                new=AsyncMock(return_value=_SUMMARY),
            ),
            patch(
                "handlers.appeals_stat.get_external_deal_by_merchant_ref",
                new=AsyncMock(return_value=None),
            ),
        ):
            await appeals_stat_handler(update, context)
        msg.reply_text.assert_awaited_once()
        self.assertIn("#2683", msg.reply_text.await_args.args[0])

    async def test_hint_without_ref(self):
        update, msg, context = _update(-5561953525, args=[])
        with patch("handlers.appeals_stat.is_appeals_group_chat", return_value=True):
            await appeals_stat_handler(update, context)
        msg.reply_text.assert_awaited_once()
        self.assertIn("/stat", msg.reply_text.await_args.args[0])

    async def test_arg_shows_card(self):
        update, msg, context = _update(
            -5561953525, args=["465b7e30-3974-47e1-96e2-debb72ac7882"]
        )
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=True),
            patch("handlers.appeals_stat.find_order_for_stat", new=AsyncMock(return_value=_ORDER)),
            patch(
                "handlers.appeals_stat.get_buyer_stat_summary",
                new=AsyncMock(return_value=_SUMMARY),
            ),
            patch(
                "handlers.appeals_stat.get_external_deal_by_merchant_ref",
                new=AsyncMock(return_value=None),
            ),
        ):
            await appeals_stat_handler(update, context)
        msg.reply_text.assert_awaited_once()
        text = msg.reply_text.await_args.args[0]
        kwargs = msg.reply_text.await_args.kwargs
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertIn("70%", text)
        self.assertIn("#2683", text)
        self.assertNotIn("1097952683", text)

    async def test_reply_caption_shows_card(self):
        update, msg, context = _update(
            -5561953525,
            args=[],
            reply_caption="465b7e30-3974-47e1-96e2-debb72ac7882",
        )
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=True),
            patch("handlers.appeals_stat.find_order_for_stat", new=AsyncMock(return_value=_ORDER)),
            patch(
                "handlers.appeals_stat.get_buyer_stat_summary",
                new=AsyncMock(return_value=_SUMMARY),
            ),
        ):
            await appeals_stat_handler(update, context)
        msg.reply_text.assert_awaited_once()
        self.assertIn("Payfast", msg.reply_text.await_args.args[0])

    async def test_not_found(self):
        update, msg, context = _update(-5561953525, args=["deadbeef-0000-0000-0000-000000000000"])
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=True),
            patch("handlers.appeals_stat.find_order_for_stat", new=AsyncMock(return_value=None)),
            patch(
                "handlers.appeals_stat.get_external_deal_by_merchant_ref",
                new=AsyncMock(return_value=None),
            ),
        ):
            await appeals_stat_handler(update, context)
        msg.reply_text.assert_awaited_once()
        self.assertIn("не найдена", msg.reply_text.await_args.args[0])

    async def test_external_deal_same_card_no_vneshtat_wording(self):
        update, msg, context = _update(
            -5561953525, args=["465b7e30-3974-47e1-96e2-debb72ac7882"]
        )
        deal = {
            "id": 12,
            "exchanger_id": 3,
            "status": "confirmed",
            "client_pays_rub": 12000,
            "crypto": "usdt",
            "merchant_order_id": "465b7e30-3974-47e1-96e2-debb72ac7882",
            "customer_fingerprint": "buyer-42",
            "client_stat": {
                "paid_orders": 7,
                "total_orders": 14,
                "buy_paid": 7,
                "buy_failed": 3,
                "conversion_pct": 70.0,
                "turnover_rub": 84500,
                "first_order_at": "2026-03-12T00:00:00+00:00",
                "last_paid_at": (datetime.now(tz=timezone.utc) - timedelta(days=2)).isoformat(),
            },
        }
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=True),
            patch("handlers.appeals_stat.find_order_for_stat", new=AsyncMock(return_value=None)),
            patch(
                "handlers.appeals_stat.get_external_deal_by_merchant_ref",
                new=AsyncMock(return_value=deal),
            ),
            patch(
                "handlers.appeals_stat.get_external_client_stat",
                new=AsyncMock(return_value=None),
            ),
        ):
            await appeals_stat_handler(update, context)
        msg.reply_text.assert_awaited_once()
        text = msg.reply_text.await_args.args[0]
        kwargs = msg.reply_text.await_args.kwargs
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertIn("Статистика по заявке", text)
        self.assertIn("Payfast", text)
        self.assertIn("465b7e30-3974-47e1-96e2-debb72ac7882", text)
        self.assertIn("PAID", text)
        self.assertIn("70%", text)
        self.assertIn("(7/10)", text)
        alias = client_alias(fingerprint_alias_seed(3, "buyer-42", 12))
        self.assertIn(alias, text)
        low = text.lower()
        self.assertNotIn("внештатн", low)
        self.assertNotIn("hmac", low)
        self.assertNotIn("кабинет", low)
        self.assertNotIn("недоступн", low)

    async def test_external_deal_empty_stat_looks_new(self):
        update, msg, context = _update(-5561953525, args=["EXT-12"])
        deal = {
            "id": 12,
            "exchanger_id": 3,
            "status": "awaiting_receipt",
            "client_pays_rub": 5000,
            "crypto": "usdt",
            "merchant_order_id": "465b7e30-3974-47e1-96e2-debb72ac7882",
            "customer_fingerprint": "buyer-new",
            "client_stat": None,
        }
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=True),
            patch("handlers.appeals_stat.find_order_for_stat", new=AsyncMock(return_value=None)),
            patch(
                "handlers.appeals_stat.get_external_deal_by_merchant_ref",
                new=AsyncMock(return_value=deal),
            ),
            patch(
                "handlers.appeals_stat.get_external_client_stat",
                new=AsyncMock(return_value=None),
            ),
        ):
            await appeals_stat_handler(update, context)
        text = msg.reply_text.await_args.args[0]
        self.assertIn("нет данных (первая заявка)", text)
        self.assertIn("Новый", text)
        self.assertIn("PENDING", text)
        self.assertNotIn("внештатн", text.lower())
        self.assertNotIn("недоступн", text.lower())

    async def test_zero_stats_first_order(self):
        update, msg, context = _update(-5561953525, args=["29596203"])
        with (
            patch("handlers.appeals_stat.is_appeals_group_chat", return_value=True),
            patch("handlers.appeals_stat.find_order_for_stat", new=AsyncMock(return_value=_ORDER)),
            patch(
                "handlers.appeals_stat.get_buyer_stat_summary",
                new=AsyncMock(return_value=_ZERO_SUMMARY),
            ),
        ):
            await appeals_stat_handler(update, context)
        text = msg.reply_text.await_args.args[0]
        self.assertIn("нет данных (первая заявка)", text)

    def test_command_registered_once(self):
        src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text()
        self.assertEqual(src.count('CommandHandler("stat"'), 1)
        self.assertEqual(src.count('CommandHandler("check"'), 1)
        self.assertIn('CommandHandler("stat", appeals_stat_handler)', src)
        self.assertIn('CommandHandler("check", appeals_stat_handler)', src)
        self.assertNotIn("filters=appeals_group_filter", src)
        self.assertIn("appeals_group_filter", src)


if __name__ == "__main__":
    unittest.main()
