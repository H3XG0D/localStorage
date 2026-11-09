import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from games.chat_reaper import (
    TTL_HELP,
    TTL_RESULT,
    pending,
    reply_ephemeral,
    reset_state,
    send_ephemeral,
    sweep,
    track,
    track_group_result,
    try_delete_user_message,
)


class ChatReaperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_state()

    def tearDown(self):
        reset_state()

    async def test_sweep_deletes_expired_and_keeps_future(self):
        bot = SimpleNamespace(delete_message=AsyncMock())
        now = time.monotonic()
        track(-100, 1, ttl=0)
        track(-100, 2, ttl=60)
        deleted = await sweep(bot, now=now + 1)
        self.assertEqual(deleted, 1)
        bot.delete_message.assert_awaited_once_with(-100, 1)
        left = pending()
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0][1:], (-100, 2))

    async def test_missing_message_is_dropped_silently(self):
        bot = SimpleNamespace(
            delete_message=AsyncMock(side_effect=RuntimeError("Bad Request: message to delete not found"))
        )
        track(7, 9, ttl=0)
        deleted = await sweep(bot, now=time.monotonic() + 1)
        self.assertEqual(deleted, 0)
        self.assertEqual(pending(), [])

    async def test_no_rights_warns_once_and_does_not_raise(self):
        bot = SimpleNamespace(
            delete_message=AsyncMock(side_effect=RuntimeError("Forbidden: not enough rights to delete"))
        )
        track(-5, 3, ttl=0)
        track(-5, 4, ttl=0)
        deleted = await sweep(bot, now=time.monotonic() + 1)
        self.assertEqual(deleted, 0)
        self.assertEqual(bot.delete_message.await_count, 2)

    async def test_group_result_expires_after_twenty_seconds(self):
        bot = SimpleNamespace(delete_message=AsyncMock())
        now = 1_000.0
        with patch("games.chat_reaper.time.monotonic", return_value=now):
            track(-100, 5, TTL_RESULT)
        self.assertEqual(TTL_RESULT, 20)
        self.assertEqual(await sweep(bot, now=now + 19), 0)
        bot.delete_message.assert_not_awaited()
        self.assertEqual(await sweep(bot, now=now + 20), 1)
        bot.delete_message.assert_awaited_once_with(-100, 5)

    async def test_group_result_skips_private_chats(self):
        now = 5_000.0
        with patch("games.chat_reaper.time.monotonic", return_value=now):
            track_group_result(77, SimpleNamespace(message_id=3))
            track_group_result(-88, SimpleNamespace(message_id=4))
        self.assertEqual(
            [(item[1], item[2], item[0]) for item in pending()],
            [(-88, 4, now + TTL_RESULT)],
        )

    async def test_send_and_reply_ephemeral_track_message_ids(self):
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=11)),
            reply_to=AsyncMock(return_value=SimpleNamespace(message_id=12)),
        )
        await send_ephemeral(bot, 7, "help", TTL_HELP, parse_mode="HTML")
        message = SimpleNamespace(chat=SimpleNamespace(id=7, type="private"), message_id=99)
        await reply_ephemeral(bot, message, "err", 30)
        ids = {(item[1], item[2]) for item in pending()}
        self.assertEqual(ids, {(7, 11), (7, 12)})

    async def test_try_delete_user_message_only_in_group(self):
        bot = SimpleNamespace(delete_message=AsyncMock())
        dm = SimpleNamespace(
            chat=SimpleNamespace(id=7, type="private"),
            message_id=21,
        )
        group = SimpleNamespace(
            chat=SimpleNamespace(id=-100, type="supergroup"),
            message_id=22,
        )
        self.assertFalse(await try_delete_user_message(bot, dm))
        bot.delete_message.assert_not_awaited()
        self.assertTrue(await try_delete_user_message(bot, group))
        bot.delete_message.assert_awaited_once_with(-100, 22)

    async def test_try_delete_user_skips_chat_after_rights_failure(self):
        bot = SimpleNamespace(
            delete_message=AsyncMock(side_effect=RuntimeError("not enough rights to delete messages"))
        )
        group = SimpleNamespace(
            chat=SimpleNamespace(id=-200, type="group"),
            message_id=3,
        )
        self.assertFalse(await try_delete_user_message(bot, group))
        self.assertFalse(await try_delete_user_message(bot, group))
        self.assertEqual(bot.delete_message.await_count, 1)

    async def test_try_delete_retries_after_rights_cooldown(self):
        import games.chat_reaper as reaper

        previous = reaper.SKIP_RIGHTS_SECONDS
        reaper.SKIP_RIGHTS_SECONDS = 0
        bot = SimpleNamespace(
            delete_message=AsyncMock(side_effect=RuntimeError("not enough rights to delete messages"))
        )
        group = SimpleNamespace(
            chat=SimpleNamespace(id=-201, type="group"),
            message_id=4,
        )
        try:
            self.assertFalse(await try_delete_user_message(bot, group))
            self.assertFalse(await try_delete_user_message(bot, group))
            self.assertEqual(bot.delete_message.await_count, 2)
        finally:
            reaper.SKIP_RIGHTS_SECONDS = previous

    async def test_group_type_enum_is_treated_as_group(self):
        from games.chat_reaper import is_group_chat

        self.assertTrue(is_group_chat(SimpleNamespace(type=SimpleNamespace(value="group"))))
        self.assertTrue(is_group_chat(SimpleNamespace(type="ChatType.SUPERGROUP")))


if __name__ == "__main__":
    unittest.main()
