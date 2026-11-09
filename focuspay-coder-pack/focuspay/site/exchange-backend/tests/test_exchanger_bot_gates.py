"""Гейт кассира и маска токена бота без живого Telegram."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from exchanger_bot_commands import mask_bot_token


BACKEND = Path(__file__).resolve().parents[1]


class ClerkPayoutGateTests(unittest.TestCase):
    def test_payout_routes_use_owner_dependency(self):
        src = (BACKEND / "routers" / "exchanger.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        owner_handlers = set()
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            deco_src = ast.get_source_segment(src, node.decorator_list[0]) if node.decorator_list else ""
            args = " ".join(a.arg for a in node.args.args)
            if "get_current_exchanger_owner" in ast.dump(node):
                owner_handlers.add(node.name)
            elif "get_current_exchanger_owner" in (deco_src or "") or "get_current_exchanger_owner" in args:
                owner_handlers.add(node.name)
        # Fallback: textual — AST dump of defaults/annotations
        if "payouts_create" not in owner_handlers:
            self.assertIn("payouts_create", src)
            create_idx = src.index("async def payouts_create")
            snippet = src[create_idx : create_idx + 180]
            self.assertIn("get_current_exchanger_owner", snippet)
        create_idx = src.index("async def payouts_create")
        self.assertIn("get_current_exchanger_owner", src[create_idx : create_idx + 160])
        rub_idx = src.index("async def payouts_rub_card")
        self.assertIn("get_current_exchanger_owner", src[rub_idx : rub_idx + 160])
        list_idx = src.index("async def payouts_list")
        self.assertIn("get_current_exchanger_owner", src[list_idx : list_idx + 220])

    def test_token_never_in_public_config_keys(self):
        from exchanger_bot_config import public_config

        out = public_config({"token": "1234567890:AAEsecretsecret7xQ", "bot_username": "shop_bot"})
        self.assertTrue(out["configured"])
        self.assertEqual(out["token_masked"], mask_bot_token("1234567890:AAEsecretsecret7xQ"))
        self.assertNotIn("token", out)
        self.assertNotIn("webhook_secret", out)
        self.assertNotIn("AAEsecret", str(out))


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


class _ConfigConn:
    def __init__(self):
        self.row = None
        self.webhook_secrets: list[str] = []

    async def fetchrow(self, sql, *args):
        if "SELECT" in sql.upper() and "INSERT" not in sql.upper():
            return dict(self.row) if self.row else None
        self.row = {
            "id": 1,
            "token": args[0],
            "bot_id": args[1],
            "bot_username": args[2],
            "webhook_secret": args[3],
            "webhook_url": args[4],
            "configured_at": None,
            "last_error": None,
        }
        self.webhook_secrets.append(args[3])
        return dict(self.row)


class ConfigureIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_configure_reuses_webhook_secret(self):
        from unittest.mock import AsyncMock, patch

        conn = _ConfigConn()
        apply_calls: list[tuple[str, str]] = []

        async def fake_apply(token: str, webhook_secret: str) -> str:
            apply_calls.append((token, webhook_secret))
            return f"https://focuspay.org/api/bot/exchanger/{webhook_secret}"

        with (
            patch("exchanger_bot_config.get_me", AsyncMock(return_value={"id": 1, "username": "shop_bot"})),
            patch("exchanger_bot_config.apply_webhook", fake_apply),
            patch("exchanger_bot_config.get_pool", AsyncMock(return_value=_Pool(conn))),
        ):
            from exchanger_bot_config import configure_token

            first = await configure_token("1234567890:AAEsecretsecret7xQ", updated_by=1)
            second = await configure_token("1234567890:AAEsecretsecret7xQ", updated_by=1)

        self.assertEqual(len(conn.webhook_secrets), 2)
        self.assertEqual(conn.webhook_secrets[0], conn.webhook_secrets[1])
        self.assertEqual(apply_calls[0][1], apply_calls[1][1])
        self.assertEqual(first["token_masked"], second["token_masked"])
        self.assertNotIn("AAEsecret", str(first) + str(second))


class WhitelistTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_telegram_id_denied_without_deal(self):
        from unittest.mock import AsyncMock, patch

        from exchanger_bot_handlers import DENIED_TEXT, handle_telegram_update

        sent: list[tuple] = []

        async def fake_send(token, chat_id, text, **_kwargs):
            sent.append((token, chat_id, text))
            return {}

        class _MemberConn:
            async def fetchrow(self, *_a, **_k):
                return None

            async def execute(self, *_a, **_k):
                return "UPDATE 0"

        create = AsyncMock()
        with (
            patch("exchanger_bot_handlers.fetch_config_row", AsyncMock(return_value={"token": "tok"})),
            patch("exchanger_bot_handlers.get_pool", AsyncMock(return_value=_Pool(_MemberConn()))),
            patch("exchanger_bot_handlers.send_message", fake_send),
            patch("exchanger_bot_handlers.create_cabinet_deal_with_payin", create),
        ):
            await handle_telegram_update(
                {
                    "message": {
                        "chat": {"type": "private"},
                        "from": {"id": 999},
                        "text": "сбп 5400",
                    }
                }
            )
        self.assertEqual(sent, [("tok", 999, DENIED_TEXT)])
        create.assert_not_called()


class OperatorBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_start_is_not_denied(self):
        from unittest.mock import AsyncMock, patch

        from exchanger_bot_handlers import handle_telegram_update
        from exchanger_ops_requisite import OPERATOR_HELP

        sent: list[tuple] = []

        async def fake_send(token, chat_id, text, **_kwargs):
            sent.append((token, chat_id, text))
            return {}

        class _Conn:
            def __init__(self):
                self.calls = 0

            async def fetchrow(self, sql, *_a, **_k):
                self.calls += 1
                if "exchanger_bot_members" in sql:
                    return None
                if "operator_accounts" in sql:
                    return {
                        "id": 3,
                        "username": "focus",
                        "display_name": "Focus Operator",
                        "telegram_user_id": 8832194482,
                    }
                return None

            async def execute(self, *_a, **_k):
                return "UPDATE 0"

        with (
            patch("exchanger_bot_handlers.fetch_config_row", AsyncMock(return_value={"token": "tok"})),
            patch("exchanger_bot_handlers.get_pool", AsyncMock(return_value=_Pool(_Conn()))),
            patch("exchanger_ops_requisite.send_message", fake_send),
        ):
            await handle_telegram_update(
                {
                    "message": {
                        "chat": {"type": "private"},
                        "from": {"id": 8832194482},
                        "text": "/start",
                    }
                }
            )
        self.assertEqual(sent, [("tok", 8832194482, OPERATOR_HELP)])

    def test_cancel_callback_fits_telegram_limit(self):
        from exchanger_ops_requisite import _format_issued, cancel_keyboard, parse_cancel_callback

        markup = cancel_keyboard("MAN-ABCDEF")
        data = markup["inline_keyboard"][0][0]["callback_data"]
        self.assertLessEqual(len(data), 64)
        self.assertEqual(parse_cancel_callback(data), "MAN-ABCDEF")
        self.assertIsNone(parse_cancel_callback("opq:m:5400:S"))
        text = _format_issued(
            "MAN-ABCDEF",
            "merchant",
            "SBPRUB",
            3000,
            {"reciver": "7900", "bank": "Сбер", "fio": "Иван", "reki_message_id": 77},
        )
        self.assertIn("MAN-ABCDEF", text)
        self.assertIn("7900", text)
        self.assertIn("22.5", text)
        self.assertIn("МТС Банка", text)
        self.assertNotIn("почт", text.lower())
        self.assertNotIn("Мерчант", text)
        self.assertNotIn("77", text)
        self.assertNotIn("Payfast", text)
        with_id = _format_issued(
            "MAN-ABCDEF",
            "reki_bot",
            "SBPRUB",
            3505,
            {
                "reciver": "79194837680",
                "bank": "Сбербанк",
                "payfast_id": "d84a6631-28dc-4afd-aa52-533a5b5bdaa3",
            },
        )
        self.assertIn("d84a6631-28dc-4afd-aa52-533a5b5bdaa3", with_id)
        self.assertNotIn("почт", with_id.lower())

    async def test_operator_amount_goes_straight_to_reki(self):
        from unittest.mock import AsyncMock, patch

        from exchanger_ops_requisite import handle_operator_message

        sent: list[tuple] = []
        edits: list[tuple] = []

        async def fake_send(token, chat_id, text, **kwargs):
            sent.append((text, kwargs.get("reply_markup")))
            return {"ok": True, "result": {"message_id": 5}}

        async def fake_edit(token, chat_id, message_id, text, **kwargs):
            edits.append((message_id, text, kwargs.get("reply_markup")))
            return {}

        card = "✅ <b>Реквизит · СБП</b>\n<code>MAN-ABCDEF</code>"
        with (
            patch("exchanger_ops_requisite.send_message", fake_send),
            patch("exchanger_ops_requisite.edit_message", fake_edit),
            patch(
                "exchanger_ops_requisite._issue_reki_bot",
                AsyncMock(return_value=(True, card, "MAN-ABCDEF")),
            ),
        ):
            await handle_operator_message(
                "tok",
                {"telegram_user_id": 1},
                {"text": "сбп 5400"},
            )
        self.assertIn("Ищу", sent[0][0])
        self.assertIsNone(sent[0][1])
        self.assertNotIn("Откуда взять", sent[0][0])
        message_id, text, markup = edits[0]
        self.assertEqual(message_id, 5)
        self.assertIn("MAN-ABCDEF", text)
        self.assertNotIn("Мерчант", text)
        self.assertEqual(markup["inline_keyboard"][0][0]["callback_data"], "opq:x:MAN-ABCDEF")

    async def test_cancel_closes_ticket_after_reki_click(self):
        from unittest.mock import AsyncMock, patch

        from exchanger_ops_requisite import handle_operator_callback

        edits: list[str] = []

        async def fake_edit(_token, _chat_id, _message_id, text, **_kwargs):
            edits.append(text)
            return {}

        with (
            patch(
                "exchanger_ops_requisite._load_operator_ticket",
                AsyncMock(
                    return_value={
                        "code": "MAN-ABCDEF",
                        "source": "reki_bot",
                        "status": "ISSUED",
                        "bill": {"reki_message_id": 77},
                    }
                ),
            ),
            patch(
                "exchanger_ops_requisite._cancel_reki_remote",
                AsyncMock(return_value=(True, "Заявка отменена")),
            ) as remote,
            patch(
                "exchanger_ops_requisite._mark_ticket_canceled",
                AsyncMock(return_value=True),
            ) as mark,
            patch("exchanger_ops_requisite.edit_message", fake_edit),
        ):
            notice = await handle_operator_callback(
                "tok",
                {"telegram_user_id": 5},
                "opq:x:MAN-ABCDEF",
                chat_id=5,
                message_id=9,
            )
        self.assertEqual(notice, "Заявка отменена")
        remote.assert_awaited_once_with(77)
        mark.assert_awaited_once_with("MAN-ABCDEF", 5)
        self.assertIn("Заявка отменена", edits[0])

    async def test_cancel_keeps_ticket_when_reki_refuses(self):
        from unittest.mock import AsyncMock, patch

        from exchanger_ops_requisite import handle_operator_callback

        with (
            patch(
                "exchanger_ops_requisite._load_operator_ticket",
                AsyncMock(
                    return_value={
                        "code": "MAN-ABCDEF",
                        "source": "reki_bot",
                        "status": "ISSUED",
                        "bill": {"reki_message_id": 77},
                    }
                ),
            ),
            patch(
                "exchanger_ops_requisite._cancel_reki_remote",
                AsyncMock(return_value=(False, "Не удалось отменить заявку у реки-бота.")),
            ),
            patch(
                "exchanger_ops_requisite._mark_ticket_canceled",
                AsyncMock(return_value=True),
            ) as mark,
        ):
            notice = await handle_operator_callback(
                "tok",
                {"telegram_user_id": 5},
                "opq:x:MAN-ABCDEF",
                chat_id=5,
                message_id=9,
            )
        self.assertIn("Не удалось", notice)
        mark.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
