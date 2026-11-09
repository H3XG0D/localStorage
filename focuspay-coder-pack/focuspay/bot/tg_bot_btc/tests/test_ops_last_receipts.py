""" /last в ops-группе: прошлые чеки покупателя. """
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.ops_last_receipts import (
    clamp_last_count,
    format_last_summary,
    ops_last_receipts_handler,
    parse_last_request,
    receipt_file_path,
    receipt_is_video,
    resolve_buyer_id,
)
from services.db import clamp_receipt_limit


def _update(
    chat_id: int,
    *,
    args: list[str] | None = None,
    reply_caption: str | None = None,
    reply_text: str | None = None,
):
    reply = None
    if reply_caption is not None or reply_text is not None:
        reply = SimpleNamespace(caption=reply_caption, text=reply_text)
    msg = SimpleNamespace(
        reply_text=AsyncMock(),
        reply_to_message=reply,
    )
    update = SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_chat=SimpleNamespace(id=chat_id),
    )
    bot = SimpleNamespace(send_document=AsyncMock(), send_video=AsyncMock())
    context = SimpleNamespace(args=list(args or []), bot=bot)
    return update, msg, context, bot


_WHEN = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def _order(**overrides):
    row = {
        "order_id": "29596203",
        "user_id": 555,
        "status": "PAID",
        "fiat_amount": 12000,
        "crypto": "usdt",
        "direction": "buy",
        "created_at": _WHEN,
        "receipt_file": "a.pdf",
        "merchant_order_id": "465b7e30-3974-47e1-96e2-debb72ac7882",
        "payment_snapshot": {"uuid_system": "465b7e30-3974-47e1-96e2-debb72ac7882"},
        "required_receipt_type": 2,
    }
    row.update(overrides)
    return row


class ParseLastTests(unittest.TestCase):
    def test_count_and_id(self):
        count, ref = parse_last_request(["5", "29596203"])
        self.assertEqual(count, 5)
        self.assertEqual(ref, "29596203")

    def test_uuid(self):
        uid = "465b7e30-3974-47e1-96e2-debb72ac7882"
        count, ref = parse_last_request(["5", uid])
        self.assertEqual(count, 5)
        self.assertEqual(ref, uid)

    def test_clamps_above_ten(self):
        count, ref = parse_last_request(["99", "29596203"])
        self.assertEqual(count, 10)
        self.assertEqual(ref, "29596203")

    def test_zero_is_usage(self):
        self.assertIsNone(clamp_last_count("0"))
        count, ref = parse_last_request(["0", "29596203"])
        self.assertIsNone(count)
        self.assertIsNone(ref)

    def test_reply_without_id_uses_card(self):
        card = "🆔 <code>29596203</code>\n💰 12 000 ₽"
        count, ref = parse_last_request(["5"], reply_text=card)
        self.assertEqual(count, 5)
        self.assertEqual(ref, "29596203")

    def test_reply_payfast_uuid(self):
        card = "🆔 Payfast: <code>465b7e30-3974-47e1-96e2-debb72ac7882</code>"
        count, ref = parse_last_request(["3"], reply_caption=card)
        self.assertEqual(count, 3)
        self.assertEqual(ref, "465b7e30-3974-47e1-96e2-debb72ac7882")


class PathAndSummaryTests(unittest.TestCase):
    def test_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "receipts"
            root.mkdir()
            outside = Path(tmp) / "secret.pdf"
            outside.write_bytes(b"x")
            link = root / "link.pdf"
            link.symlink_to(outside)
            good = root / "a.pdf"
            good.write_bytes(b"%PDF")
            self.assertEqual(receipt_file_path("a.pdf", root), good.resolve())
            self.assertIsNone(receipt_file_path("link.pdf", root))
            self.assertIsNone(receipt_file_path("../secret.pdf", root))
            self.assertIsNone(receipt_file_path("/etc/passwd", root))
            self.assertIsNone(receipt_file_path("a/../../secret.pdf", root))

    def test_summary_lists_order_and_missing_file(self):
        present = _order()
        present["_file_missing"] = False
        missing = _order(
            order_id="11112222",
            merchant_order_id="11112222",
            payment_snapshot={},
            receipt_file="gone.pdf",
            status="CANCELED",
        )
        missing["_file_missing"] = True
        text = format_last_summary(555, {"paid_count": 7}, [present, missing])
        self.assertIn("Постоянный", text)
        self.assertIn("555", text)
        self.assertIn("465b7e30-3974-47e1-96e2-debb72ac7882", text)
        self.assertIn("12 000 ₽", text)
        self.assertIn("PAID", text)
        self.assertIn("11.10 15:00", text)
        self.assertIn("11112222", text)
        self.assertIn("файла нет", text)
        self.assertEqual(text.count("файла нет"), 1)

    def test_video_by_type_or_extension(self):
        self.assertTrue(receipt_is_video("clip.mp4", {"required_receipt_type": 2}))
        self.assertTrue(receipt_is_video("note.bin", {"required_receipt_type": 3}))
        self.assertFalse(receipt_is_video("a.pdf", {"required_receipt_type": 2}))
        self.assertFalse(receipt_is_video("a.pdf", {"required_receipt_type": 3}))
        self.assertFalse(receipt_is_video("shot.gif", {"required_receipt_type": 3}))

    def test_sql_limit_cap(self):
        self.assertEqual(clamp_receipt_limit(99), 10)
        self.assertEqual(clamp_receipt_limit(0), 1)
        self.assertEqual(clamp_receipt_limit(5), 5)


class ResolveBuyerTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_wins_over_same_looking_telegram_id(self):
        order = {"user_id": 555, "order_id": "29596203"}
        with (
            patch(
                "services.db.find_order_for_stat",
                new=AsyncMock(return_value=order),
            ) as find,
            patch(
                "handlers.ops_last_receipts.buyer_has_orders",
                new=AsyncMock(return_value=True),
            ) as has,
        ):
            uid = await resolve_buyer_id("29596203")
        self.assertEqual(uid, 555)
        find.assert_awaited_once_with("29596203")
        has.assert_not_awaited()

    async def test_telegram_id_when_no_order(self):
        with (
            patch("services.db.find_order_for_stat", new=AsyncMock(return_value=None)),
            patch(
                "handlers.ops_last_receipts.buyer_has_orders",
                new=AsyncMock(return_value=True),
            ) as has,
        ):
            uid = await resolve_buyer_id("1097952683")
        self.assertEqual(uid, 1097952683)
        has.assert_awaited_once_with(1097952683)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_silent_outside_ops(self):
        update, msg, context, bot = _update(-100111, args=["5", "29596203"])
        with patch("handlers.ops_last_receipts.is_ops_group_chat", return_value=False):
            await ops_last_receipts_handler(update, context)
        msg.reply_text.assert_not_awaited()
        bot.send_document.assert_not_awaited()

    async def test_hint_without_args(self):
        update, msg, context, _bot = _update(-100, args=[])
        with patch("handlers.ops_last_receipts.is_ops_group_chat", return_value=True):
            await ops_last_receipts_handler(update, context)
        text = msg.reply_text.await_args.args[0]
        self.assertIn("/last 5 id", text)

    async def test_sends_pdf_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.pdf").write_bytes(b"%PDF")
            present = _order(receipt_file="a.pdf")
            missing = _order(
                order_id="11112222",
                merchant_order_id="11112222",
                payment_snapshot={},
                receipt_file="gone.pdf",
            )
            update, msg, context, bot = _update(-100, args=["5", "29596203"])
            with (
                patch("handlers.ops_last_receipts.is_ops_group_chat", return_value=True),
                patch(
                    "services.db.find_order_for_stat",
                    new=AsyncMock(return_value={"user_id": 555, "order_id": "29596203"}),
                ),
                patch(
                    "handlers.ops_last_receipts.get_buyer_ops_stats",
                    new=AsyncMock(return_value={"paid_count": 7}),
                ),
                patch(
                    "handlers.ops_last_receipts.get_recent_receipt_orders",
                    new=AsyncMock(return_value=[present, missing]),
                ) as recent,
                patch("handlers.ops_last_receipts.receipts_dir", return_value=root),
            ):
                await ops_last_receipts_handler(update, context)
        recent.assert_awaited_once_with(555, 5)
        summary = msg.reply_text.await_args_list[0].args[0]
        self.assertIn("файла нет", summary)
        self.assertIn("Постоянный", summary)
        bot.send_document.assert_awaited_once()
        caption = bot.send_document.await_args.kwargs["caption"]
        self.assertIn("465b7e30-3974-47e1-96e2-debb72ac7882", caption)
        bot.send_video.assert_not_awaited()
        self.assertEqual(msg.reply_text.await_count, 1)

    async def test_video_and_failed_send_does_not_stop_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clip.mp4").write_bytes(b"mp4")
            (root / "b.pdf").write_bytes(b"%PDF")
            video = _order(receipt_file="clip.mp4", required_receipt_type=3, order_id="29596203")
            pdf = _order(
                order_id="88887777",
                merchant_order_id="88887777",
                payment_snapshot={},
                receipt_file="b.pdf",
                required_receipt_type=2,
            )
            update, msg, context, bot = _update(-100, args=["99", "29596203"])
            bot.send_video.side_effect = RuntimeError("boom")
            bot.send_document.side_effect = [RuntimeError("nope"), None]
            with (
                patch("handlers.ops_last_receipts.is_ops_group_chat", return_value=True),
                patch(
                    "services.db.find_order_for_stat",
                    new=AsyncMock(return_value={"user_id": 555}),
                ),
                patch(
                    "handlers.ops_last_receipts.get_buyer_ops_stats",
                    new=AsyncMock(return_value={"paid_count": 20}),
                ),
                patch(
                    "handlers.ops_last_receipts.get_recent_receipt_orders",
                    new=AsyncMock(return_value=[video, pdf]),
                ) as recent,
                patch("handlers.ops_last_receipts.receipts_dir", return_value=root),
            ):
                await ops_last_receipts_handler(update, context)
        recent.assert_awaited_once_with(555, 10)
        bot.send_video.assert_awaited()
        self.assertGreaterEqual(bot.send_document.await_count, 2)
        texts = [call.args[0] for call in msg.reply_text.await_args_list]
        self.assertTrue(any("VIP" in t for t in texts))
        self.assertTrue(any("Не удалось отправить" in t for t in texts))

    async def test_buyer_not_found(self):
        update, msg, context, bot = _update(-100, args=["5", "1097952683"])
        with (
            patch("handlers.ops_last_receipts.is_ops_group_chat", return_value=True),
            patch("services.db.find_order_for_stat", new=AsyncMock(return_value=None)),
            patch(
                "handlers.ops_last_receipts.buyer_has_orders",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "handlers.ops_last_receipts.get_recent_receipt_orders",
                new=AsyncMock(),
            ) as recent,
        ):
            await ops_last_receipts_handler(update, context)
        self.assertIn("не найден", msg.reply_text.await_args.args[0])
        recent.assert_not_awaited()
        bot.send_document.assert_not_awaited()
