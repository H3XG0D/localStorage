from decimal import Decimal
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("dependency override required")


sys.modules.setdefault("db", types.SimpleNamespace(get_pool=_dependency_stub))

import casino_weekly_cashback


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _Connection:
    def __init__(self, *, claim_results=None):
        self.stats_query = ""
        self.executions = []
        self.claim_results = list(claim_results or [202])

    def transaction(self):
        return _Transaction()

    async def fetch(self, query, *args):
        if 'FROM casino_settings' in query:
            # This fixture tests the configured 7% payout, not the default grid.
            return [{'key': 'cashback_volume_tiers', 'value': [{'min_wager_rub': 0, 'percent': 7}]}]
        self.stats_query = query
        return [
            {
                "telegram_id": 202,
                "total_bet": Decimal("10000.00"),
                "total_won": Decimal("0.00"),
                "eligible_loss": Decimal("10000.00"),
            },
        ]

    async def fetchval(self, query, *args):
        self.executions.append((query, args))
        return self.claim_results.pop(0) if self.claim_results else None

    async def execute(self, query, *args):
        self.executions.append((query, args))
        return "INSERT 0 1"


class CasinoWeeklyCashbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_includes_only_canonical_completed_loss_types(self):
        conn = _Connection()

        with patch(
            "casino_weekly_cashback.get_pool",
            new=AsyncMock(return_value=_Pool(conn)),
        ):
            result = await casino_weekly_cashback.accrue_weekly_casino_cashback()

        normalized_query = " ".join(conn.stats_query.split())
        self.assertIn("game_type IN (", normalized_query)
        for game_type in casino_weekly_cashback.CASHBACK_GAME_TYPES:
            self.assertIn(f"'{game_type}'", normalized_query)
        self.assertIn("game_type = 'cub'", normalized_query)
        self.assertIn("wager_totals", normalized_query)
        self.assertIn("loss_totals", normalized_query)
        self.assertIn("win_totals", normalized_query)
        self.assertIn("finished_at >= $1", normalized_query)
        self.assertIn("finished_at < $2", normalized_query)
        self.assertIn("'baccara'", normalized_query)
        self.assertIn("'blackjack'", normalized_query)
        self.assertIn("creator_id AS telegram_id", normalized_query)
        self.assertIn("opponent_id AS telegram_id", normalized_query)
        self.assertIn("SUM(wager_rub)::numeric AS total_bet", normalized_query)
        self.assertIn("SUM(won_rub)::numeric AS total_won", normalized_query)
        self.assertIn("SUM(loss_rub)::numeric AS eligible_loss", normalized_query)
        self.assertIn("counterparty_kind = 'player'", normalized_query)
        self.assertIn("counterparty_kind = 'pvp_robot'", normalized_query)
        self.assertIn("counterparty_kind = 'house_robot'", normalized_query)
        self.assertIn("outcome->>'kind' = 'house_win'", normalized_query)
        self.assertIn("outcome->>'kind' = 'winner'", normalized_query)
        self.assertIn("outcome->>'kind' = 'loss'", normalized_query)
        self.assertIn("outcome->>'kind' = 'win'", normalized_query)
        self.assertIn("UNION ALL", normalized_query)
        self.assertNotIn("game_type <> 'raffle'", normalized_query)
        self.assertNotIn("'raffle'", normalized_query)

        ledger_rows = [
            args
            for query, args in conn.executions
            if "INSERT INTO user_cashback_ledger" in query
        ]
        self.assertTrue(any(
            "ON CONFLICT (order_id) DO NOTHING" in query
            for query, _ in conn.executions
        ))
        self.assertEqual(
            ledger_rows,
            [(202, Decimal("700.00"), unittest.mock.ANY, unittest.mock.ANY)],
        )

        claim_rows = [
            args
            for query, args in conn.executions
            if "INSERT INTO casino_player_cashback" in query
        ]
        self.assertEqual(claim_rows, [
            (
                202,
                unittest.mock.ANY,
                Decimal("10000.00"),
                Decimal("0.00"),
                Decimal("10000.00"),
                Decimal("10000.00"),
                Decimal("700.00"),
                Decimal("7"),
            ),
        ])
        self.assertEqual(
            result,
            {"processed": 1, "accrued": 1, "total_cashback_rub": 700.0},
        )

    async def test_duplicate_claim_does_not_create_second_ledger_credit(self):
        conn = _Connection(claim_results=[None])

        with patch(
            "casino_weekly_cashback.get_pool",
            new=AsyncMock(return_value=_Pool(conn)),
        ):
            result = await casino_weekly_cashback.accrue_weekly_casino_cashback()

        self.assertEqual(result, {"processed": 0, "accrued": 0, "total_cashback_rub": 0.0})
        self.assertFalse(
            any("INSERT INTO user_cashback_ledger" in query for query, _ in conn.executions)
        )


if __name__ == "__main__":
    unittest.main()
