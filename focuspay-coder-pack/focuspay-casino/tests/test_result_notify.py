import importlib
import unittest
from unittest.mock import AsyncMock, patch

from games.result_notify import format_personal_result_dm
from tests.telebot_stub import TelebotModules


class PersonalResultFormatterTests(unittest.TestCase):
    def test_win_includes_payout_and_balance(self):
        text = format_personal_result_dm(
            {
                "result": "win",
                "game_type": "baccara",
                "table_id": "6bb750e9-aaaa-bbbb-cccc-dddddddddddd",
                "your_payout_rub": "95.00",
                "stake_rub": "100.00",
                "commission_rub": "5.00",
                "available_rub": "972.25",
            },
            recipient_id=8443902979,
        )
        self.assertIn("Вы победили", text)
        self.assertIn("Baccara", text)
        self.assertIn("стол #6BB750E9", text)
        self.assertIn("Выплата: 95.00 ₽", text)
        self.assertIn("Ставка: 100.00 ₽", text)
        self.assertIn("Комиссия стола: 5.00 ₽", text)
        self.assertIn("Баланс: 972.25 ₽", text)
        self.assertNotIn("Победил: место", text)

    def test_lose_shows_zero_payout(self):
        text = format_personal_result_dm(
            {
                "result": "lose",
                "game_type": "pvp_dice",
                "table_id": "table-1",
                "your_payout_rub": "0.00",
                "available_rub": "10.00",
            },
            recipient_id=1,
        )
        self.assertIn("Вы проиграли", text)
        self.assertIn("Выплата: 0.00 ₽", text)
        self.assertIn("Баланс: 10.00 ₽", text)

    def test_cancel_omits_payout_and_says_stake_returned(self):
        text = format_personal_result_dm(
            {
                "result": "cancel",
                "game_type": "baccara",
                "table_id": "5a2f9bb1-aaaa-bbbb-cccc-dddddddddddd",
                "your_payout_rub": "0.00",
                "available_rub": "200.00",
            },
            recipient_id=8760743763,
        )
        self.assertIn("Игра отменена, ставка возвращена", text)
        self.assertIn("Baccara", text)
        self.assertIn("стол #5A2F9BB1", text)
        self.assertNotIn("Выплата:", text)
        self.assertIn("Баланс: 200.00 ₽", text)


with TelebotModules("games.v2_runtime", "games.v2_tables"):
    runtime = importlib.import_module("games.v2_runtime")


class V2OutboxPersonalDmTests(unittest.IsolatedAsyncioTestCase):
    async def test_outbox_sends_personal_result_not_seat_headline(self):
        bot = AsyncMock()
        client = AsyncMock()
        client.v2_recovery_or_outbox.return_value = {
            "items": [
                {
                    "outbox_id": 1,
                    "claim_token": "tok",
                    "recipient_id": 8443902979,
                    "payload": {
                        "table_id": "6bb750e9-aaaa-bbbb-cccc-dddddddddddd",
                        "outcome_kind": "winner",
                        "result": "win",
                        "your_payout_rub": "95.00",
                        "available_rub": "972.25",
                        "game_type": "baccara",
                        "stake_rub": "100.00",
                        "pot_rub": "200.00",
                        "payouts": [{"seat_no": 1, "amount_rub": "95.00"}],
                    },
                }
            ]
        }

        processed = await runtime.run_v2_outbox_pass(bot, client, worker_id="w")

        self.assertEqual(processed, 1)
        chat_id, text = bot.send_message.await_args.args[:2]
        self.assertEqual(chat_id, 8443902979)
        self.assertIn("Вы победили", text)
        self.assertIn("Баланс: 972.25 ₽", text)
        self.assertNotIn("Победил: место", text)
        self.assertEqual(bot.send_message.await_args.kwargs["parse_mode"], "HTML")
        client.v2_recovery_or_outbox.assert_any_await(
            "/v2/outbox/complete", outbox_id=1, claim_token="tok"
        )

    async def test_cancelled_outbox_dms_without_settled_board(self):
        bot = AsyncMock()
        client = AsyncMock()
        client.v2_recovery_or_outbox.return_value = {
            "items": [
                {
                    "outbox_id": 2,
                    "claim_token": "tok",
                    "recipient_id": 8760743763,
                    "event_type": "cancelled",
                    "payload": {
                        "table_id": "5a2f9bb1-aaaa-bbbb-cccc-dddddddddddd",
                        "result": "cancel",
                        "game_type": "baccara",
                        "your_payout_rub": "0.00",
                        "available_rub": "200.00",
                    },
                }
            ]
        }
        with patch.object(runtime, "recall_table", return_value={"table_id": "5a2f9bb1-aaaa-bbbb-cccc-dddddddddddd"}), \
                patch.object(runtime, "publish_settled_table", AsyncMock()) as publish:
            processed = await runtime.run_v2_outbox_pass(bot, client, worker_id="w")

        self.assertEqual(processed, 1)
        publish.assert_not_awaited()
        chat_id, text = bot.send_message.await_args.args[:2]
        self.assertEqual(chat_id, 8760743763)
        self.assertIn("Игра отменена, ставка возвращена", text)
        self.assertNotIn("Выплата:", text)
        client.v2_recovery_or_outbox.assert_any_await(
            "/v2/outbox/complete", outbox_id=2, claim_token="tok"
        )

    async def test_cancelled_outbox_deletes_remembered_card(self):
        bot = AsyncMock()
        client = AsyncMock()
        client.v2_recovery_or_outbox.return_value = {
            "items": [
                {
                    "outbox_id": 2,
                    "claim_token": "tok",
                    "recipient_id": 11,
                    "event_type": "public_cancelled",
                    "payload": {
                        "table_id": "5a2f9bb1-aaaa-bbbb-cccc-dddddddddddd",
                        "result": "cancel",
                    },
                }
            ]
        }
        remembered = {
            "table_id": "5a2f9bb1-aaaa-bbbb-cccc-dddddddddddd",
            "game_state": {"play_chats": [{"chat_id": -100123, "card_msg_id": 71}]},
        }
        with patch.object(runtime, "recall_table", return_value=remembered), \
                patch.object(runtime, "publish_settled_table", AsyncMock()) as publish:
            processed = await runtime.run_v2_outbox_pass(bot, client, worker_id="w")

        self.assertEqual(processed, 1)
        publish.assert_not_awaited()
        bot.delete_message.assert_awaited_once_with(-100123, 71)

    async def test_dm_failure_warns_game_chat_without_completing_outbox(self):
        bot = AsyncMock()
        blocked = RuntimeError("Forbidden: bot was blocked by the user")
        blocked.error_code = 403
        blocked.description = "Forbidden: bot was blocked by the user"
        bot.send_message.side_effect = [blocked, None]
        client = AsyncMock()
        client.v2_recovery_or_outbox.return_value = {
            "items": [
                {
                    "outbox_id": 3,
                    "claim_token": "tok",
                    "recipient_id": 8443902979,
                    "payload": {
                        "table_id": "6bb750e9-aaaa-bbbb-cccc-dddddddddddd",
                        "game_chat_id": -100123,
                        "result": "win",
                        "your_payout_rub": "95.00",
                        "available_rub": "972.25",
                        "game_type": "baccara",
                    },
                }
            ]
        }

        processed = await runtime.run_v2_outbox_pass(bot, client, worker_id="w")

        self.assertEqual(processed, 1)
        self.assertEqual(bot.send_message.await_count, 2)
        fallback_chat, fallback_text = bot.send_message.await_args_list[1].args[:2]
        self.assertEqual(fallback_chat, -100123)
        self.assertIn("Откройте личку", fallback_text)
        self.assertNotIn("95.00", fallback_text)
        self.assertNotIn("972.25", fallback_text)
        client.v2_recovery_or_outbox.assert_any_await(
            "/v2/outbox/fail", outbox_id=3, claim_token="tok",
            error="Forbidden: bot was blocked by the user",
            error_kind="dm_unavailable", retry_after_seconds=None,
        )
        self.assertFalse(
            any(call.args and call.args[0] == "/v2/outbox/complete" for call in client.v2_recovery_or_outbox.await_args_list)
        )

    async def test_public_board_failure_does_not_block_personal_result(self):
        bot = AsyncMock()
        client = AsyncMock()
        client.v2_recovery_or_outbox.return_value = {
            "items": [
                {
                    "outbox_id": 40, "claim_token": "public-tok", "recipient_id": 11,
                    "event_type": "public_settled",
                    "payload": {"table_id": "table-4", "table": {"table_id": "table-4"}},
                },
                {
                    "outbox_id": 4, "claim_token": "tok", "recipient_id": 11,
                    "event_type": "settled",
                    "payload": {"table_id": "table-4", "result": "win", "your_payout_rub": "19.00"},
                },
            ]
        }
        with patch.object(runtime, "recall_table", return_value={"table_id": "table-4"}), \
                patch.object(runtime, "publish_settled_table", AsyncMock(side_effect=RuntimeError("group failed"))):
            await runtime.run_v2_outbox_pass(bot, client, worker_id="w")

        bot.send_message.assert_awaited_once()
        client.v2_recovery_or_outbox.assert_any_await(
            "/v2/outbox/fail", outbox_id=40, claim_token="public-tok",
            error="group failed", error_kind="temporary", retry_after_seconds=None,
        )
        client.v2_recovery_or_outbox.assert_any_await(
            "/v2/outbox/complete", outbox_id=4, claim_token="tok"
        )

    async def test_temporary_dm_failure_does_not_claim_user_must_start_bot(self):
        bot = AsyncMock()
        bot.send_message.side_effect = TimeoutError("Telegram timeout")
        client = AsyncMock()
        client.v2_recovery_or_outbox.return_value = {
            "items": [{
                "outbox_id": 5, "claim_token": "tok", "recipient_id": 11,
                "payload": {"table_id": "table-5", "game_chat_id": -100123, "result": "lose"},
            }]
        }

        await runtime.run_v2_outbox_pass(bot, client, worker_id="w")

        self.assertEqual(bot.send_message.await_count, 1)
        client.v2_recovery_or_outbox.assert_any_await(
            "/v2/outbox/fail", outbox_id=5, claim_token="tok", error="Telegram timeout",
            error_kind="temporary", retry_after_seconds=None,
        )

    async def test_ack_failure_after_dm_does_not_emit_false_group_warning(self):
        bot = AsyncMock()
        client = AsyncMock()

        async def api(path, **kwargs):
            if path == "/v2/outbox/claim":
                return {"items": [{
                    "outbox_id": 6, "claim_token": "tok", "recipient_id": 11,
                    "payload": {"table_id": "table-6", "game_chat_id": -100123, "result": "win"},
                }]}
            if path == "/v2/outbox/complete":
                raise TimeoutError("ack failed")
            return {"success": True}

        client.v2_recovery_or_outbox.side_effect = api
        await runtime.run_v2_outbox_pass(bot, client, worker_id="w")

        self.assertEqual(bot.send_message.await_count, 1)
        self.assertFalse(any(
            call.args and call.args[0] == "/v2/outbox/fail"
            for call in client.v2_recovery_or_outbox.await_args_list
        ))
