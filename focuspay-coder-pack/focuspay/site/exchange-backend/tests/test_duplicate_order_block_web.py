"""P0: блокировка дублей BUY на сайте.

Инцидент: гость -48 создал две OPERATOR_PENDING заявки на 9000 ₽. Блокирующий
набор статусов в веб-флоу должен включать COMPLETED и OPERATOR_PENDING.
"""
import unittest
from unittest.mock import AsyncMock


class UserHasActiveOrderWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_true_when_active(self):
        from buy_order_web import _user_has_active_order

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        self.assertTrue(await _user_has_active_order(conn, -48))

    async def test_returns_false_when_none(self):
        from buy_order_web import _user_has_active_order

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        self.assertFalse(await _user_has_active_order(conn, -48))

    async def test_blocking_statuses_include_completed_and_operator(self):
        from buy_order_web import _user_has_active_order

        captured = {}

        async def fetchval(query, *args):
            captured["query"] = query
            return None

        conn = AsyncMock()
        conn.fetchval = fetchval
        await _user_has_active_order(conn, -48)
        q = captured["query"]
        for status in ("CREATED", "AWAITING_CHECK", "PENDING", "OPERATOR_PENDING", "COMPLETED"):
            self.assertIn(status, q)


class ActiveStatusesConstantTests(unittest.TestCase):
    def test_order_service_active_statuses(self):
        from order_service import ACTIVE_STATUSES

        self.assertIn("COMPLETED", ACTIVE_STATUSES)
        self.assertIn("OPERATOR_PENDING", ACTIVE_STATUSES)

    def test_ip_guard_active_statuses(self):
        from ip_order_guard import ACTIVE_STATUSES

        self.assertIn("COMPLETED", ACTIVE_STATUSES)


if __name__ == "__main__":
    unittest.main()
