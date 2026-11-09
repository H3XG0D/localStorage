from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from routers.admin_operators import admin_close_operator_shift


class AdminForceCloseShiftAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_sends_high_severity_alert_with_admin_and_shift_details(self):
        ended_at = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
        row = {"id": 41, "operator_id": 7, "ended_at": ended_at}
        conn = AsyncMock()
        conn.fetchrow.return_value = row
        conn.fetchval.return_value = "Operator Seven"

        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        alert = MagicMock()

        with (
            patch("routers.admin_operators.get_pool", new=AsyncMock(return_value=pool)),
            patch(
                "operator_shift_store.sync_active_shift_user_ids_from_db",
                new=AsyncMock(),
            ),
            patch("operator_shift_notify.notify_operator_shift", new=AsyncMock()),
            patch("security_alerts.send_security_alert", new=alert),
        ):
            result = await admin_close_operator_shift(
                operator_id=7,
                _admin={"id": 3, "username": "owner"},
            )

        self.assertEqual(result["shift"]["id"], 41)
        alert.assert_called_once()
        kwargs = alert.call_args.kwargs
        self.assertEqual(kwargs["threat_type"], "admin_force_close_shift")
        self.assertEqual(kwargs["extra"]["severity"], "high")
        self.assertEqual(kwargs["extra"]["admin"], "owner (id=3)")
        self.assertEqual(kwargs["extra"]["operator"], "Operator Seven")
        self.assertEqual(kwargs["extra"]["operator_id"], 7)
        self.assertEqual(kwargs["extra"]["shift_id"], 41)

    async def test_alert_failure_does_not_fail_successful_close(self):
        ended_at = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
        conn = AsyncMock()
        conn.fetchrow.return_value = {
            "id": 41,
            "operator_id": 7,
            "ended_at": ended_at,
        }
        conn.fetchval.return_value = "Operator Seven"

        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with (
            patch("routers.admin_operators.get_pool", new=AsyncMock(return_value=pool)),
            patch(
                "operator_shift_store.sync_active_shift_user_ids_from_db",
                new=AsyncMock(),
            ),
            patch("operator_shift_notify.notify_operator_shift", new=AsyncMock()),
            patch(
                "security_alerts.send_security_alert",
                side_effect=RuntimeError("telegram unavailable"),
            ),
        ):
            result = await admin_close_operator_shift(
                operator_id=7,
                _admin={"id": 3, "username": "owner"},
            )

        self.assertEqual(result["shift"]["ended_at"], ended_at.isoformat())
        conn.fetchrow.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
