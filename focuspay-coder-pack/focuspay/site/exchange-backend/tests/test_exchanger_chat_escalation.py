"""Тесты эскалации чата внештатника."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from exchanger_chat_escalation import (
    EXCHANGER_CHAT_ESCALATION_SEC,
    _try_escalate,
    clear_exchanger_escalation,
)


class ExchangerEscalationTests(unittest.IsolatedAsyncioTestCase):
    def test_escalation_sec_is_60(self):
        self.assertEqual(EXCHANGER_CHAT_ESCALATION_SEC, 60)

    async def test_skips_when_admin_replied(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 3,
                "source": "exchanger",
                "chat_escalation_msg_id": 10,
                "external_exchanger_id": 1,
                "last_sender": "exchanger",
                "last_body": "Нужна помощь",
                "admin_replies_after": 1,
            }
        )
        conn.execute = AsyncMock()

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        import exchanger_chat_escalation as mod

        old_pool = mod.get_pool
        try:
            mod.get_pool = AsyncMock(return_value=pool)
            with patch.object(mod, "clear_exchanger_escalation", new=AsyncMock()) as clear:
                sent = await _try_escalate(3, 10)
        finally:
            mod.get_pool = old_pool

        self.assertFalse(sent)
        clear.assert_awaited_once_with(3)

    async def test_sends_when_still_waiting(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 3,
                "source": "exchanger",
                "chat_escalation_msg_id": 10,
                "external_exchanger_id": 1,
                "last_sender": "exchanger",
                "last_body": "Нужна помощь",
                "admin_replies_after": 0,
            }
        )
        conn.execute = AsyncMock()

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        import exchanger_chat_escalation as mod

        old_pool = mod.get_pool
        try:
            mod.get_pool = AsyncMock(return_value=pool)
            with patch(
                "chat_service.exchanger_snapshot",
                new=AsyncMock(
                    return_value={
                        "display_name": "Test",
                        "name": "Test",
                        "username": "test_ex",
                    }
                ),
            ), patch(
                "external_deals_telegram.external_deals_chat",
                return_value=(-100123, None),
            ), patch(
                "telegram_notify.send_ops_message",
                new=AsyncMock(),
            ) as send:
                sent = await _try_escalate(3, 10)
        finally:
            mod.get_pool = old_pool

        self.assertTrue(sent)
        send.assert_awaited_once()
        text = send.await_args.args[0]
        self.assertIn("Ответьте внештатнику", text)
        self.assertIn("Нужна помощь", text)

    async def test_clear_escalation_only_for_exchanger(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"source": "telegram"})
        conn.execute = AsyncMock()

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        import exchanger_chat_escalation as mod

        old_pool = mod.get_pool
        try:
            mod.get_pool = AsyncMock(return_value=pool)
            await clear_exchanger_escalation(5)
        finally:
            mod.get_pool = old_pool

        conn.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
