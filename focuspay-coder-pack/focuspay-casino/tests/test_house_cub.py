import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.telebot_stub import TelebotModules


with TelebotModules("games.house_cub", "games.site_links"):
    house_cub = importlib.import_module("games.house_cub")


class Bot:
    def __init__(self):
        self.reply_to = AsyncMock()
        self.send_dice = AsyncMock(
            return_value=SimpleNamespace(dice=SimpleNamespace(emoji="🎲", value=3))
        )
        self.answer_callback_query = AsyncMock()
        self.edit_message_reply_markup = AsyncMock()


class HouseCubDiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        house_cub._house_cub_busy.clear()
        house_cub._house_cub_locks.clear()
        self.sleep = AsyncMock()
        self.sleep_patcher = patch.object(house_cub, "wait_dice_landed", self.sleep)
        self.sleep_patcher.start()
        self.bot = Bot()
        self.client = SimpleNamespace(
            get_casino_settings=AsyncMock(
                return_value={
                    "enabled_games": {"cub": True},
                    "min_bet_rub": {"amount": 10},
                    "max_bet_rub": {"amount": 100000},
                }
            ),
            open_cub=AsyncMock(
                return_value={
                    "success": True,
                    "game_id": "cub-1",
                    "already_open": False,
                    "stake_rub": "10.00",
                    "status": "waiting_player_roll",
                }
            ),
            get_pending_cub=AsyncMock(
                return_value={"success": True, "pending": {"game_id": "cub-1", "stake_rub": "10.00"}}
            ),
            resolve_cub=AsyncMock(
                return_value={
                    "success": True,
                    "tie": False,
                    "player_value": 5,
                    "house_value": 3,
                    "payout_rub": "19.00",
                    "outcome": {"kind": "win", "winner_id": 77},
                }
            ),
            get_balance=AsyncMock(return_value=50.25),
        )

    def tearDown(self):
        self.sleep_patcher.stop()
        house_cub._house_cub_busy.clear()
        house_cub._house_cub_locks.clear()

    def _private_message(self, *, emoji="🎲", value=5, text="/cub 10"):
        return SimpleNamespace(
            text=text,
            chat=SimpleNamespace(id=77, type="private"),
            from_user=SimpleNamespace(id=77, is_bot=False),
            dice=SimpleNamespace(emoji=emoji, value=value),
        )

    async def test_start_asks_to_throw_without_hmac(self):
        await house_cub.start_house_cub(self.bot, self.client, self._private_message())
        self.client.open_cub.assert_awaited_once()
        self.assertEqual(self.client.open_cub.await_args.kwargs["telegram_id"], 77)
        text = self.bot.reply_to.await_args.args[1]
        self.assertIn("Кинь 🎲 сюда", text)
        self.assertNotIn("Смотреть на сайте", text)
        self.assertNotIn("Commit", text)
        self.assertNotIn("Seed", text)
        self.assertNotIn("HMAC", text)

    async def test_dice_sends_house_die_then_settles(self):
        handled = await house_cub.try_handle_house_cub_dice(
            self.bot, self.client, self._private_message()
        )
        self.assertTrue(handled)
        self.bot.send_dice.assert_awaited_once_with(chat_id=77, emoji="🎲")
        self.client.resolve_cub.assert_awaited_once_with(
            game_id="cub-1", telegram_id=77, player_value=5, house_value=3
        )
        text = self.bot.reply_to.await_args.args[1]
        self.assertIn("Ты 5, казино 3 — выигрыш", text)
        self.assertIn("19.00 ₽", text)
        self.assertIn("Баланс: 50.25 ₽", text)
        self.assertNotIn("🏁", text)
        self.assertNotIn("Commit", text)
        self.assertNotIn("Seed", text)
        self.client.get_balance.assert_awaited_once_with(77)
        self.assertEqual(self.sleep.await_count, 2)

    async def test_waits_for_player_face_then_casino_then_result(self):
        order: list[str] = []

        async def wait():
            order.append("wait")

        async def send_dice(**kwargs):
            order.append("send_dice")
            return SimpleNamespace(dice=SimpleNamespace(emoji="🎲", value=3))

        async def resolve_cub(**kwargs):
            order.append("resolve")
            return {
                "success": True,
                "tie": False,
                "player_value": 5,
                "house_value": 3,
                "payout_rub": "19.00",
                "outcome": {"kind": "win", "winner_id": 77},
            }

        async def reply_to(*args, **kwargs):
            order.append("result")

        self.sleep.side_effect = wait
        self.bot.send_dice.side_effect = send_dice
        self.client.resolve_cub.side_effect = resolve_cub
        self.bot.reply_to.side_effect = reply_to

        await house_cub.try_handle_house_cub_dice(self.bot, self.client, self._private_message())

        self.assertEqual(order, ["wait", "send_dice", "wait", "resolve", "result"])

    async def test_tie_asks_to_throw_again_without_resolve_payout_text(self):
        self.client.resolve_cub = AsyncMock(
            return_value={"success": True, "tie": True, "player_value": 4, "house_value": 4}
        )
        handled = await house_cub.try_handle_house_cub_dice(
            self.bot, self.client, self._private_message(value=4)
        )
        self.assertTrue(handled)
        self.assertEqual(self.bot.reply_to.await_args.args[1], house_cub.TIE_PROMPT)
        self.client.get_balance.assert_not_awaited()

    async def test_wrong_emoji_is_consumed_without_resolve(self):
        handled = await house_cub.try_handle_house_cub_dice(
            self.bot, self.client, self._private_message(emoji="🎯", value=5)
        )
        self.assertTrue(handled)
        self.bot.send_dice.assert_not_awaited()
        self.client.resolve_cub.assert_not_awaited()
        self.sleep.assert_not_awaited()
        self.assertIn("🎲", self.bot.reply_to.await_args.args[1])

    async def test_no_pending_round_is_not_consumed(self):
        self.client.get_pending_cub = AsyncMock(return_value={"success": True, "pending": None})
        handled = await house_cub.try_handle_house_cub_dice(
            self.bot, self.client, self._private_message()
        )
        self.assertFalse(handled)
        self.bot.send_dice.assert_not_awaited()

    async def test_bot_dice_in_private_is_swallowed(self):
        message = self._private_message()
        message.from_user = SimpleNamespace(id=1, is_bot=True)
        handled = await house_cub.try_handle_house_cub_dice(self.bot, self.client, message)
        self.assertTrue(handled)
        self.client.get_pending_cub.assert_not_awaited()
        self.bot.send_dice.assert_not_awaited()

    async def test_group_dice_is_not_consumed(self):
        message = self._private_message()
        message.chat = SimpleNamespace(id=-100123, type="supergroup")
        handled = await house_cub.try_handle_house_cub_dice(self.bot, self.client, message)
        self.assertFalse(handled)
        self.client.get_pending_cub.assert_not_awaited()
