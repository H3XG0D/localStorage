"""Доставка уведомления о закрытии реквизитов PayFast."""
import inspect
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import services.db


NOW = datetime.now(timezone.utc)
ORDER = {
    "order_id": "PF-NOTICE-1",
    "user_id": 42,
    "payment_snapshot": {
        "merchant_expires_at": (NOW + timedelta(minutes=6)).isoformat(),
    },
}
# asyncpg отдаёт jsonb строкой, пока не навешан кодек — как на проде.
ORDER_RAW_SNAPSHOT = {
    "order_id": "PF-NOTICE-2",
    "user_id": 42,
    "payment_snapshot": json.dumps(ORDER["payment_snapshot"]),
}


class PayfastRequisitesCloseNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_notice_delivered_only_after_successful_send(self):
        bot = AsyncMock()
        marker = "payment_requisites_closed_7m_sent_at"
        with patch(
            "services.db.get_orders_with_closed_payfast_requisites",
            new=AsyncMock(return_value=[ORDER]),
        ), patch(
            "services.db.get_orders_needing_payment_nudge",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.db.acquire_order_payment_snapshot_lease",
            new=AsyncMock(return_value="lease-1"),
        ), patch(
            "services.db.complete_order_payment_snapshot_lease",
            new=AsyncMock(return_value=True),
        ) as complete, patch(
            "services.db.release_order_payment_snapshot_lease",
            new=AsyncMock(),
        ) as release:
            from services.order_expirer import _send_payment_nudges

            await _send_payment_nudges(bot)

        bot.send_message.assert_awaited()
        complete.assert_awaited_once_with(ORDER["order_id"], marker, "lease-1")
        release.assert_not_awaited()

    async def test_releases_lease_when_telegram_delivery_fails(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("telegram unavailable"))
        marker = "payment_requisites_closed_7m_sent_at"
        with patch(
            "services.db.get_orders_with_closed_payfast_requisites",
            new=AsyncMock(return_value=[ORDER]),
        ), patch(
            "services.db.get_orders_needing_payment_nudge",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.db.acquire_order_payment_snapshot_lease",
            new=AsyncMock(return_value="lease-1"),
        ), patch(
            "services.db.complete_order_payment_snapshot_lease",
            new=AsyncMock(),
        ) as complete, patch(
            "services.db.release_order_payment_snapshot_lease",
            new=AsyncMock(return_value=True),
        ) as release:
            from services.order_expirer import _send_payment_nudges

            await _send_payment_nudges(bot)

        complete.assert_not_awaited()
        release.assert_awaited_once_with(ORDER["order_id"], marker, "lease-1")

    async def test_sends_notice_when_snapshot_arrives_as_json_string(self):
        bot = AsyncMock()
        marker = "payment_requisites_closed_7m_sent_at"
        with patch(
            "services.db.get_orders_with_closed_payfast_requisites",
            new=AsyncMock(return_value=[ORDER_RAW_SNAPSHOT]),
        ), patch(
            "services.db.get_orders_needing_payment_nudge",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.db.acquire_order_payment_snapshot_lease",
            new=AsyncMock(return_value="lease-1"),
        ), patch(
            "services.db.complete_order_payment_snapshot_lease",
            new=AsyncMock(return_value=True),
        ) as complete, patch(
            "services.db.release_order_payment_snapshot_lease",
            new=AsyncMock(),
        ) as release:
            from services.order_expirer import _send_payment_nudges

            await _send_payment_nudges(bot)

        bot.send_message.assert_awaited()
        complete.assert_awaited_once_with(ORDER_RAW_SNAPSHOT["order_id"], marker, "lease-1")
        release.assert_not_awaited()


class PaymentSnapshotLeaseFormatTests(unittest.TestCase):
    """lease_until должен писаться в том же формате, который читают запросы."""

    def _lease_regex(self) -> str:
        source = inspect.getsource(services.db.acquire_order_payment_snapshot_lease)
        found = re.search(r"'(\^\\\\d\{4\}[^']+)'", source)
        self.assertIsNotNone(found, "в запросе нет регекспа lease_until")
        return found.group(1).replace("\\\\", "\\")

    def test_written_format_matches_reader_regex(self):
        written = (NOW + timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        self.assertRegex(written, self._lease_regex())

    def test_postgres_text_cast_would_not_match(self):
        legacy = (NOW + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S.%f+00")
        self.assertNotRegex(legacy, self._lease_regex())

    def test_acquire_writes_iso_timestamp(self):
        source = inspect.getsource(services.db.acquire_order_payment_snapshot_lease)
        self.assertIn('YYYY-MM-DD"T"HH24:MI:SS.US"Z"', source)
        self.assertNotIn("($4 * interval '1 second'))::text", source)


if __name__ == "__main__":
    unittest.main()
