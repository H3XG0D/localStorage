"""Antispam must close Telegram callback spinner even on cooldown."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services import antispam


class RateLimitCallbackAnswerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        antispam._STATES.clear()

    def tearDown(self):
        antispam._STATES.clear()

    async def test_blocked_callback_answers_on_warn_cooldown(self):
        user_id = 4242
        now = time.time()
        antispam._STATES[user_id] = {
            "events": [],
            "penalty_level": 2,
            "blocked_until": now + 30,
            "last_violation": now,
            "last_warn": now,
        }
        query = SimpleNamespace(answer=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            callback_query=query,
            message=None,
        )
        ok = await antispam.rate_limit_ok(update)
        self.assertFalse(ok)
        query.answer.assert_awaited_once_with()
