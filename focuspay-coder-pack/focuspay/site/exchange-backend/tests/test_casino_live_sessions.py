"""Concurrent PvP seats and the 10-second start countdown helper."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException

from casino_live_sessions import assert_can_sit, count_live_pvp_seats, max_concurrent_games


class LiveSessionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_max_concurrent_defaults_to_ten(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value={"value": 10})
        self.assertEqual(await max_concurrent_games(conn), 10)

    async def test_assert_can_sit_rejects_eleventh(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[{"value": 10}, 10, 0, 0, 0])
        with self.assertRaises(HTTPException) as raised:
            await assert_can_sit(conn, 7)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("10", str(raised.exception.detail))

    async def test_count_sums_rooms_v2_jackpot_roulette(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[3, 2, 1, 1])
        self.assertEqual(await count_live_pvp_seats(conn, 7), 7)
