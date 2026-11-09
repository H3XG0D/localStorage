""" /checks <банк> [N] в группе отчётов: апрувнутые чеки отправок из банка. """
from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.ops_bank_receipts import ops_bank_receipts_handler
from services.receipt_bank_report import (
    format_checks_summary,
    order_bank,
    parse_checks_request,
    resolve_bank_query,
)

REPORTS_CHAT = -1001234567890


def _order(order_id: str, bank: str, amount: float, receipt: str | None = "r.pdf") -> dict:
    return {
        "order_id": order_id,
        "merchant_order_id": None,
        "payment_snapshot": json.dumps({"bill": {"bank": bank, "reciver": "7900"}}),
        "crypto": "usdt",
        "direction": "buy",
        "status": "PAID",
        "crypto_amount": 10,
        "fiat_amount": amount,
        "created_at": datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc),
        "receipt_file": receipt,
        "user_id": 777,
        "required_receipt_type": 2,
    }


def _update(chat_id: int, *, args: list[str] | None, user_id: int = 42):
    msg = SimpleNamespace(reply_text=AsyncMock(), reply_to_message=None)
    update = SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=user_id, username="boss"),
    )
    ctx = SimpleNamespace(args=list(args or []), bot=None)
    return update, ctx, msg


class ParseChecksRequestTest(unittest.TestCase):
    def test_bank_and_count(self):
        label, patterns, count = parse_checks_request(["vtb", "10"])
        self.assertEqual(label, "ВТБ")
        self.assertEqual(count, 10)
        self.assertIn("%втб%", patterns)
        self.assertIn("%vtb%", patterns)

    def test_count_optional(self):
        self.assertEqual(parse_checks_request(["сбер"])[2], 10)

    def test_count_capped(self):
        self.assertEqual(parse_checks_request(["сбер", "500"])[2], 20)

    def test_multiword_bank(self):
        label, _, count = parse_checks_request(["русский", "стандарт", "3"])
        self.assertEqual(count, 3)
        self.assertEqual(label, "русский стандарт")

    def test_unknown_bank_searched_literally(self):
        label, patterns, _ = parse_checks_request(["кукубанк"])
        self.assertEqual(label, "кукубанк")
        self.assertEqual(patterns, ["%кукубанк%"])

    def test_no_args_and_zero(self):
        self.assertIsNone(parse_checks_request([]))
        self.assertIsNone(parse_checks_request(["втб", "0"]))

    def test_yo_normalized(self):
        self.assertIsNotNone(resolve_bank_query("Сбер"))
        self.assertEqual(resolve_bank_query("ВТБ")[0], "ВТБ")


class FormatTest(unittest.TestCase):
    def test_summary_has_bank_amount_and_total(self):
        orders = [_order("A1", "Банк ВТБ", 5000), _order("A2", "ВТБ", 2500)]
        orders[0]["_sender_bank"] = "ВТБ"
        orders[0]["_recipient_bank"] = "Т-Банк"
        text = format_checks_summary("ВТБ", 10, orders)
        self.assertIn("Отправки из", text)
        self.assertIn("ВТБ → Т-Банк", text)
        self.assertIn("7 500 ₽", text)
        self.assertIn("по 2 чекам", text)

    def test_empty(self):
        self.assertIn("Чеков не нашлось.", format_checks_summary("ВТБ", 10, []))

    def test_order_bank_reads_json_string_snapshot(self):
        self.assertEqual(order_bank(_order("A1", "ВТБ", 100)), "ВТБ")


class HandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_silent_outside_reports_group(self):
        update, ctx, msg = _update(-100999, args=["втб", "5"])
        with patch(
            "handlers.ops_bank_receipts.config_rates.is_reports_group_chat",
            return_value=False,
        ):
            await ops_bank_receipts_handler(update, ctx)
        msg.reply_text.assert_not_awaited()

    async def test_denies_non_reports_user(self):
        update, ctx, msg = _update(REPORTS_CHAT, args=["втб", "5"])
        with patch(
            "handlers.ops_bank_receipts.config_rates.is_reports_group_chat",
            return_value=True,
        ), patch(
            "handlers.ops_bank_receipts.config_rates.is_reports_user",
            return_value=False,
        ):
            await ops_bank_receipts_handler(update, ctx)
        self.assertIn("Нет доступа", msg.reply_text.await_args.args[0])

    async def test_hint_without_args(self):
        update, ctx, msg = _update(REPORTS_CHAT, args=[])
        with patch(
            "handlers.ops_bank_receipts.config_rates.is_reports_group_chat",
            return_value=True,
        ), patch(
            "handlers.ops_bank_receipts.config_rates.is_reports_user",
            return_value=True,
        ):
            await ops_bank_receipts_handler(update, ctx)
        self.assertIn("/checks", msg.reply_text.await_args.args[0])

    async def test_video_excluded_in_query_not_after(self):
        """Видео режет SQL. Банк реквизита в запрос не входит: это получатель."""
        from services.db import get_recent_approved_receipt_documents

        src = inspect.getsource(get_recent_approved_receipt_documents)
        self.assertIn("mp4", src)
        self.assertIn("!~", src)
        self.assertIn("LIMIT $1", src.split("!~")[1])
        self.assertNotIn("LIKE ANY", src)
        self.assertNotIn("->> 'bank'", src)

    async def test_always_sends_as_document(self):
        update, ctx, _ = _update(REPORTS_CHAT, args=["втб", "1"])
        bot = SimpleNamespace(send_document=AsyncMock(), send_video=AsyncMock())
        ctx.bot = bot
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "r.pdf").write_bytes(b"%PDF-1.4")
            # required_receipt_type=3 на PDF не должен уводить файл в send_video
            order = _order("A1", "ВТБ", 5000)
            order["required_receipt_type"] = 3
            order["_sender_bank"] = "ВТБ"
            order["_path"] = root / "r.pdf"
            with patch(
                "handlers.ops_bank_receipts.config_rates.is_reports_group_chat",
                return_value=True,
            ), patch(
                "handlers.ops_bank_receipts.config_rates.is_reports_user",
                return_value=True,
            ), patch(
                "handlers.ops_bank_receipts.collect_sender_receipts",
                AsyncMock(return_value=([order], 1, False)),
            ):
                await ops_bank_receipts_handler(update, ctx)
        bot.send_video.assert_not_awaited()
        bot.send_document.assert_awaited_once()

    async def test_sends_summary_and_files(self):
        update, ctx, msg = _update(REPORTS_CHAT, args=["vtb", "2"])
        bot = SimpleNamespace(send_document=AsyncMock(), send_video=AsyncMock())
        ctx.bot = bot
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "r.pdf").write_bytes(b"%PDF-1.4")
            ready = _order("A1", "ВТБ", 5000)
            ready["_sender_bank"] = "ВТБ"
            ready["_path"] = root / "r.pdf"
            with patch(
                "handlers.ops_bank_receipts.config_rates.is_reports_group_chat",
                return_value=True,
            ), patch(
                "handlers.ops_bank_receipts.config_rates.is_reports_user",
                return_value=True,
            ), patch(
                "handlers.ops_bank_receipts.collect_sender_receipts",
                AsyncMock(return_value=([ready], 4, False)),
            ) as fetch, patch(
                "handlers.ops_bank_receipts.receipts_dir",
                return_value=root,
            ):
                await ops_bank_receipts_handler(update, ctx)

        patterns, count, _root = fetch.await_args.args
        self.assertEqual(count, 2)
        self.assertIn("%втб%", patterns)
        self.assertIn("Ищу отправки из", msg.reply_text.await_args_list[0].args[0])
        summary = msg.reply_text.await_args_list[1].args[0]
        self.assertIn("Отправки из", summary)
        self.assertIn("ВТБ", summary)
        bot.send_document.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
