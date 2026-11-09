"""Прогон авточистки и /clean без Telegram и без базы."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import RetryAfter

from handlers.group_antispam import group_antispam_handler
from handlers.group_cleanup import (
    clean_command,
    cleanup_daily,
    execute_cleanup,
    register_group_cleanup_handlers,
    start_cleanup,
)
from services.chat_call import CALL_ALLOW_USER_ID
from services.chat_cleanup import CLEAN_INTERVAL_SEC
from services.chat_members_scan import (
    ChatMemberScan,
    ScannedMember,
    _client_session_name,
    api_credentials,
    scan_ready,
)
import handlers.group_cleanup as group_cleanup


def _member(**kwargs: object) -> ScannedMember:
    payload = {
        "user_id": 1,
        "is_bot": False,
        "deleted": False,
        "presence": None,
        "was_online": None,
    }
    payload.update(kwargs)
    return ScannedMember(**payload)  # type: ignore[arg-type]


def _scan() -> ChatMemberScan:
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    fresh = datetime.now(timezone.utc)
    return ChatMemberScan(
        scanner_id=99,
        members=(
            _member(user_id=10, deleted=True, presence="online"),
            _member(user_id=10, deleted=True),
            _member(user_id=11, presence="empty"),
            _member(user_id=12, presence="offline", was_online=old),
            _member(user_id=13, presence="offline", was_online=fresh),
            _member(user_id=14, presence="last_month"),
            _member(user_id=15, is_bot=True, presence="empty"),
            _member(user_id=1, deleted=True),
            _member(user_id=99, presence="empty"),
            _member(user_id=16, presence=None),
            _member(user_id=CALL_ALLOW_USER_ID, deleted=True),
            _member(user_id=42, presence="empty"),
        ),
    )


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.get_chat_administrators = AsyncMock(
        return_value=[SimpleNamespace(user=SimpleNamespace(id=1))]
    )
    bot.ban_chat_member = AsyncMock()
    bot.unban_chat_member = AsyncMock()
    bot.send_message = AsyncMock()
    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
    return bot


class ExecuteCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        group_cleanup._active = False

    async def test_kicks_only_stale_and_deleted(self):
        bot = _bot()
        with (
            patch("handlers.group_cleanup.community_chat_id", return_value=-100555),
            patch("handlers.group_cleanup.scan_ready", return_value=True),
            patch("handlers.group_cleanup.scan_chat_members", AsyncMock(return_value=_scan())),
            patch("handlers.group_cleanup.TELEGRAM_ADMIN_IDS", [42]),
            patch("handlers.group_cleanup.forget_member", AsyncMock()) as forgot,
            patch("handlers.group_cleanup.asyncio.sleep", AsyncMock()),
        ):
            stats = await execute_cleanup(bot)
        self.assertEqual(stats.checked, 11)
        self.assertEqual(stats.stale, 2)
        self.assertEqual(stats.deleted, 1)
        self.assertTrue(stats.report)
        banned = [call.kwargs["user_id"] for call in bot.ban_chat_member.await_args_list]
        self.assertEqual(banned, [10, 11, 12])
        for call in bot.ban_chat_member.await_args_list:
            self.assertFalse(call.kwargs["revoke_messages"])
            self.assertEqual(call.kwargs["chat_id"], -100555)
        unbanned = [call.kwargs["user_id"] for call in bot.unban_chat_member.await_args_list]
        self.assertEqual(unbanned, [10, 11, 12])
        self.assertEqual(
            [call.args[1] for call in forgot.await_args_list],
            [10, 11, 12],
        )

    async def test_admin_list_failure_kicks_nobody(self):
        bot = _bot()
        bot.get_chat_administrators = AsyncMock(side_effect=RuntimeError("no"))
        with (
            patch("handlers.group_cleanup.community_chat_id", return_value=-100555),
            patch("handlers.group_cleanup.scan_ready", return_value=True),
            patch("handlers.group_cleanup.scan_chat_members", AsyncMock(return_value=_scan())),
        ):
            stats = await execute_cleanup(bot)
        self.assertEqual(stats.skipped, "admins")
        bot.ban_chat_member.assert_not_called()

    async def test_flood_wait_then_unban(self):
        bot = _bot()
        bot.ban_chat_member = AsyncMock(side_effect=[RetryAfter(1), None])
        scan = ChatMemberScan(
            scanner_id=99,
            members=(_member(user_id=11, presence="empty"),),
        )
        with (
            patch("handlers.group_cleanup.community_chat_id", return_value=-5),
            patch("handlers.group_cleanup.scan_ready", return_value=True),
            patch("handlers.group_cleanup.scan_chat_members", AsyncMock(return_value=scan)),
            patch("handlers.group_cleanup.TELEGRAM_ADMIN_IDS", []),
            patch("handlers.group_cleanup.forget_member", AsyncMock()),
            patch("handlers.group_cleanup.asyncio.sleep", AsyncMock()) as slept,
        ):
            stats = await execute_cleanup(bot)
        self.assertEqual(stats.stale, 1)
        self.assertEqual(bot.ban_chat_member.await_count, 2)
        bot.unban_chat_member.assert_awaited_once()
        slept.assert_awaited()


def _update(user_id: int, chat_id: int = -100555):
    message = MagicMock()
    message.reply_text = AsyncMock()
    user = SimpleNamespace(id=user_id, is_bot=False, username="admin")
    chat = SimpleNamespace(id=chat_id, title="focus", username=None, type="supergroup")
    update = MagicMock()
    update.effective_message = message
    update.effective_chat = chat
    update.effective_user = user
    context = MagicMock()
    context.bot = _bot()
    return update, context, message


class CleanCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        group_cleanup._active = False

    async def test_other_chat_is_refused(self):
        update, context, message = _update(CALL_ALLOW_USER_ID, chat_id=-9)
        with patch("handlers.group_cleanup.is_community_chat", return_value=False):
            await clean_command(update, context)
        message.reply_text.assert_awaited_once_with("Эта команда только в focus-чате.")

    async def test_member_cannot_start(self):
        update, context, message = _update(50)
        with (
            patch("handlers.group_cleanup.is_community_chat", return_value=True),
            patch("handlers.group_cleanup.scan_ready", return_value=True),
            patch("handlers.group_cleanup.start_cleanup", AsyncMock()) as start,
        ):
            await clean_command(update, context)
        start.assert_not_awaited()
        message.reply_text.assert_awaited_once_with("Команда только для админа чата.")

    async def test_missing_session_does_not_start(self):
        update, context, message = _update(CALL_ALLOW_USER_ID)
        with (
            patch("handlers.group_cleanup.is_community_chat", return_value=True),
            patch("handlers.group_cleanup.scan_ready", return_value=False),
            patch("handlers.group_cleanup.start_cleanup", AsyncMock()) as start,
        ):
            await clean_command(update, context)
        start.assert_not_awaited()
        message.reply_text.assert_awaited_once_with("Список участников не настроен.")

    async def test_admin_starts_cleanup(self):
        update, context, message = _update(7)
        context.bot.get_chat_member = AsyncMock(
            return_value=SimpleNamespace(status="administrator")
        )
        with (
            patch("handlers.group_cleanup.is_community_chat", return_value=True),
            patch("handlers.group_cleanup.scan_ready", return_value=True),
            patch("handlers.group_cleanup.start_cleanup", AsyncMock(return_value="started")) as start,
        ):
            await clean_command(update, context)
        start.assert_awaited_once()
        message.reply_text.assert_awaited_once_with("Чистка запущена.")

    async def test_busy_reply(self):
        update, context, message = _update(CALL_ALLOW_USER_ID)
        with (
            patch("handlers.group_cleanup.is_community_chat", return_value=True),
            patch("handlers.group_cleanup.scan_ready", return_value=True),
            patch("handlers.group_cleanup.start_cleanup", AsyncMock(return_value="busy")),
        ):
            await clean_command(update, context)
        message.reply_text.assert_awaited_once_with("Чистка уже идёт.")


class CleanupJobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        group_cleanup._active = False

    async def test_daily_waits_for_session(self):
        context = MagicMock()
        with (
            patch("handlers.group_cleanup.community_chat_id", return_value=-100555),
            patch("handlers.group_cleanup.scan_ready", return_value=False),
            patch("handlers.group_cleanup.start_cleanup", AsyncMock()) as start,
        ):
            await cleanup_daily(context)
        start.assert_not_awaited()

    async def test_second_start_is_busy(self):
        gate = asyncio.Event()

        async def hold(_bot: object):
            await gate.wait()
            return group_cleanup.CleanupStats()

        with patch("handlers.group_cleanup.execute_cleanup", side_effect=hold):
            first = await start_cleanup(MagicMock())
            second = await start_cleanup(MagicMock())
            self.assertEqual(first, "started")
            self.assertEqual(second, "busy")
            self.assertTrue(group_cleanup._active)
            gate.set()
            pending = [
                task
                for task in asyncio.all_tasks()
                if task.get_name() == "focusclear-cleanup"
            ]
            await asyncio.gather(*pending)
        self.assertFalse(group_cleanup._active)

    def test_job_is_daily(self):
        app = MagicMock()
        register_group_cleanup_handlers(app)
        app.job_queue.run_repeating.assert_called_once()
        kwargs = app.job_queue.run_repeating.call_args.kwargs
        self.assertEqual(kwargs["interval"], CLEAN_INTERVAL_SEC)
        self.assertEqual(kwargs["first"], CLEAN_INTERVAL_SEC)
        self.assertEqual(kwargs["name"], "focusclear_cleanup")

    def test_missing_job_queue_is_safe(self):
        app = MagicMock()
        app.job_queue = None
        register_group_cleanup_handlers(app)


class AntispamCleanSkipTests(unittest.IsolatedAsyncioTestCase):
    async def test_clean_command_is_not_deleted(self):
        message = MagicMock()
        message.text = "/clean"
        message.caption = None
        message.delete = AsyncMock()
        message.is_automatic_forward = False
        message.sender_chat = None
        user = SimpleNamespace(id=7, is_bot=False, username="a")
        chat = SimpleNamespace(id=-1001, title="focus", username=None, type="supergroup")
        update = MagicMock()
        update.effective_message = message
        update.effective_chat = chat
        update.effective_user = user
        context = MagicMock()
        with patch("handlers.group_antispam.is_watched_public_chat", return_value=True):
            await group_antispam_handler(update, context)
        message.delete.assert_not_called()


class ScanConfigTests(unittest.TestCase):
    def test_credentials_and_session_file(self):
        with patch.dict(os.environ, {"TELEGRAM_API_ID": "nope", "TELEGRAM_API_HASH": "h"}):
            self.assertIsNone(api_credentials())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "focusclear_user.session"
            env = {
                "TELEGRAM_API_ID": "100",
                "TELEGRAM_API_HASH": "hash",
                "FOCUSCLEAR_USER_SESSION": str(path),
            }
            with patch.dict(os.environ, env):
                self.assertEqual(api_credentials(), (100, "hash"))
                self.assertFalse(scan_ready())
                path.write_bytes(b"session")
                self.assertTrue(scan_ready())
                self.assertEqual(_client_session_name(path), str(path.with_suffix("")))

    def test_session_name_without_suffix_stays(self):
        self.assertEqual(_client_session_name(Path("/tmp/focusclear_user")), "/tmp/focusclear_user")


if __name__ == "__main__":
    unittest.main()
