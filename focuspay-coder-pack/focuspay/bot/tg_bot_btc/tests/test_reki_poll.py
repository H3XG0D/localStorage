"""Конфиг опроса /reki, запись и чтение снимка."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

import services.db  # noqa: E402,F401  (patch-цель services.db.get_pool)
from services import reki_poll  # noqa: E402
from services.reki_snapshot import SUB_TOKEN_CARD, SUB_TOKEN_SBP, parse_reki_snapshot  # noqa: E402

SAMPLE = """🟢 Количество активных СБП: 2
💸 Доступно всего: 5503 RUB
🟢 2403 RUB - 2403 RUB
💸 Доступно: 2403 RUB
🟢 3000 RUB - 3100 RUB
💸 Доступно: 3100 RUB

🟢 Количество активных C2C: 1
💸 Доступно всего: 2500 RUB
🟢 2500 RUB - 2500 RUB
💸 Доступно: 2500 RUB"""

NOW = datetime(2026, 11, 2, 22, 33, tzinfo=timezone.utc)


class ConfigTests(unittest.TestCase):
    def test_peer_parsing(self):
        with patch.dict(os.environ, {"REKI_BOT_PEER": "@reki_bot"}, clear=False):
            self.assertEqual(reki_poll.reki_peer(), "reki_bot")
        with patch.dict(os.environ, {"REKI_BOT_PEER": "-1001234567"}, clear=False):
            self.assertEqual(reki_poll.reki_peer(), -1001234567)
        with patch.dict(os.environ, {"REKI_BOT_PEER": "  "}, clear=False):
            self.assertIsNone(reki_poll.reki_peer())

    def test_intervals_have_floors(self):
        with patch.dict(os.environ, {"REKI_POLL_SECONDS": "5", "REKI_SNAPSHOT_TTL_SECONDS": "1"}, clear=False):
            self.assertEqual(reki_poll.poll_seconds(), 30)
            self.assertEqual(reki_poll.snapshot_ttl_seconds(), 60)
        with patch.dict(os.environ, {"REKI_POLL_SECONDS": "nope"}, clear=False):
            self.assertEqual(reki_poll.poll_seconds(), reki_poll.DEFAULT_POLL_SECONDS)

    def test_not_ready_without_peer_or_session(self):
        with patch.dict(os.environ, {"REKI_BOT_PEER": ""}, clear=False):
            self.assertFalse(reki_poll.poll_ready())
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "reki.session"
            session.write_text("x")
            env = {
                "REKI_BOT_PEER": "@reki_bot",
                "REKI_USER_SESSION": str(session),
                "TELEGRAM_API_ID": "100",
                "TELEGRAM_API_HASH": "hash",
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertTrue(reki_poll.poll_ready())
                self.assertEqual(reki_poll.reki_session_path(), session)


class StoreTests(unittest.IsolatedAsyncioTestCase):
    def _pool(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire)
        return pool, conn

    async def test_store_rewrites_everything(self):
        pool, conn = self._pool()
        snapshot = parse_reki_snapshot(SAMPLE, taken_at=NOW)
        with patch("services.db.get_pool", AsyncMock(return_value=pool)):
            await reki_poll.store_snapshot(snapshot)
        sql = [call.args[0] for call in conn.execute.await_args_list]
        self.assertIn("DELETE FROM reki_snapshots", sql)
        self.assertIn("DELETE FROM reki_snapshot_meta", sql)
        inserts = [s for s in sql if "INSERT INTO reki_snapshots" in s]
        metas = [s for s in sql if "INSERT INTO reki_snapshot_meta" in s]
        self.assertEqual(len(inserts), 3)
        self.assertEqual(len(metas), 2)

    async def test_load_rebuilds_snapshot(self):
        pool, conn = self._pool()
        conn.fetch = AsyncMock(
            side_effect=[
                [
                    {"sub_token": SUB_TOKEN_SBP, "count": 2, "total_rub": Decimal("5503.00"), "snapshot_at": NOW},
                    {"sub_token": SUB_TOKEN_CARD, "count": 1, "total_rub": Decimal("2500.00"), "snapshot_at": NOW},
                ],
                [
                    {"sub_token": SUB_TOKEN_SBP, "min_rub": Decimal("3000"), "max_rub": Decimal("3100"), "available_rub": Decimal("3100")},
                    {"sub_token": SUB_TOKEN_CARD, "min_rub": Decimal("2500"), "max_rub": Decimal("2500"), "available_rub": Decimal("2500")},
                ],
            ]
        )
        with patch("services.db.get_pool", AsyncMock(return_value=pool)):
            snapshot = await reki_poll.load_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.taken_at, NOW)
        self.assertEqual(len(snapshot.bands(SUB_TOKEN_SBP)), 1)
        self.assertEqual(snapshot.section(SUB_TOKEN_CARD).count, 1)
        self.assertTrue(snapshot.is_fresh(now=NOW))

    async def test_load_survives_db_error(self):
        with patch("services.db.get_pool", AsyncMock(side_effect=RuntimeError("down"))):
            self.assertIsNone(await reki_poll.load_snapshot())


class PollOnceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unparsable_reply_is_not_stored(self):
        with patch.object(reki_poll, "fetch_reki_text", AsyncMock(return_value="ничего нет")), patch.object(
            reki_poll, "store_snapshot", AsyncMock()
        ) as store:
            self.assertIsNone(await reki_poll.poll_once())
            store.assert_not_awaited()

    async def test_good_reply_is_cached_and_stored(self):
        with patch.object(reki_poll, "fetch_reki_text", AsyncMock(return_value=SAMPLE)), patch.object(
            reki_poll, "store_snapshot", AsyncMock()
        ) as store:
            snapshot = await reki_poll.poll_once()
        self.assertIsNotNone(snapshot)
        store.assert_awaited_once()
        self.assertIs(reki_poll.cached_snapshot(), snapshot)

    async def test_store_failure_does_not_break_poll(self):
        with patch.object(reki_poll, "fetch_reki_text", AsyncMock(return_value=SAMPLE)), patch.object(
            reki_poll, "store_snapshot", AsyncMock(side_effect=RuntimeError("db"))
        ):
            self.assertIsNotNone(await reki_poll.poll_once())


if __name__ == "__main__":
    unittest.main()
