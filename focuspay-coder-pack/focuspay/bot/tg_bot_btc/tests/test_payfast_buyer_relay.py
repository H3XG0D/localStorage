"""/msg Payfast → покупатель и копия ответа без профиля."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop

from handlers.payfast_buyer_relay import payfast_buyer_reply_handler, payfast_msg_handler
from services.operator_availability import ShiftGate
from services.payfast_buyer_relay import (
    HINT,
    NOT_DELIVERED,
    NOT_FOUND,
    NO_BUYER,
    SHIFT_ON,
    SHIFT_UNKNOWN,
    TOO_LONG,
    find_relay_anchor,
    format_buyer_dm,
    format_client_label,
    insert_relay_anchor,
    parse_msg_command,
    relay_shift_block_reason,
)

_BUYER = 1097952683
_ORDER_ID = "29596203"
_UUID = "465b7e30-3974-47e1-96e2-debb72ac7882"


def _gate(**overrides) -> ShiftGate:
    fields = dict(
        allow=False,
        reason="no_shift",
        active_count=0,
        missing_roles=("client", "finance"),
        telegram_user_ids=(),
        unbound_count=0,
        store_user_ids=(),
    )
    fields.update(overrides)
    return ShiftGate(**fields)


def _order(**overrides) -> dict:
    row = {
        "order_id": _ORDER_ID,
        "user_id": _BUYER,
        "status": "AWAITING_CHECK",
        "merchant_order_id": _UUID,
    }
    row.update(overrides)
    return row


def _group_update(text: str, *, thread: int | None = None, user_id: int = 42):
    msg = SimpleNamespace(
        text=text,
        message_id=10,
        message_thread_id=thread,
        reply_text=AsyncMock(return_value=SimpleNamespace(message_id=77)),
        chat=SimpleNamespace(id=-5561953525),
    )
    update = SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_chat=SimpleNamespace(id=-5561953525),
        effective_user=SimpleNamespace(id=user_id),
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=501)),
        copy_message=AsyncMock(),
        forward_message=AsyncMock(),
    )
    context = SimpleNamespace(bot=bot)
    return update, msg, context, bot


def _private_reply(**fields):
    msg = SimpleNamespace(
        message_id=900,
        text=fields.get("text", "привет 😀"),
        sticker=fields.get("sticker"),
        video=fields.get("video"),
        document=fields.get("document"),
        video_note=fields.get("video_note"),
        reply_to_message=fields.get("reply_to_message", SimpleNamespace(message_id=501)),
        chat=SimpleNamespace(id=_BUYER),
    )
    update = SimpleNamespace(
        message=msg,
        effective_user=SimpleNamespace(id=_BUYER),
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        copy_message=AsyncMock(),
        forward_message=AsyncMock(),
    )
    return update, msg, SimpleNamespace(bot=bot), bot


_ANCHOR = {
    "order_id": _ORDER_ID,
    "buyer_user_id": _BUYER,
    "buyer_message_id": 501,
    "group_chat_id": -5561953525,
    "group_message_id": 77,
    "message_thread_id": 5,
}


class ParseAndShiftTests(unittest.TestCase):
    def test_parse_keeps_newlines_and_emoji(self):
        ref, body = parse_msg_command("/msg@focus_bot 29596203 первая строка\nвторая 😀")
        self.assertEqual(ref, "29596203")
        self.assertEqual(body, "первая строка\nвторая 😀")

    def test_parse_uuid(self):
        ref, body = parse_msg_command(f"/msg {_UUID} где чек")
        self.assertEqual(ref, _UUID)
        self.assertEqual(body, "где чек")

    def test_parse_requires_text(self):
        self.assertEqual(parse_msg_command("/msg 29596203"), ("29596203", ""))
        self.assertEqual(parse_msg_command("/msg"), (None, ""))

    def test_dm_escapes_html_and_hides_profile_wording(self):
        text = format_buyer_dm(_ORDER_ID, "привет <b>x</b> 😀")
        self.assertIn(_ORDER_ID, text)
        self.assertIn("😀", text)
        self.assertNotIn("<b>", text)
        self.assertIn("Ответьте на это сообщение", text)
        self.assertIn("профиль не показывается", text)

    def test_label_is_alias_only(self):
        label = format_client_label(_BUYER)
        self.assertEqual(label, "Клиент #2683")
        self.assertNotIn(str(_BUYER), label)

    def test_shift_blocks(self):
        self.assertIsNone(relay_shift_block_reason(_gate()))
        self.assertEqual(
            relay_shift_block_reason(_gate(active_count=1, reason="incomplete_shift")),
            "on_shift",
        )
        self.assertEqual(
            relay_shift_block_reason(_gate(store_user_ids=(99,))),
            "on_shift",
        )
        self.assertEqual(
            relay_shift_block_reason(_gate(reason="check_failed")),
            "check_failed",
        )


class AnchorStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_and_find_use_buyer_message_pair(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_ANCHOR)
        pool = MagicMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = ctx
        with patch("services.payfast_buyer_relay.get_pool", new=AsyncMock(return_value=pool)):
            await insert_relay_anchor(
                order_id=_ORDER_ID,
                buyer_user_id=_BUYER,
                buyer_message_id=501,
                group_chat_id=-100,
                group_message_id=77,
                message_thread_id=5,
                sender_tg_id=42,
            )
            found = await find_relay_anchor(_BUYER, 501)
        sql = conn.execute.await_args.args[0]
        self.assertIn("payfast_buyer_relay", sql)
        self.assertIn("ON CONFLICT (buyer_user_id, buyer_message_id)", sql)
        self.assertEqual(conn.execute.await_args.args[2], _BUYER)
        self.assertEqual(conn.execute.await_args.args[3], 501)
        self.assertEqual(found["group_message_id"], 77)
        find_sql = conn.fetchrow.await_args.args[0]
        self.assertIn("buyer_user_id = $1 AND buyer_message_id = $2", find_sql)

    def test_migration_declares_unique_anchor(self):
        sql = Path(__file__).resolve().parents[1].joinpath(
            "migrations/add_payfast_buyer_relay.sql"
        ).read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS payfast_buyer_relay", sql)
        self.assertIn("buyer_user_id", sql)
        self.assertIn("buyer_message_id", sql)
        self.assertIn("payfast_buyer_relay_buyer_msg_uidx", sql)


class MsgCommandTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self, gate: ShiftGate, order=None, external=None):
        return (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(return_value=gate),
            ),
            patch(
                "handlers.payfast_buyer_relay.find_order_for_stat",
                new=AsyncMock(return_value=order),
            ),
            patch(
                "handlers.payfast_buyer_relay.get_external_deal_by_merchant_ref",
                new=AsyncMock(return_value=external),
            ),
            patch(
                "handlers.payfast_buyer_relay.insert_relay_anchor",
                new=AsyncMock(),
            ),
        )

    async def test_silent_without_access(self):
        update, msg, _context, bot = _group_update(f"/msg {_ORDER_ID} привет")
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=False),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(),
            ) as gate,
        ):
            await payfast_msg_handler(update, _context)
        msg.reply_text.assert_not_awaited()
        bot.send_message.assert_not_awaited()
        gate.assert_not_awaited()

    async def test_hint_without_text(self):
        update, msg, context, bot = _group_update("/msg 29596203")
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(return_value=_gate()),
            ),
        ):
            await payfast_msg_handler(update, context)
        msg.reply_text.assert_awaited_once()
        self.assertIn("/msg", msg.reply_text.await_args.args[0])
        self.assertEqual(msg.reply_text.await_args.args[0], HINT)
        bot.send_message.assert_not_awaited()

    async def test_operator_on_shift_blocks_even_one_role(self):
        update, msg, context, bot = _group_update(f"/msg {_ORDER_ID} привет")
        find = AsyncMock()
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(
                    return_value=_gate(active_count=1, reason="incomplete_shift", allow=False)
                ),
            ),
            patch("handlers.payfast_buyer_relay.find_order_for_stat", new=find),
        ):
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], SHIFT_ON)
        bot.send_message.assert_not_awaited()
        find.assert_not_awaited()

    async def test_store_shift_blocks(self):
        update, msg, context, bot = _group_update(f"/msg {_ORDER_ID} привет")
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(return_value=_gate(store_user_ids=(7,))),
            ),
        ):
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], SHIFT_ON)
        bot.send_message.assert_not_awaited()

    async def test_shift_check_failed_blocks(self):
        update, msg, context, bot = _group_update(f"/msg {_ORDER_ID} привет")
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(return_value=_gate(reason="check_failed")),
            ),
        ):
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], SHIFT_UNKNOWN)
        bot.send_message.assert_not_awaited()

    async def test_sends_dm_without_buyer_id_in_group(self):
        update, msg, context, bot = _group_update(
            f"/msg {_UUID} где видео\nи стикер 😀",
            thread=12,
        )
        insert = AsyncMock()
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(return_value=_gate()),
            ),
            patch(
                "handlers.payfast_buyer_relay.find_order_for_stat",
                new=AsyncMock(return_value=_order()),
            ),
            patch("handlers.payfast_buyer_relay.insert_relay_anchor", new=insert),
        ):
            await payfast_msg_handler(update, context)
        dm = bot.send_message.await_args.kwargs
        self.assertEqual(dm["chat_id"], _BUYER)
        self.assertIn("где видео\nи стикер 😀", dm["text"])
        self.assertNotIn(str(_BUYER), dm["text"])
        ack = msg.reply_text.await_args.args[0]
        self.assertIn("#2683", ack)
        self.assertIn(_ORDER_ID, ack)
        self.assertNotIn(str(_BUYER), ack)
        self.assertNotIn("@", ack)
        insert.assert_awaited_once()
        saved = insert.await_args.kwargs
        self.assertEqual(saved["buyer_message_id"], 501)
        self.assertEqual(saved["group_message_id"], 77)
        self.assertEqual(saved["message_thread_id"], 12)
        self.assertEqual(saved["buyer_user_id"], _BUYER)
        bot.forward_message.assert_not_called()

    async def test_not_found(self):
        update, msg, context, bot = _group_update(f"/msg {_UUID} текст")
        stacks = self._patches(_gate(), order=None, external=None)
        with stacks[0], stacks[1], stacks[2], stacks[3], stacks[4]:
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], NOT_FOUND)
        bot.send_message.assert_not_awaited()

    async def test_external_deal_has_no_bot_buyer(self):
        update, msg, context, bot = _group_update("/msg EXT-12 текст")
        stacks = self._patches(_gate(), order=None, external={"id": 12})
        with stacks[0], stacks[1], stacks[2], stacks[3], stacks[4]:
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], NO_BUYER)
        bot.send_message.assert_not_awaited()

    async def test_order_without_user(self):
        update, msg, context, bot = _group_update(f"/msg {_ORDER_ID} текст")
        stacks = self._patches(_gate(), order=_order(user_id=0))
        with stacks[0], stacks[1], stacks[2], stacks[3], stacks[4]:
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], NO_BUYER)
        bot.send_message.assert_not_awaited()

    async def test_buyer_blocked_bot(self):
        update, msg, context, bot = _group_update(f"/msg {_ORDER_ID} текст")
        bot.send_message = AsyncMock(side_effect=TelegramError("blocked"))
        insert = AsyncMock()
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(return_value=_gate()),
            ),
            patch(
                "handlers.payfast_buyer_relay.find_order_for_stat",
                new=AsyncMock(return_value=_order()),
            ),
            patch("handlers.payfast_buyer_relay.insert_relay_anchor", new=insert),
        ):
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], NOT_DELIVERED)
        self.assertNotIn(str(_BUYER), msg.reply_text.await_args.args[0])
        insert.assert_not_awaited()

    async def test_text_too_long(self):
        update, msg, context, bot = _group_update("/msg 29596203 " + ("а" * 3501))
        with (
            patch("handlers.payfast_buyer_relay.can_run_stat", return_value=True),
            patch(
                "handlers.payfast_buyer_relay.get_shift_gate",
                new=AsyncMock(return_value=_gate()),
            ),
            patch("handlers.payfast_buyer_relay.find_order_for_stat", new=AsyncMock()) as find,
        ):
            await payfast_msg_handler(update, context)
        self.assertEqual(msg.reply_text.await_args.args[0], TOO_LONG)
        bot.send_message.assert_not_awaited()
        find.assert_not_awaited()


class BuyerReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_is_copied_not_forwarded(self):
        update, _msg, context, bot = _private_reply(text="ответ 😀")
        with patch(
            "handlers.payfast_buyer_relay.find_relay_anchor",
            new=AsyncMock(return_value=_ANCHOR),
        ):
            with self.assertRaises(ApplicationHandlerStop):
                await payfast_buyer_reply_handler(update, context)
        bot.forward_message.assert_not_called()
        copied = bot.copy_message.await_args.kwargs
        self.assertEqual(copied["from_chat_id"], _BUYER)
        self.assertEqual(copied["message_id"], 900)
        self.assertEqual(copied["chat_id"], -5561953525)
        self.assertEqual(copied["reply_to_message_id"], 77)
        self.assertEqual(copied["message_thread_id"], 5)
        label = bot.send_message.await_args.kwargs["text"]
        self.assertEqual(label, "Клиент #2683")
        self.assertNotIn(str(_BUYER), label)

    async def test_sticker_is_copied(self):
        update, _msg, context, bot = _private_reply(text=None, sticker=object())
        with patch(
            "handlers.payfast_buyer_relay.find_relay_anchor",
            new=AsyncMock(return_value=_ANCHOR),
        ):
            with self.assertRaises(ApplicationHandlerStop):
                await payfast_buyer_reply_handler(update, context)
        bot.copy_message.assert_awaited_once()
        bot.forward_message.assert_not_called()

    async def test_unrelated_reply_is_ignored(self):
        update, _msg, context, bot = _private_reply()
        find = AsyncMock(return_value=None)
        with patch("handlers.payfast_buyer_relay.find_relay_anchor", new=find):
            await payfast_buyer_reply_handler(update, context)
        bot.copy_message.assert_not_awaited()
        bot.forward_message.assert_not_called()

    async def test_message_without_reply_is_ignored(self):
        update, _msg, context, bot = _private_reply(reply_to_message=None)
        find = AsyncMock()
        with patch("handlers.payfast_buyer_relay.find_relay_anchor", new=find):
            await payfast_buyer_reply_handler(update, context)
        find.assert_not_awaited()
        bot.copy_message.assert_not_awaited()

    async def test_video_reply_still_reaches_receipt_handler(self):
        update, _msg, context, bot = _private_reply(video=object(), text=None)
        with patch(
            "handlers.payfast_buyer_relay.find_relay_anchor",
            new=AsyncMock(return_value=_ANCHOR),
        ):
            await payfast_buyer_reply_handler(update, context)
        bot.copy_message.assert_awaited_once()
        bot.forward_message.assert_not_called()

    async def test_pdf_reply_still_reaches_receipt_handler(self):
        update, _msg, context, bot = _private_reply(document=object(), text=None)
        with patch(
            "handlers.payfast_buyer_relay.find_relay_anchor",
            new=AsyncMock(return_value=_ANCHOR),
        ):
            await payfast_buyer_reply_handler(update, context)
        bot.copy_message.assert_awaited_once()

    def test_command_and_reply_handler_registered(self):
        src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text()
        self.assertEqual(src.count('CommandHandler("msg"'), 1)
        self.assertIn('CommandHandler("msg", payfast_msg_handler)', src)
        reply_at = src.index("payfast_buyer_reply_handler,\n")
        self.assertIn("group=-5", src[reply_at:reply_at + 80])


if __name__ == "__main__":
    unittest.main()
