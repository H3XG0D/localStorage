import asyncio
import importlib
import math
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("bot", "games.pvp", "games.baccara", "games.blackjack", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.fairness", "games.roulette_table", "games.jackpot", "web_login"):
    casino_bot = importlib.import_module("bot")


class CasinoSettings:
    async def get_casino_settings(self):
        return {
            "commission_rate_wagering_active": 15.0,
            "commission_rate_wagering_complete": 5.0,
            "wagering_percent": 100.0,
            "min_bet_rub": 10.0,
            "max_bet_rub": 100000.0,
            "enabled_games": {
                "pvp_dice": True, "baccara": True, "blackjack": True,
                "roulette": True, "jackpot": True, "fixed_room": True,
            },
        }

    async def get_active_game_chat_binding(self):
        return None

    async def get_active_pvp_games(self):
        return []


class CasinoBotStartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_settings = (
            casino_bot.config.COMMISSION_RATE,
            casino_bot.config.MIN_BET,
            casino_bot.config.MAX_BET,
        )

    def tearDown(self):
        (
            casino_bot.config.COMMISSION_RATE,
            casino_bot.config.MIN_BET,
            casino_bot.config.MAX_BET,
        ) = self.original_settings

    async def test_load_casino_settings_accepts_flat_authoritative_contract(self):
        await casino_bot.load_casino_settings(CasinoSettings())

        self.assertEqual(casino_bot.config.COMMISSION_RATE, 15.0)
        self.assertEqual(casino_bot.config.MIN_BET, 10.0)
        self.assertEqual(casino_bot.config.MAX_BET, 100000.0)

    async def test_load_casino_settings_rejects_missing_or_invalid_financial_values(self):
        for response in (
            {},
            {
                "commission_rate_wagering_active": 15.0,
                "commission_rate_wagering_complete": 5.0,
                "wagering_percent": 100.0,
                "min_bet_rub": 10.0,
                "max_bet_rub": "not-a-number",
            },
            {
                "commission_rate_wagering_active": 101.0,
                "commission_rate_wagering_complete": 5.0,
                "wagering_percent": 100.0,
                "min_bet_rub": 10.0,
                "max_bet_rub": 100.0,
            },
            {
                "commission_rate_wagering_active": 15.0,
                "commission_rate_wagering_complete": 5.0,
                "wagering_percent": 100.0,
                "min_bet_rub": 100.0,
                "max_bet_rub": 10.0,
            },
            {
                "commission_rate_wagering_active": math.nan,
                "commission_rate_wagering_complete": 5.0,
                "wagering_percent": 100.0,
                "min_bet_rub": 10.0,
                "max_bet_rub": 100.0,
            },
        ):
            client = AsyncMock()
            client.get_casino_settings.return_value = response
            with self.assertRaises(ValueError):
                await casino_bot.load_casino_settings(client)

    async def test_client_failure_stops_before_handlers_cleaners_and_polling(self):
        with (
            patch.object(
                casino_bot,
                "get_focuspay_client",
                AsyncMock(side_effect=RuntimeError("API unavailable")),
            ),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()) as close_client,
            patch.object(casino_bot, "run_recovery_pass", AsyncMock()) as recovery_pass,
            patch.object(casino_bot, "register_pvp_handlers") as register_pvp,
            patch.object(casino_bot, "register_baccara_handlers") as register_baccara,
            patch.object(casino_bot, "register_blackjack_handlers") as register_blackjack,
            patch.object(casino_bot.asyncio, "create_task") as create_task,
            patch.object(casino_bot.bot, "infinity_polling", AsyncMock()) as polling,
        ):
            with self.assertRaisesRegex(RuntimeError, "API unavailable"):
                await casino_bot.main()

        close_client.assert_awaited_once()
        register_pvp.assert_not_called()
        register_baccara.assert_not_called()
        register_blackjack.assert_not_called()
        create_task.assert_not_called()
        polling.assert_not_awaited()

    async def test_settings_failure_stops_before_handlers_cleaners_and_polling(self):
        client = AsyncMock()
        client.get_casino_settings.side_effect = RuntimeError("Settings unavailable")

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()) as close_client,
            patch.object(casino_bot, "run_recovery_pass", AsyncMock()) as recovery_pass,
            patch.object(casino_bot, "register_pvp_handlers") as register_pvp,
            patch.object(casino_bot, "register_baccara_handlers") as register_baccara,
            patch.object(casino_bot, "register_blackjack_handlers") as register_blackjack,
            patch.object(casino_bot.asyncio, "create_task") as create_task,
            patch.object(casino_bot.bot, "infinity_polling", AsyncMock()) as polling,
        ):
            with self.assertRaisesRegex(RuntimeError, "Settings unavailable"):
                await casino_bot.main()

        close_client.assert_awaited_once()
        register_pvp.assert_not_called()
        register_baccara.assert_not_called()
        register_blackjack.assert_not_called()
        create_task.assert_not_called()
        polling.assert_not_awaited()

    async def test_recovery_failure_stops_before_handlers_cleaners_and_polling(self):
        client = CasinoSettings()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()) as close_client,
            patch.object(casino_bot, "run_recovery_pass", AsyncMock(side_effect=RuntimeError("Recovery unavailable"))),
            patch.object(casino_bot, "register_pvp_handlers") as register_pvp,
            patch.object(casino_bot, "register_baccara_handlers") as register_baccara,
            patch.object(casino_bot, "register_blackjack_handlers") as register_blackjack,
            patch.object(casino_bot.asyncio, "create_task") as create_task,
            patch.object(casino_bot.bot, "infinity_polling", AsyncMock()) as polling,
        ):
            with self.assertRaisesRegex(RuntimeError, "Recovery unavailable"):
                await casino_bot.main()

        close_client.assert_awaited_once()
        register_pvp.assert_not_called()
        register_baccara.assert_not_called()
        register_blackjack.assert_not_called()
        create_task.assert_not_called()
        polling.assert_not_awaited()

    async def test_recovery_runs_before_handler_registration_and_raffle_stays_disabled(self):
        client = CasinoSettings()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})
        execution_order: list[str] = []

        async def recover(*args, **kwargs):
            execution_order.append("recovery")

        def register_pvp(*args):
            execution_order.append("pvp")

        def consume_cleaner(coroutine):
            coroutine.close()
            return Mock()

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()),
            patch.object(casino_bot, "run_recovery_pass", recover),
            patch.object(casino_bot, "register_pvp_handlers", register_pvp),
            patch.object(casino_bot, "register_baccara_handlers"),
            patch.object(casino_bot, "register_blackjack_handlers"),
            patch.object(casino_bot, "baccara_cleaner", AsyncMock()),
            patch.object(casino_bot, "blackjack_cleaner", AsyncMock()),
            patch.object(casino_bot.asyncio, "create_task", side_effect=consume_cleaner),
            patch.object(casino_bot.bot, "infinity_polling", AsyncMock()),
            patch.object(casino_bot.config, "RAFFLE_ENABLED", True),
        ):
            await casino_bot.main()

        self.assertEqual(execution_order, ["recovery", "pvp"])

        client = CasinoSettings()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()) as close_client,
            patch.object(casino_bot, "run_recovery_pass", AsyncMock()) as recovery_pass,
            patch.object(casino_bot, "register_pvp_handlers", side_effect=RuntimeError("Registration failed")),
            patch.object(casino_bot, "register_baccara_handlers") as register_baccara,
            patch.object(casino_bot, "register_blackjack_handlers") as register_blackjack,
            patch.object(casino_bot.asyncio, "create_task") as create_task,
            patch.object(casino_bot.bot, "infinity_polling", AsyncMock()) as polling,
        ):
            with self.assertRaisesRegex(RuntimeError, "Registration failed"):
                await casino_bot.main()

        close_client.assert_awaited_once()
        register_baccara.assert_not_called()
        register_blackjack.assert_not_called()
        create_task.assert_not_called()
        polling.assert_not_awaited()

    async def test_shutdown_cancels_and_awaits_all_background_workers(self):
        client = CasinoSettings()
        workers: list[asyncio.Task[None]] = []
        cancelled_workers: list[str] = []

        async def worker(name: str) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_workers.append(name)
                raise

        async def baccara_worker(*args):
            await worker("baccara")

        async def blackjack_worker(*args):
            await worker("blackjack")

        async def recovery_worker(*args, **kwargs):
            await worker("recovery")

        async def invitation_worker(*args, **kwargs):
            await worker("invitation")

        async def reaper_worker(*args, **kwargs):
            await worker("reaper")

        native_create_task = asyncio.create_task

        def create_task(coroutine):
            task = native_create_task(coroutine)
            workers.append(task)
            return task

        async def polling_once():
            await asyncio.sleep(0)

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()) as close_client,
            patch.object(casino_bot, "run_recovery_pass", AsyncMock()),
            patch.object(casino_bot, "register_pvp_handlers"),
            patch.object(casino_bot, "register_baccara_handlers"),
            patch.object(casino_bot, "register_blackjack_handlers"),
            patch.object(casino_bot, "baccara_cleaner", baccara_worker),
            patch.object(casino_bot, "blackjack_cleaner", blackjack_worker),
            patch.object(casino_bot, "recovery_outbox_loop", recovery_worker),
            patch.object(casino_bot, "pvp_invitation_loop", invitation_worker),
            patch.object(casino_bot, "reaper_loop", reaper_worker),
            patch.object(casino_bot.asyncio, "create_task", side_effect=create_task),
            patch.object(casino_bot.bot, "infinity_polling", polling_once),
        ):
            await casino_bot.main()

        self.assertEqual(len(workers), 5)
        self.assertTrue(all(task.cancelled() for task in workers))
        self.assertCountEqual(
            cancelled_workers, ["baccara", "blackjack", "recovery", "invitation", "reaper"]
        )
        close_client.assert_awaited_once()

    async def test_normal_shutdown_closes_client_after_polling(self):
        client = CasinoSettings()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})

        def consume_cleaner(coroutine):
            coroutine.close()
            return Mock()

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()) as close_client,
            patch.object(casino_bot, "run_recovery_pass", AsyncMock()) as recovery_pass,
            patch.object(casino_bot, "register_pvp_handlers") as register_pvp,
            patch.object(casino_bot, "register_baccara_handlers") as register_baccara,
            patch.object(casino_bot, "register_blackjack_handlers") as register_blackjack,
            patch.object(casino_bot, "baccara_cleaner", AsyncMock()),
            patch.object(casino_bot, "blackjack_cleaner", AsyncMock()),
            patch.object(casino_bot.asyncio, "create_task", side_effect=consume_cleaner) as create_task,
            patch.object(casino_bot.bot, "infinity_polling", AsyncMock()) as polling,
            patch.object(casino_bot.config, "RAFFLE_ENABLED", False),
        ):
            await casino_bot.main()

        register_pvp.assert_called_once_with(casino_bot.bot, client)
        register_baccara.assert_called_once_with(casino_bot.bot, client)
        register_blackjack.assert_called_once_with(casino_bot.bot, client)
        self.assertEqual(create_task.call_count, 5)
        recovery_pass.assert_awaited_once()
        polling.assert_awaited_once()
        close_client.assert_awaited_once()

    async def test_startup_registers_enabled_telegram_slash_menu(self):
        client = CasinoSettings()
        client.get_active_game_chat_binding = AsyncMock(return_value={"chat_id": -100123})

        def consume_cleaner(coroutine):
            coroutine.close()
            return Mock()

        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot, "close_focuspay_client", AsyncMock()),
            patch.object(casino_bot, "run_recovery_pass", AsyncMock()),
            patch.object(casino_bot, "register_pvp_handlers"),
            patch.object(casino_bot, "register_baccara_handlers"),
            patch.object(casino_bot, "register_blackjack_handlers"),
            patch.object(casino_bot, "baccara_cleaner", AsyncMock()),
            patch.object(casino_bot, "blackjack_cleaner", AsyncMock()),
            patch.object(casino_bot.asyncio, "create_task", side_effect=consume_cleaner),
            patch.object(casino_bot.bot, "infinity_polling", AsyncMock()),
            patch.object(casino_bot.bot, "set_my_commands", AsyncMock()) as set_cmds,
        ):
            await casino_bot.main()

        self.assertGreaterEqual(set_cmds.await_count, 4)
        names = [item.command for item in set_cmds.await_args_list[0].args[0]]
        self.assertEqual(names, [
            "newgame", "cub", "2cub", "baccara", "blackjack",
            "roulette", "jackpot", "rooms", "allgames",
        ])

    def _deposit_call(self, data, *, call_id="dep"):
        return SimpleNamespace(
            id=call_id,
            data=data,
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=11),
        )

    async def test_deposit_amount_error_uses_callback_alert(self):
        call = self._deposit_call("depamt:1")
        with (
            patch.object(casino_bot.config, "DEPOSITS_ENABLED", True),
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send,
        ):
            await casino_bot.deposit_amount_cb(call)
        send.assert_not_awaited()
        self.assertTrue(answer.await_args.kwargs.get("show_alert"))
        self.assertIn("Минимальная", answer.await_args.args[1])

    async def test_deposit_pay_create_failure_uses_callback_alert(self):
        casino_bot._pending_deposit_credit[7] = 500.0
        call = self._deposit_call("dep:pay:SBPRUB")
        client = AsyncMock()
        client.create_deposit.side_effect = RuntimeError("down")
        try:
            with (
                patch.object(casino_bot.config, "DEPOSITS_ENABLED", True),
                patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
                patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer,
                patch.object(casino_bot.bot, "send_message", AsyncMock()) as send,
            ):
                await casino_bot.deposit_pay_cb(call)
        finally:
            casino_bot._pending_deposit_credit.pop(7, None)
        send.assert_not_awaited()
        self.assertIn("Не удалось создать заявку", answer.await_args.args[1])
        self.assertTrue(answer.await_args.kwargs.get("show_alert"))

    async def test_deposit_pay_disabled_does_not_create_deal(self):
        casino_bot._pending_deposit_credit[7] = 500.0
        call = self._deposit_call("dep:pay:SBPRUB")
        client = AsyncMock()
        try:
            with (
                patch.object(casino_bot.config, "DEPOSITS_ENABLED", False),
                patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
                patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer,
                patch.object(casino_bot.bot, "send_message", AsyncMock()) as send,
            ):
                await casino_bot.deposit_pay_cb(call)
        finally:
            casino_bot._pending_deposit_credit.pop(7, None)
        client.create_deposit.assert_not_awaited()
        send.assert_not_awaited()
        self.assertIn("Пополнение скоро", answer.await_args.args[1])
        self.assertTrue(answer.await_args.kwargs.get("show_alert"))
        self.assertNotIn(7, casino_bot._pending_deposit_credit)

    async def test_deposit_amount_disabled_alerts_soon(self):
        call = self._deposit_call("depamt:500")
        with (
            patch.object(casino_bot.config, "DEPOSITS_ENABLED", False),
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send,
        ):
            await casino_bot.deposit_amount_cb(call)
        send.assert_not_awaited()
        self.assertIn("Пополнение скоро", answer.await_args.args[1])
        self.assertTrue(answer.await_args.kwargs.get("show_alert"))

    async def test_deposit_command_soon_when_disabled(self):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=7, type="private"),
            from_user=SimpleNamespace(id=7),
            text="/deposit 500",
        )
        client = AsyncMock()
        with (
            patch.object(casino_bot.config, "DEPOSITS_ENABLED", False),
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send,
        ):
            await casino_bot.deposit_handler(message)
        client.create_deposit.assert_not_awaited()
        self.assertIn("Пополнение скоро", send.await_args.args[1])

    async def test_deposit_cancel_conflict_uses_callback_alert(self):
        request = casino_bot.httpx.Request("POST", "http://deposit/cancel")
        response = casino_bot.httpx.Response(409, request=request)
        client = AsyncMock()
        client.cancel_deposit.side_effect = casino_bot.httpx.HTTPStatusError(
            "conflict", request=request, response=response
        )
        call = self._deposit_call("dep:cxl:42")
        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send,
            patch.object(casino_bot.bot, "edit_message_reply_markup", AsyncMock()),
        ):
            await casino_bot.deposit_request_cancel_cb(call)
        send.assert_not_awaited()
        self.assertTrue(answer.await_args.kwargs.get("show_alert"))
        self.assertIn("нельзя отменить", answer.await_args.args[1])

    async def test_deposit_cancel_success_uses_callback_alert(self):
        client = AsyncMock()
        call = self._deposit_call("dep:cxl:42")
        with (
            patch.object(casino_bot, "get_focuspay_client", AsyncMock(return_value=client)),
            patch.object(casino_bot.bot, "answer_callback_query", AsyncMock()) as answer,
            patch.object(casino_bot.bot, "send_message", AsyncMock()) as send,
            patch.object(casino_bot.bot, "edit_message_reply_markup", AsyncMock()) as edit,
        ):
            await casino_bot.deposit_request_cancel_cb(call)
        send.assert_not_awaited()
        edit.assert_awaited()
        self.assertIn("отменена", answer.await_args.args[1])
        self.assertTrue(answer.await_args.kwargs.get("show_alert"))


if __name__ == "__main__":
    unittest.main()
