"""Персональный доступ в турнир: белый список обходит гейт по истории обменов."""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from casino_tournaments import _assert_entry_requirements  # noqa: E402


class AccessConn:
    """Минимальный conn: таблица доступов есть, обменов у игрока нет."""

    def __init__(self, *, granted=False, access_table=True):
        self.granted = granted
        self.access_table = access_table

    async def fetchval(self, query, *args):
        if "to_regclass" in query:
            return 1 if self.access_table else None
        if "trn:access-check" in query:
            return 1 if self.granted else None
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        if "FROM orders" in query:
            return {"volume": 0, "deals": 0}
        raise AssertionError(query)


TOURNAMENT = {
    "id": 7,
    "require_exchange_history": True,
    "min_exchange_count": 1,
    "min_exchange_volume_rub": 0,
}


class TournamentAccessTests(unittest.TestCase):
    def test_no_history_and_no_grant_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_assert_entry_requirements(AccessConn(), TOURNAMENT, 101))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_granted_user_passes_without_exchanges(self):
        asyncio.run(_assert_entry_requirements(AccessConn(granted=True), TOURNAMENT, 101))

    def test_missing_access_table_keeps_the_old_gate(self):
        with self.assertRaises(HTTPException):
            asyncio.run(
                _assert_entry_requirements(AccessConn(access_table=False), TOURNAMENT, 101)
            )


if __name__ == "__main__":
    unittest.main()
