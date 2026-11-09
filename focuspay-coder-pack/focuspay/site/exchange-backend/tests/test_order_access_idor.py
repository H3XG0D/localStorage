"""P1: доступ к заявке только владельцу (IP-IDOR закрыт)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _pool_with_row(row: dict):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def _get_pool():
        return pool

    return _get_pool


class OrderAccessIdorTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_access_ok(self):
        from order_service import _fetch_order_row_for_web

        row = {"order_id": "O1", "user_id": 100, "client_ip": "1.2.3.4", "status": "PENDING"}
        with patch("order_service.get_pool", new=_pool_with_row(row)):
            got = await _fetch_order_row_for_web("O1", 100, client_ip="1.2.3.4")
        self.assertIsNotNone(got)

    async def test_other_user_same_ip_denied(self):
        from order_service import _fetch_order_row_for_web

        row = {"order_id": "O1", "user_id": 100, "client_ip": "1.2.3.4", "status": "PENDING"}
        # Чужой user_id, но тот же IP — доступа быть НЕ должно (раньше был IDOR).
        with patch("order_service.get_pool", new=_pool_with_row(row)):
            got = await _fetch_order_row_for_web("O1", 999, client_ip="1.2.3.4")
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
