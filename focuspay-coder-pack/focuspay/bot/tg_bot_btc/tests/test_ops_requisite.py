"""Парсинг «сбп 5400», выдача тикета и чистка висяков — без сети."""
from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services.manual_requisite import (  # noqa: E402
    SOURCE_MERCHANT,
    SOURCE_RAIL,
    SOURCE_REKI_BOT,
    ManualTicket,
    normalize_ticket_code,
    new_ticket_code,
)
from services.manual_requisite_issue import (  # noqa: E402
    IssueResult,
    cancel_issued_reki,
    cleanup_stale_tickets_once,
    format_issued,
    issue_from_rail,
    issue_from_reki_bot,
    release_requisite,
)
from services.ops_requisite_parse import parse_requisite_command  # noqa: E402
from services.reki_request import parse_issued_requisite, payfast_id_from_issue  # noqa: E402
from services.reki_snapshot import SUB_TOKEN_CARD, SUB_TOKEN_SBP  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_sbp_and_card(self):
        self.assertEqual(
            parse_requisite_command("сбп 5400"),
            {"amount_rub": 5400.0, "sub_token": SUB_TOKEN_SBP},
        )
        self.assertEqual(
            parse_requisite_command("карта 12 000"),
            {"amount_rub": 12000.0, "sub_token": SUB_TOKEN_CARD},
        )
        self.assertEqual(
            parse_requisite_command("c2c 3500.5"),
            {"amount_rub": 3500.5, "sub_token": SUB_TOKEN_CARD},
        )

    def test_rejects_junk(self):
        for text in ("", "привет", "сбп", "сбп -1", "/reki", "баланс 100"):
            self.assertIsNone(parse_requisite_command(text), text)

    def test_ticket_code_shape(self):
        code = new_ticket_code()
        self.assertTrue(code.startswith("MAN-"))
        self.assertEqual(len(code), 10)
        self.assertEqual(normalize_ticket_code(" man-ab12cd "), "MAN-AB12CD")
        self.assertIsNone(normalize_ticket_code("short"))
        self.assertIsNone(normalize_ticket_code(""))


class RekiReplyParseTests(unittest.TestCase):
    def test_card_and_phone(self):
        card = parse_issued_requisite(
            "Банк: Сбер\nКарта 2200 7001 2345 6789\nПолучатель: Иван И."
        )
        self.assertIsNotNone(card)
        self.assertEqual(card.method, "card")
        self.assertIn("2200", card.requisite)

        phone = parse_issued_requisite("СБП +7 900 123 45 67 Банк: Т-Банк")
        self.assertIsNotNone(phone)
        self.assertEqual(phone.method, "sbp")

    def test_refusal(self):
        self.assertIsNone(parse_issued_requisite("Нет свободных реквизитов"))
        self.assertIsNone(parse_issued_requisite(""))

    def test_payfast_id_from_issue_card(self):
        text = (
            "👌🏽 Заявка принята!\n"
            "❗️ВНИМАНИЕ с МТС ДЕНЬГИ, УралСИБ НЕ ПРИНИМАЕМ ОПЛАТЫ❗️\n"
            "🆔 ID заявки: d84a6631-28dc-4afd-aa52-533a5b5bdaa3\n"
            "💰 Сумма: 3505 RUB\n"
            "💳 Реквизит: 79194837680\n"
            "🏦 Банк: Сбербанк\n"
            "🟢 Метод оплаты: СБП\n"
            "Чек можно отправить по почте: null\n"
            "🆔 Ваш id заявки: 29166406\n"
        )
        issued = parse_issued_requisite(text)
        self.assertIsNotNone(issued)
        self.assertEqual(issued.method, "sbp")
        self.assertIn("79194837680", issued.requisite)
        self.assertEqual(issued.bank, "Сбербанк")
        self.assertEqual(issued.payfast_id, "d84a6631-28dc-4afd-aa52-533a5b5bdaa3")
        self.assertNotIn("29166406", issued.payfast_id or "")
        both = (
            "ID заявки: d84a6631-28dc-4afd-aa52-533a5b5bdaa3\n"
            "Ваш id заявки: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
        )
        self.assertEqual(
            payfast_id_from_issue(both),
            "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
        )


class IssueTests(unittest.IsolatedAsyncioTestCase):
    async def test_rail_reserves_and_saves(self):
        candidate = MagicMock(
            id=42,
            bank="Сбер",
            requisites="79001234567",
            holder_name="Иван",
        )
        fit = MagicMock(pay_rub=Decimal("5400.00"))
        conn = MagicMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire)

        with patch(
            "services.db.get_pool", AsyncMock(return_value=pool)
        ), patch(
            "services.payin_requisite_rail.reserve_payin_slot",
            AsyncMock(return_value=(candidate, fit)),
        ) as reserve, patch(
            "services.manual_requisite_issue.save_ticket", AsyncMock()
        ) as save:
            result = await issue_from_rail(
                amount_rub=5400, sub_token=SUB_TOKEN_SBP, operator_tg_id=1
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.source, SOURCE_RAIL)
        self.assertTrue(result.code.startswith("MAN-"))
        self.assertEqual(result.bill["reciver"], "79001234567")
        reserve.assert_awaited_once()
        self.assertEqual(reserve.await_args.kwargs["order_id"], result.code)
        save.assert_awaited_once()

    async def test_rail_empty_pool(self):
        conn = MagicMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire)

        with patch(
            "services.db.get_pool", AsyncMock(return_value=pool)
        ), patch(
            "services.payin_requisite_rail.reserve_payin_slot",
            AsyncMock(return_value=None),
        ):
            result = await issue_from_rail(amount_rub=5400, sub_token=SUB_TOKEN_SBP)
        self.assertFalse(result.ok)
        self.assertIn("карт", result.reason.lower())

    async def test_reki_bot_saves_bill(self):
        issued = MagicMock(
            bank="Т-Банк",
            requisite="79001112233",
            holder="Пётр",
            message_id=77,
            payfast_id="d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
        )
        with patch(
            "services.reki_request.request_ready", return_value=True
        ), patch(
            "services.reki_request.request_requisite", AsyncMock(return_value=issued)
        ), patch(
            "services.manual_requisite_issue.save_ticket", AsyncMock()
        ) as save:
            result = await issue_from_reki_bot(
                amount_rub=3000, sub_token=SUB_TOKEN_SBP, operator_tg_id=9
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.source, SOURCE_REKI_BOT)
        self.assertEqual(result.bill["reciver"], "79001112233")
        self.assertEqual(result.bill["reki_message_id"], 77)
        self.assertEqual(result.bill["payfast_id"], issued.payfast_id)
        save.assert_awaited_once()
        self.assertEqual(save.await_args.kwargs["merchant_order_id"], issued.payfast_id)

    async def test_cleanup_releases_and_cancels(self):
        ticket = ManualTicket(
            code="MAN-ABCDEF",
            source=SOURCE_RAIL,
            sub_token=SUB_TOKEN_SBP,
            amount_rub=Decimal("1000"),
            bill={"reciver": "1"},
        )
        with patch(
            "services.manual_requisite.stale_tickets", AsyncMock(return_value=[ticket])
        ), patch(
            "services.manual_requisite_issue.release_requisite", AsyncMock()
        ) as release, patch(
            "services.manual_requisite.cancel_ticket",
            AsyncMock(return_value=ticket),
        ) as cancel:
            n = await cleanup_stale_tickets_once()
        self.assertEqual(n, 1)
        release.assert_awaited_once_with(ticket)
        cancel.assert_awaited_once_with("MAN-ABCDEF")

    def test_format_issued_has_code(self):
        text = format_issued(
            "MAN-ABCDEF",
            SOURCE_MERCHANT,
            SUB_TOKEN_SBP,
            5400,
            {"reciver": "7900", "bank": "Сбер", "fio": "Иван", "reki_message_id": 77},
        )
        self.assertIn("MAN-ABCDEF", text)
        self.assertIn("7900", text)
        self.assertIn("22.5", text)
        self.assertIn("точную сумму", text)
        self.assertIn("МТС Банка", text)
        self.assertNotIn("почт", text.lower())
        self.assertNotIn("Мерчант", text)
        self.assertNotIn("77", text)
        self.assertNotIn("Payfast", text)

    def test_format_issued_shows_payfast_id(self):
        text = format_issued(
            "MAN-ABCDEF",
            SOURCE_REKI_BOT,
            SUB_TOKEN_SBP,
            3505,
            {
                "reciver": "79194837680",
                "bank": "Сбербанк",
                "payfast_id": "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
            },
        )
        self.assertIn("d84a6631-28dc-4afd-aa52-533a5b5bdaa3", text)
        self.assertIn("MAN-ABCDEF", text)
        self.assertNotIn("почт", text.lower())

    async def test_cancel_clicks_reki_and_marks_ticket(self):
        ticket = ManualTicket(
            code="MAN-ABCDEF",
            source=SOURCE_REKI_BOT,
            sub_token=SUB_TOKEN_SBP,
            amount_rub=Decimal("3000"),
            bill={"reciver": "1", "reki_message_id": 55},
        )
        with patch(
            "services.reki_request.cancel_reki_message", AsyncMock(return_value=True)
        ) as click, patch(
            "services.manual_requisite.cancel_ticket", AsyncMock(return_value=ticket)
        ) as cancel:
            ok, notice = await cancel_issued_reki(ticket)
        self.assertTrue(ok)
        self.assertIn("отмен", notice.lower())
        click.assert_awaited_once_with(55)
        cancel.assert_awaited_once_with("MAN-ABCDEF")

    async def test_cancel_keeps_ticket_when_click_fails(self):
        ticket = ManualTicket(
            code="MAN-ABCDEF",
            source=SOURCE_REKI_BOT,
            sub_token=SUB_TOKEN_SBP,
            amount_rub=Decimal("3000"),
            bill={"reciver": "1", "reki_message_id": 55},
        )
        with patch(
            "services.reki_request.cancel_reki_message", AsyncMock(return_value=False)
        ), patch(
            "services.manual_requisite.cancel_ticket", AsyncMock()
        ) as cancel:
            ok, notice = await cancel_issued_reki(ticket)
        self.assertFalse(ok)
        self.assertIn("Не удалось", notice)
        cancel.assert_not_awaited()

    async def test_release_reki_ignores_click_failure(self):
        ticket = ManualTicket(
            code="MAN-ABCDEF",
            source=SOURCE_REKI_BOT,
            sub_token=SUB_TOKEN_SBP,
            amount_rub=Decimal("3000"),
            bill={"reciver": "1", "reki_message_id": 9},
        )
        with patch(
            "services.reki_request.cancel_reki_message", AsyncMock(return_value=False)
        ) as click:
            await release_requisite(ticket)
        click.assert_awaited_once_with(9)

    async def test_click_cancel_button(self):
        from services.reki_request import click_cancel_button

        class _Button:
            def __init__(self, text: str):
                self.text = text
                self.clicked = False

            async def click(self):
                self.clicked = True

        cancel = _Button("Отменить заявку")
        other = _Button("Ок")
        message = MagicMock()
        message.buttons = [[other, cancel]]
        self.assertTrue(await click_cancel_button(message))
        self.assertTrue(cancel.clicked)
        self.assertFalse(other.clicked)
        empty = MagicMock()
        empty.buttons = []
        self.assertFalse(await click_cancel_button(empty))

    async def test_handler_issues_reki_without_source_menu(self):
        from handlers import ops_requisite

        msg = MagicMock()
        msg.text = "сбп 3000"
        wait = MagicMock()
        wait.edit_text = AsyncMock()
        msg.reply_text = AsyncMock(return_value=wait)
        update = MagicMock()
        update.message = msg
        update.effective_message = msg
        update.effective_user.id = 7
        result = IssueResult(
            ok=True,
            code="MAN-ABCDEF",
            source=SOURCE_REKI_BOT,
            bill={"reciver": "7900", "bank": "Сбер"},
            pay_rub=Decimal("3000"),
        )
        with patch.object(ops_requisite, "_allowed", AsyncMock(return_value=True)), patch.object(
            ops_requisite, "issue_from_reki_bot", AsyncMock(return_value=result)
        ) as issue:
            await ops_requisite.ops_requisite_handler(update, MagicMock())
        issue.assert_awaited_once()
        self.assertNotIn("reply_markup", msg.reply_text.await_args.kwargs)
        self.assertIn("Ищу", msg.reply_text.await_args.args[0])
        edited = wait.edit_text.await_args
        self.assertIn("MAN-ABCDEF", edited.args[0])
        self.assertNotIn("Мерчант", edited.args[0])
        self.assertNotIn("Откуда взять", edited.args[0])
        button = edited.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "opsreq:x:MAN-ABCDEF")
        self.assertLessEqual(len(button.callback_data), 64)


class HandlerGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_ops_group_allowed(self):
        from handlers import ops_requisite

        update = MagicMock()
        update.effective_chat.id = -1001
        update.effective_chat.type = "supergroup"
        update.effective_user.id = 42
        with patch.object(ops_requisite, "is_ops_group_chat", return_value=True):
            self.assertTrue(await ops_requisite._allowed(update))

    async def test_private_requires_bound_operator(self):
        from handlers import ops_requisite

        update = MagicMock()
        update.effective_chat.id = 42
        update.effective_chat.type = "private"
        update.effective_user.id = 42
        with patch.object(ops_requisite, "is_ops_group_chat", return_value=False), patch.object(
            ops_requisite, "_is_bound_operator", AsyncMock(return_value=False)
        ):
            self.assertFalse(await ops_requisite._allowed(update))
        with patch.object(ops_requisite, "is_ops_group_chat", return_value=False), patch.object(
            ops_requisite, "_is_bound_operator", AsyncMock(return_value=True)
        ):
            self.assertTrue(await ops_requisite._allowed(update))


if __name__ == "__main__":
    unittest.main()
