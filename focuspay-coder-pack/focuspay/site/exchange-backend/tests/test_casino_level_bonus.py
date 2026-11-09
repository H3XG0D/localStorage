from decimal import Decimal
import unittest

from casino_level_bonus import (
    bonus_for_threshold,
    grant_reached_level_bonuses,
    maybe_grant_reached_level_bonuses,
    parse_level_reach_bonuses,
)
from casino_settings_registry import canonical_defaults, validate_value
from casino_weekly_wager import current_week_start


class LevelReachBonusParseTests(unittest.TestCase):
    def test_zero_bonus_is_omitted_and_order_is_sorted(self):
        rows = parse_level_reach_bonuses(
            [
                {"min_wager_rub": 100000, "bonus_rub": 200},
                {"min_wager_rub": 25000, "bonus_rub": 0},
                {"min_wager_rub": 50000, "bonus_rub": 500},
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].min_wager_rub, Decimal("50000.00"))
        self.assertEqual(rows[0].bonus_rub, Decimal("500.00"))
        self.assertEqual(bonus_for_threshold(rows, Decimal("50000")), Decimal("500.00"))
        self.assertEqual(bonus_for_threshold(rows, Decimal("0")), Decimal("0.00"))

    def test_duplicate_threshold_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_level_reach_bonuses(
                [
                    {"min_wager_rub": 50000, "bonus_rub": 100},
                    {"min_wager_rub": 50000, "bonus_rub": 200},
                ]
            )

    def test_registry_accepts_empty_list(self):
        self.assertEqual(validate_value("level_reach_bonuses", []), [])

    def test_registry_default_is_example_grid(self):
        self.assertEqual(
            canonical_defaults()["level_reach_bonuses"],
            [
                {"min_wager_rub": 50000.0, "bonus_rub": 500.0},
                {"min_wager_rub": 100000.0, "bonus_rub": 1000.0},
                {"min_wager_rub": 200000.0, "bonus_rub": 2500.0},
                {"min_wager_rub": 500000.0, "bonus_rub": 5000.0},
            ],
        )


class LevelReachBonusGrantTests(unittest.IsolatedAsyncioTestCase):
    async def test_grant_is_once_per_player_week_threshold(self):
        seen: set[tuple] = set()
        ledger: list[tuple] = []

        class _Conn:
            async def fetchrow(self, query, *args):
                if "FROM casino_settings" in query:
                    return {"value": [{"min_wager_rub": 50000, "bonus_rub": 500}]}
                if "SUM(wager_rub)" in query or "wagers" in query:
                    return {"wager_rub": Decimal("60000")}
                if "INSERT INTO casino_level_bonus_grants" in query:
                    key = (args[0], args[1], args[2])
                    if key in seen:
                        return None
                    seen.add(key)
                    return {"telegram_id": args[0]}
                raise AssertionError(query)

            async def execute(self, query, *args):
                if "user_cashback_ledger" in query:
                    ledger.append(args)
                return "INSERT 1"

        conn = _Conn()
        first = await grant_reached_level_bonuses(conn, 42)
        second = await grant_reached_level_bonuses(conn, 42)
        self.assertEqual(first, [{"min_wager_rub": "50000.00", "bonus_rub": "500.00"}])
        self.assertEqual(second, [])
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0][0], 42)
        self.assertEqual(ledger[0][1], Decimal("500.00"))
        self.assertIn(f":{current_week_start().isoformat()}:", str(ledger[0][2]))
        self.assertEqual(ledger[0][2], f"clb:42:{current_week_start().isoformat()}:50000.00")

    async def test_maybe_grant_skips_mocked_connections(self):
        class _NotAsyncpg:
            pass

        await maybe_grant_reached_level_bonuses(_NotAsyncpg(), 1)
