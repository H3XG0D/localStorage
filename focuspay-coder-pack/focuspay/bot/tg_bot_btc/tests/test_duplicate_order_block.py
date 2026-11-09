"""P0: блокировка дублей BUY-заявок.

Инцидент: клиент создал две заявки на 9000 ₽ с разницей 17 сек, потому что
COMPLETED (ждёт выплату) не блокировал новую покупку. Эти тесты фиксируют, что
блокирующий набор статусов включает COMPLETED и OPERATOR_PENDING, и что функция
возвращает True при наличии активной заявки.
"""
import unittest
from unittest.mock import AsyncMock, patch


BLOCKING_REQUIRED = {"CREATED", "AWAITING_CHECK", "PENDING", "OPERATOR_PENDING", "COMPLETED"}


class UserHasActiveBuyOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_true_when_active_exists(self):
        from services.db import user_has_active_buy_order

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        self.assertTrue(await user_has_active_buy_order(conn, 555))

    async def test_returns_false_when_none(self):
        from services.db import user_has_active_buy_order

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        self.assertFalse(await user_has_active_buy_order(conn, 555))

    async def test_blocking_statuses_include_completed_and_operator(self):
        from services.db import user_has_active_buy_order

        captured = {}

        async def fetchval(query, *args):
            captured["query"] = query
            return None

        conn = AsyncMock()
        conn.fetchval = fetchval
        await user_has_active_buy_order(conn, 555)
        q = captured["query"]
        for status in BLOCKING_REQUIRED:
            self.assertIn(status, q, f"{status} должен блокировать новую BUY")

    async def test_exclude_order_id_path_also_blocks_completed(self):
        from services.db import user_has_active_buy_order

        captured = {}

        async def fetchval(query, *args):
            captured["query"] = query
            return None

        conn = AsyncMock()
        conn.fetchval = fetchval
        await user_has_active_buy_order(conn, 555, exclude_order_id="O1")
        self.assertIn("COMPLETED", captured["query"])
        self.assertIn("OPERATOR_PENDING", captured["query"])


class UserHasActiveOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocking_statuses_include_completed(self):
        from services.db import user_has_active_order

        captured = {}

        async def fetchval(query, *args):
            captured["query"] = query
            return None

        conn = AsyncMock()
        conn.fetchval = fetchval
        await user_has_active_order(conn, 555)
        self.assertIn("COMPLETED", captured["query"])
        self.assertIn("OPERATOR_PENDING", captured["query"])


class GetActiveOrderByUserTests(unittest.IsolatedAsyncioTestCase):
    async def test_includes_operator_pending(self):
        from unittest.mock import MagicMock
        from services.db import get_active_order_by_user

        captured = {}

        async def fetchrow(query, *args):
            captured["query"] = query
            return None

        conn = AsyncMock()
        conn.fetchrow = fetchrow

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("services.db.get_pool", AsyncMock(return_value=pool)):
            await get_active_order_by_user(555)

        self.assertIn("OPERATOR_PENDING", captured["query"])
        for status in BLOCKING_REQUIRED:
            self.assertIn(status, captured["query"], f"{status} должен быть в get_active_order_by_user")


if __name__ == "__main__":
    unittest.main()
