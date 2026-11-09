"""Сборка /spam и запуск команды без сети и без Telethon."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import RetryAfter

from handlers.group_antispam import group_antispam_handler
from handlers.group_call import (
    _entities,
    _running,
    _send_batch,
    register_group_call_handlers,
    spam_command,
    track_chat_member,
    track_group_message,
)
from services.chat_call import (
    BATCH_SIZE,
    CALL_ALLOW_USER_ID,
    MASK_EMOJI,
    SEND_INTERVAL_SEC,
    CallUser,
    build_call_messages,
    is_call_command,
    quote_from_command,
    user_may_call,
    utf16_len,
)
from services.chat_roster import clean_username, should_refresh_roster


def _people(count: int) -> list[CallUser]:
    return [CallUser(user_id=index, first_name=f"U{index}") for index in range(1, count + 1)]


def _update(text: str, *, user_id: int, chat_type: str = "supergroup"):
    message = MagicMock()
    message.text = text
    message.message_id = 42
    message.reply_text = AsyncMock()
    message.caption = None
    message.entities = ()
    message.caption_entities = ()
    message.is_automatic_forward = False
    message.sender_chat = None
    message.delete = AsyncMock()
    user = SimpleNamespace(id=user_id, is_bot=False, username="admin")
    chat = SimpleNamespace(id=-1001, title="focus", username=None, type=chat_type)
    message.chat = chat
    update = MagicMock()
    update.effective_message = message
    update.effective_chat = chat
    update.effective_user = user
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    context = MagicMock()
    context.bot = bot
    return update, context, message, bot


class BuildCallTests(unittest.TestCase):
    def test_allow_id_is_the_requested_admin(self):
        self.assertEqual(CALL_ALLOW_USER_ID, 8854187047)

    def test_batches_of_six_repeat_the_quote(self):
        quote = "5 мест по 500!! Рулеточка!!!"
        messages = build_call_messages(quote, _people(13))
        self.assertEqual(len(messages), 3)
        self.assertEqual([len(item.mentions) for item in messages], [6, 6, 1])
        self.assertEqual(
            [mention.user_id for item in messages for mention in item.mentions],
            list(range(1, 14)),
        )
        for item in messages:
            self.assertTrue(item.text.startswith(quote + "\n"))

    def test_utf16_offsets_cover_mask_emoji(self):
        quote = "привет 😀"
        messages = build_call_messages(quote, [CallUser(user_id=9, first_name="Анна")])
        mention = messages[0].mentions[0]
        self.assertEqual(mention.offset, utf16_len(quote + "\n"))
        self.assertEqual(mention.length, 2)
        encoded = messages[0].text.encode("utf-16-le")
        chunk = encoded[mention.offset * 2 : (mention.offset + mention.length) * 2]
        self.assertEqual(chunk.decode("utf-16-le"), MASK_EMOJI[0])
        self.assertEqual(mention.first_name, "Анна")
        for emoji in MASK_EMOJI:
            self.assertEqual(utf16_len(emoji), 2)

    def test_skips_bots_deleted_and_duplicates(self):
        users = [
            CallUser(user_id=1, first_name="Bot", is_bot=True),
            CallUser(user_id=2, first_name="Gone", deleted=True),
            CallUser(user_id=3, first_name="Ann"),
            CallUser(user_id=3, first_name="Ann again"),
            CallUser(user_id=4, first_name="  "),
        ]
        messages = build_call_messages("цитата", users)
        self.assertEqual(len(messages), 1)
        self.assertEqual([item.user_id for item in messages[0].mentions], [3, 4])
        self.assertEqual(messages[0].mentions[1].first_name, "user")
        self.assertEqual(len(messages[0].mentions), 2)
        self.assertLessEqual(BATCH_SIZE, len(MASK_EMOJI))

    def test_registers_command_ahead_of_other_handlers(self):
        app = MagicMock()
        register_group_call_handlers(app)
        command_call = app.add_handler.call_args_list[0]
        handler = command_call.args[0]
        self.assertEqual(command_call.kwargs["group"], -1)
        self.assertIn("spam", handler.commands)

    def test_empty_quote(self):
        self.assertEqual(build_call_messages("   ", _people(2)), [])
        self.assertFalse(is_call_command("привет"))
        self.assertTrue(is_call_command("/spam@focuscleear_bot текст"))
        self.assertEqual(quote_from_command("/spam\nраз\nдва"), "раз\nдва")
        self.assertEqual(quote_from_command("/Spam@Bot   5 мест"), "5 мест")

    def test_who_may_call(self):
        self.assertTrue(user_may_call(CALL_ALLOW_USER_ID, "member"))
        self.assertTrue(user_may_call(CALL_ALLOW_USER_ID, None))
        self.assertTrue(user_may_call(1, "administrator"))
        self.assertTrue(user_may_call(1, "creator"))
        self.assertFalse(user_may_call(1, "member"))
        self.assertFalse(user_may_call(1, None))


class RosterTests(unittest.TestCase):
    def test_username_hides_behind_emoji(self):
        messages = build_call_messages(
            "цитата",
            [CallUser(user_id=9, first_name="Анна", username="@Ann_name")],
        )
        mention = messages[0].mentions[0]
        self.assertEqual(mention.username, "Ann_name")
        self.assertNotIn("Ann_name", messages[0].text)
        self.assertTrue(messages[0].text.endswith(MASK_EMOJI[0]))
        entity = _entities(messages[0])[0]
        self.assertEqual(entity.type, "text_mention")
        self.assertEqual(entity.user.username, "Ann_name")
        self.assertEqual(entity.user.id, 9)

    def test_clean_username(self):
        self.assertEqual(clean_username("@Ann_name"), "Ann_name")
        self.assertIsNone(clean_username("bad name"))
        self.assertIsNone(clean_username(""))

    def test_thin_roster_needs_a_full_check(self):
        self.assertTrue(should_refresh_roster(2, 1122, scanned_recently=True))
        self.assertFalse(should_refresh_roster(900, 1122, scanned_recently=True))
        self.assertTrue(should_refresh_roster(900, 1122, scanned_recently=False))


class SpamCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        tasks = list(_running.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        _running.clear()

    async def test_empty_text(self):
        update, context, message, _bot = _update("/spam", user_id=CALL_ALLOW_USER_ID)
        with patch("handlers.group_call.list_chat_members", AsyncMock()) as listed:
            await spam_command(update, context)
        message.reply_text.assert_awaited_once()
        self.assertIn("/spam", message.reply_text.await_args.args[0])
        listed.assert_not_called()
        self.assertEqual(_running, {})

    async def test_rejects_long_quote(self):
        update, context, message, _bot = _update(
            "/spam " + ("а" * 1001),
            user_id=CALL_ALLOW_USER_ID,
        )
        with patch("handlers.group_call.list_chat_members", AsyncMock()) as listed:
            await spam_command(update, context)
        message.reply_text.assert_awaited_once_with("Текст длиннее 1000 символов.")
        listed.assert_not_called()

    async def test_rejects_non_admin(self):
        update, context, message, bot = _update("/spam цитата", user_id=5)
        with patch("handlers.group_call.list_chat_members", AsyncMock()) as listed:
            await spam_command(update, context)
        message.reply_text.assert_awaited_once_with("Команда только для админа чата.")
        bot.get_chat_member.assert_awaited_once()
        listed.assert_not_called()

    async def test_admin_check_failure_refuses(self):
        update, context, message, bot = _update("/spam цитата", user_id=5)
        bot.get_chat_member = AsyncMock(side_effect=RuntimeError("telegram down"))
        with patch("handlers.group_call.list_chat_members", AsyncMock()) as listed:
            await spam_command(update, context)
        message.reply_text.assert_awaited_once_with("Команда только для админа чата.")
        listed.assert_not_called()

    async def test_allow_user_without_chat_admin(self):
        update, context, message, bot = _update("/spam цитата", user_id=CALL_ALLOW_USER_ID)
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_list(_chat_id: int):
            started.set()
            await release.wait()
            return _people(1)

        with (
            patch("handlers.group_call.list_chat_members", side_effect=slow_list),
            patch("handlers.group_call.asyncio.sleep", AsyncMock()),
        ):
            await spam_command(update, context)
            await asyncio.wait_for(started.wait(), timeout=1)
            bot.get_chat_member.assert_not_called()
            again, again_context, again_message, _again_bot = _update(
                "/spam ещё", user_id=CALL_ALLOW_USER_ID
            )
            await spam_command(again, again_context)
            again_message.reply_text.assert_awaited_once_with("В этом чате зазыв уже идёт.")
            task = next(iter(_running.values()))
            release.set()
            await task

        bot.delete_message.assert_awaited_once()
        bot.send_message.assert_awaited_once()
        sent = bot.send_message.await_args.kwargs
        self.assertNotIn("parse_mode", sent)
        self.assertEqual(sent["entities"][0].type, "text_mention")
        self.assertEqual(sent["entities"][0].user.id, 1)
        self.assertTrue(sent["text"].startswith("цитата\n"))

    async def test_chat_admin_can_start(self):
        update, context, _message, bot = _update("/spam цитата", user_id=5)
        bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="administrator"))
        tasks: list[asyncio.Task] = []
        real_create = asyncio.create_task

        def capture(coro, *args, **kwargs):
            task = real_create(coro, *args, **kwargs)
            tasks.append(task)
            return task

        with (
            patch("handlers.group_call.list_chat_members", AsyncMock(return_value=_people(1))),
            patch("handlers.group_call.asyncio.sleep", AsyncMock()),
            patch("handlers.group_call.asyncio.create_task", capture),
        ):
            await spam_command(update, context)
            await tasks[0]
        bot.delete_message.assert_awaited_once()

    async def test_nobody_and_list_failure_do_not_delete_command(self):
        update, context, _message, bot = _update("/spam цитата", user_id=CALL_ALLOW_USER_ID)
        tasks: list[asyncio.Task] = []
        real_create = asyncio.create_task

        def capture(coro, *args, **kwargs):
            task = real_create(coro, *args, **kwargs)
            tasks.append(task)
            return task

        with (
            patch(
                "handlers.group_call.list_chat_members",
                AsyncMock(return_value=[CallUser(user_id=1, first_name="B", is_bot=True)]),
            ),
            patch("handlers.group_call.asyncio.create_task", capture),
        ):
            await spam_command(update, context)
            await tasks[0]
        bot.delete_message.assert_not_called()
        self.assertEqual(bot.send_message.await_args.kwargs["text"], "В чате некого звать.")

        update, context, _message, bot = _update("/spam цитата", user_id=CALL_ALLOW_USER_ID)
        tasks.clear()
        with (
            patch(
                "handlers.group_call.list_chat_members",
                AsyncMock(side_effect=RuntimeError("db")),
            ),
            patch("handlers.group_call.asyncio.create_task", capture),
        ):
            await spam_command(update, context)
            await tasks[0]
        bot.delete_message.assert_not_called()
        self.assertEqual(
            bot.send_message.await_args.kwargs["text"],
            "Не удалось прочитать участников чата.",
        )

    async def test_interval_between_batches(self):
        update, context, _message, _bot = _update("/spam цитата", user_id=CALL_ALLOW_USER_ID)
        tasks: list[asyncio.Task] = []
        real_create = asyncio.create_task

        def capture(coro, *args, **kwargs):
            task = real_create(coro, *args, **kwargs)
            tasks.append(task)
            return task

        with (
            patch(
                "handlers.group_call.list_chat_members",
                AsyncMock(return_value=_people(BATCH_SIZE + 1)),
            ),
            patch("handlers.group_call.asyncio.sleep", AsyncMock()) as slept,
            patch("handlers.group_call.asyncio.create_task", capture),
        ):
            await spam_command(update, context)
            await tasks[0]
        slept.assert_awaited_once_with(SEND_INTERVAL_SEC)

    async def test_send_waits_on_flood(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=[RetryAfter(2), None])
        prepared = build_call_messages("hi", _people(1))[0]
        with patch("handlers.group_call.asyncio.sleep", AsyncMock()) as slept:
            await _send_batch(bot, -1001, prepared)
        self.assertEqual(bot.send_message.await_count, 2)
        slept.assert_awaited_once_with(2.5)
        self.assertNotIn("parse_mode", bot.send_message.await_args.kwargs)

    async def test_tracks_people_seen_in_the_chat(self):
        message = SimpleNamespace(
            new_chat_members=(
                SimpleNamespace(id=8, is_bot=False, username="joined", first_name="J"),
            ),
            left_chat_member=SimpleNamespace(id=9, is_bot=False, username="left", first_name="L"),
        )
        update = SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(id=-5, type="supergroup"),
            effective_user=SimpleNamespace(id=7, is_bot=False, username="writer", first_name="W"),
        )
        with (
            patch("handlers.group_call.remember_member", AsyncMock()) as remembered,
            patch("handlers.group_call.forget_member", AsyncMock()) as forgot,
        ):
            await track_group_message(update, MagicMock())
        self.assertEqual(remembered.await_count, 2)
        forgot.assert_awaited_once_with(-5, 9)

        left_update = SimpleNamespace(
            chat_member=SimpleNamespace(
                chat=SimpleNamespace(id=-5),
                new_chat_member=SimpleNamespace(
                    status="left",
                    user=SimpleNamespace(id=7, is_bot=False, username="writer", first_name="W"),
                ),
            )
        )
        with patch("handlers.group_call.forget_member", AsyncMock()) as forgot_status:
            await track_chat_member(left_update, MagicMock())
        forgot_status.assert_awaited_once_with(-5, 7)


class AntispamCallSkipTests(unittest.IsolatedAsyncioTestCase):
    async def test_allow_user_spam_command_is_not_deleted(self):
        message = MagicMock()
        message.text = "/spam пишите в лс"
        message.caption = None
        message.delete = AsyncMock()
        message.is_automatic_forward = False
        message.sender_chat = None
        user = SimpleNamespace(id=CALL_ALLOW_USER_ID, is_bot=False, username="a")
        chat = SimpleNamespace(id=-1001, title="focus", username=None, type="supergroup")
        update = MagicMock()
        update.effective_message = message
        update.effective_chat = chat
        update.effective_user = user
        context = MagicMock()
        context.bot = MagicMock()
        with patch("handlers.group_antispam.is_watched_public_chat", return_value=True):
            await group_antispam_handler(update, context)
        message.delete.assert_not_called()

    async def test_allow_user_other_text_still_checked(self):
        message = MagicMock()
        message.text = "пишите в лс"
        message.caption = None
        message.entities = ()
        message.caption_entities = ()
        message.delete = AsyncMock()
        message.is_automatic_forward = False
        message.sender_chat = None
        message.chat = SimpleNamespace(id=-1001, title="focus", username=None)
        user = SimpleNamespace(id=CALL_ALLOW_USER_ID, is_bot=False, username="a")
        chat = message.chat
        update = MagicMock()
        update.effective_message = message
        update.effective_chat = chat
        update.effective_user = user
        bot = MagicMock()
        bot.username = "focuscleear_bot"
        bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
        bot.ban_chat_member = AsyncMock()
        bot.send_message = AsyncMock()
        context = MagicMock()
        context.bot = bot
        with (
            patch("handlers.group_antispam.is_watched_public_chat", return_value=True),
            patch("handlers.group_antispam.TELEGRAM_ADMIN_IDS", []),
            patch("handlers.group_antispam.reports_group_id", return_value=0),
            patch("handlers.group_antispam.load_extra_phrases", AsyncMock(return_value=())),
        ):
            await group_antispam_handler(update, context)
        message.delete.assert_awaited_once()
        bot.ban_chat_member.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
