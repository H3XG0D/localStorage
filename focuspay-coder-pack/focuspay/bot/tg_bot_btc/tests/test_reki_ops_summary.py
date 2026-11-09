"""Строка наличия по /reki в ops-уведомлении и в сводке пропусков."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services import no_shift_block_notify as notify  # noqa: E402
from services import owner_dashboard  # noqa: E402
from services.reki_snapshot import (  # noqa: E402
    SUB_TOKEN_CARD,
    SUB_TOKEN_SBP,
    RekiBand,
    RekiSection,
    RekiSnapshot,
)


def _snapshot(taken_at=None):
    return RekiSnapshot(
        sections={
            SUB_TOKEN_SBP: RekiSection(
                sub_token=SUB_TOKEN_SBP,
                count=11,
                total_rub=Decimal("78207.00"),
                bands=(RekiBand(Decimal("3000"), Decimal("3100"), Decimal("3100")),),
            ),
            SUB_TOKEN_CARD: RekiSection(
                sub_token=SUB_TOKEN_CARD,
                count=15,
                total_rub=Decimal("106202.00"),
                bands=(RekiBand(Decimal("2500"), Decimal("2500"), Decimal("2500")),),
            ),
        },
        taken_at=taken_at or datetime.now(timezone.utc),
    )


class NotifySummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_from_fresh_snapshot(self):
        with patch("services.reki_poll.load_snapshot", AsyncMock(return_value=_snapshot())):
            line = await notify._reki_summary()
        self.assertIn("78 207 ₽ СБП", line)
        self.assertIn("106 202 ₽", line)

    async def test_stale_snapshot_gives_nothing(self):
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        with patch("services.reki_poll.load_snapshot", AsyncMock(return_value=_snapshot(old))):
            self.assertIsNone(await notify._reki_summary())

    async def test_failure_is_swallowed(self):
        with patch("services.reki_poll.load_snapshot", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertIsNone(await notify._reki_summary())


class MissesTextTests(unittest.IsolatedAsyncioTestCase):
    async def _build(self, rows, snapshot):
        with patch.object(
            owner_dashboard, "fetch_missed_requisites", AsyncMock(return_value=(len(rows), rows))
        ), patch("services.reki_poll.load_snapshot", AsyncMock(return_value=snapshot)):
            return await owner_dashboard.build_misses_text(24)

    async def test_all_busy_rows_get_the_reki_line(self):
        rows = [{"reason": "all_busy", "fiat_amount": 3000, "created_at": datetime.now()}]
        text = await self._build(rows, _snapshot())
        self.assertIn("реки заняты", text)
        self.assertIn("78 207 ₽ СБП", text)

    async def test_no_shift_rows_stay_clean(self):
        rows = [{"reason": "no_shift", "fiat_amount": 3000, "created_at": datetime.now()}]
        text = await self._build(rows, _snapshot())
        self.assertNotIn("По /reki", text)

    async def test_empty_period_unchanged(self):
        with patch.object(
            owner_dashboard, "fetch_missed_requisites", AsyncMock(return_value=(0, []))
        ):
            text = await owner_dashboard.build_misses_text(24)
        self.assertIn("Пропусков нет.", text)


if __name__ == "__main__":
    unittest.main()
