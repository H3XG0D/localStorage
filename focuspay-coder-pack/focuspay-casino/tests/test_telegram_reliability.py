"""Entry probes must stop money calls; Telegram failures must not silence players."""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from telegram_reliability import (
    EntryDenied,
    TelegramEntryCheck,
    classify_telegram_delivery_error,
    wrap_callback,
)


class DeliveryClassificationTests(unittest.TestCase):
    def test_telegram_retry_after_is_preserved(self):
        exc = RuntimeError("Too Many Requests")
        exc.result_json = {
            "error_code": 429,
            "description": "Too Many Requests: retry after 17",
            "parameters": {"retry_after": 17},
        }
        self.assertEqual(classify_telegram_delivery_error(exc), ("rate_limited", 17))

    def test_only_explicit_forbidden_is_dm_unavailable(self):
        plain = RuntimeError("Forbidden: bot was blocked by the user")
        self.assertEqual(classify_telegram_delivery_error(plain), ("temporary", None))
        plain.error_code = 403
        self.assertEqual(classify_telegram_delivery_error(plain), ("dm_unavailable", None))


class EntryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = NS(get_me=AsyncMock(return_value=NS(id=900, username='fixture_bot')),
                      get_chat_member=AsyncMock(return_value=NS(status='administrator', can_delete_messages=True)),
                      get_chat=AsyncMock(return_value=NS(permissions=NS(can_send_messages=False))),
                      send_message=AsyncMock(), send_chat_action=AsyncMock(), answer_callback_query=AsyncMock())
        self.client = NS(get_active_game_chat_binding=AsyncMock(return_value={'chat_id': -100123}))

    async def test_blocked_dm_fails_before_hold(self):
        blocked = RuntimeError('Forbidden: bot was blocked by the user')
        blocked.error_code = 403
        blocked.description = 'Forbidden: bot was blocked by the user'
        self.bot.send_chat_action.side_effect = blocked
        hold = AsyncMock()
        check = TelegramEntryCheck(self.bot, self.client)
        with self.assertRaises(EntryDenied):
            await check(11)
            await hold()
        hold.assert_not_awaited()

    async def test_missing_group_rights_fail_closed(self):
        self.bot.get_chat_member.return_value = NS(status='member')
        with self.assertRaises(EntryDenied):
            await TelegramEntryCheck(self.bot, self.client)(11, game_chat_id=-100123)
        self.bot.send_chat_action.assert_not_awaited()

    async def test_restricted_but_writable_group_allows_game(self):
        self.bot.get_chat_member.return_value = NS(
            status='restricted', is_member=True, can_send_messages=True,
            can_send_other_messages=True)
        await TelegramEntryCheck(self.bot, self.client)(11, game_chat_id=-100123)
        self.bot.send_chat_action.assert_awaited_once()

    async def test_writable_member_does_not_need_admin(self):
        self.bot.get_chat_member.return_value = NS(status='member')
        self.bot.get_chat.return_value = NS(permissions=NS(can_send_messages=True))
        await TelegramEntryCheck(self.bot, self.client)(11, game_chat_id=-100123)
        self.bot.send_chat_action.assert_awaited_once()

    async def test_group_create_reaches_backend_for_all_v2_families(self):
        from focuspay_client import FocusPayClient
        self.bot.get_chat_member.return_value = NS(
            status='restricted', is_member=True, can_send_messages=True,
            can_send_other_messages=True)
        client = FocusPayClient(base_url='http://backend', internal_token='synthetic')
        client.entry_check = TelegramEntryCheck(self.bot, self.client)
        client._post_internal = AsyncMock(return_value={'success': True})
        try:
            for game in ('baccara', 'blackjack', 'pvp_dice'):
                with self.subTest(game=game):
                    payload = dict(creator_id=11, game_chat_id=-100123, game_type=game)
                    self.assertEqual(await client.create_v2_table(**payload), {'success': True})
                    client._post_internal.assert_awaited_with('/v2/tables', payload)
        finally:
            await client.close()

    async def test_muted_or_removed_bot_cannot_accept_stake(self):
        for member in (NS(status='left'), NS(status='kicked'),
                       NS(status='restricted', is_member=False, can_send_messages=True),
                       NS(status='restricted', is_member=True, can_send_messages=False)):
            self.bot.get_chat_member.return_value = member
            with self.assertRaises(EntryDenied):
                await TelegramEntryCheck(self.bot, self.client)(11, game_chat_id=-100123)
        self.bot.send_chat_action.assert_not_awaited()

    async def test_dm_game_does_not_require_group_binding(self):
        self.client.get_active_game_chat_binding.return_value = None
        await TelegramEntryCheck(self.bot, self.client)(11, game_chat_id=11)
        self.client.get_active_game_chat_binding.assert_not_awaited()
        self.bot.get_chat_member.assert_not_awaited()
        self.bot.send_chat_action.assert_awaited_once()

    async def test_group_must_match_binding(self):
        with self.assertRaises(EntryDenied):
            await TelegramEntryCheck(self.bot, self.client)(11, game_chat_id=-999)
        self.bot.send_chat_action.assert_not_awaited()

    async def test_telegram_outage_is_not_reported_as_missing_start(self):
        self.bot.send_chat_action.side_effect = TimeoutError()
        with self.assertRaisesRegex(EntryDenied, 'временно не отвечает'):
            await TelegramEntryCheck(self.bot, self.client)(11)

    async def test_client_does_not_post_create_when_preflight_fails(self):
        from focuspay_client import FocusPayClient
        client = FocusPayClient(base_url='http://backend', internal_token='synthetic')
        client.entry_check = TelegramEntryCheck(self.bot, self.client)
        client._post_internal = AsyncMock()
        self.bot.send_chat_action.side_effect = TimeoutError()
        try:
            with self.assertRaises(EntryDenied):
                await client.create_v2_table(creator_id=11, game_chat_id=11)
            client._post_internal.assert_not_awaited()
        finally:
            await client.close()

    async def test_success_requires_actual_dm_delivery(self):
        await TelegramEntryCheck(self.bot, self.client)(11)
        self.bot.send_chat_action.assert_awaited_once_with(11, "typing")

    async def test_callback_error_has_feedback_and_ack(self):
        handler = AsyncMock(side_effect=RuntimeError('unavailable'))
        call = NS(id='cb1', data='v2join:table', from_user=NS(id=11), message=NS(chat=NS(id=-100123)))
        await wrap_callback(self.bot, handler)(call)
        self.bot.answer_callback_query.assert_awaited()
        self.bot.send_message.assert_not_awaited()
        self.assertTrue(any(
            item.kwargs.get('show_alert') is True
            and 'Не удалось подтвердить действие' in item.args[1]
            for item in self.bot.answer_callback_query.await_args_list
            if len(item.args) > 1
        ))

    async def test_duplicate_callback_does_not_run_twice(self):
        handler = AsyncMock()
        call = NS(id='duplicate', data='v2join:table', from_user=NS(id=11), message=NS(chat=NS(id=-100123)))
        wrapped = wrap_callback(self.bot, handler)
        await wrapped(call)
        await wrapped(call)
        self.assertEqual(handler.await_count, 1)

    async def test_slow_callback_is_acknowledged_before_finishing(self):
        reached = asyncio.Event()
        async def handler(call):
            await reached.wait()
        call = NS(id='slow', data='v2join:table', from_user=NS(id=11), message=NS(chat=NS(id=-100123)))
        task = asyncio.create_task(wrap_callback(self.bot, handler)(call))
        await asyncio.sleep(.6)
        self.bot.answer_callback_query.assert_awaited()
        reached.set()
        await task
