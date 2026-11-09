"""Изоляция областей кошелька: рубли, бонусные фишки и каждый турнир отдельно."""
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from casino_wallet import (  # noqa: E402
    BONUS_SCOPE,
    RUB_SCOPE,
    assert_player_may_sit,
    assert_real_money_only,
    parse_scope,
    scope_from_row,
    scope_insert_sql,
    scope_or_mine_filter,
    scope_sql_filter,
    tournament_scope,
)


class ScopeConn:
    """Минимальный conn: отвечает на пробу колонок и на активный кошелёк игрока."""

    def __init__(self, *, migrated=True, player_kind="rub", player_tournament=None):
        self.migrated = migrated
        self.player_kind = player_kind
        self.player_tournament = player_tournament

    async def fetchval(self, query, *args):
        if "information_schema.columns" in query:
            return 1 if self.migrated else None
        if "to_regclass" in query:
            return 1 if self.migrated else None
        if "wallet:active" in query:
            return self.player_kind
        if "casino_settings" in query:
            return '{"enabled": true}'
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        if "trn:wallet" in query:
            return {"tid": self.player_tournament}
        if "casino_settings" in query:
            return {"value": '{"enabled": true}'}
        raise AssertionError(query)

    async def fetchval_settings(self):  # pragma: no cover - documentation helper
        return None


class ScopeKeyTests(unittest.TestCase):
    def test_keys_and_units_are_stable(self):
        self.assertEqual(RUB_SCOPE.key(), "rub")
        self.assertEqual(BONUS_SCOPE.key(), "bonus")
        self.assertEqual(tournament_scope(7).key(), "trn:7")
        self.assertEqual(RUB_SCOPE.unit(), "rub")
        self.assertEqual(BONUS_SCOPE.unit(), "chips")
        self.assertTrue(BONUS_SCOPE.is_chips)
        self.assertFalse(BONUS_SCOPE.is_rub)

    def test_two_tournaments_are_different_scopes(self):
        self.assertNotEqual(tournament_scope(1), tournament_scope(2))

    def test_row_without_columns_is_real_money(self):
        self.assertEqual(scope_from_row({"stake_rub": 100}), RUB_SCOPE)
        self.assertEqual(scope_from_row(None), RUB_SCOPE)
        self.assertEqual(scope_from_row({"wallet_kind": "bonus"}), BONUS_SCOPE)
        self.assertEqual(
            scope_from_row({"wallet_kind": "tournament", "tournament_id": 3}),
            tournament_scope(3),
        )

    def test_tournament_row_without_id_degrades_to_rub(self):
        self.assertEqual(scope_from_row({"wallet_kind": "tournament", "tournament_id": None}), RUB_SCOPE)

    def test_parse_scope_rejects_nonsense_and_maps_demo(self):
        self.assertEqual(parse_scope("demo"), BONUS_SCOPE)
        self.assertEqual(parse_scope(None), RUB_SCOPE)
        self.assertEqual(parse_scope("tournament", 5), tournament_scope(5))
        with self.assertRaises(HTTPException):
            parse_scope("chips_of_mine")
        with self.assertRaises(HTTPException):
            parse_scope("tournament", None)

    def test_filter_pins_one_scope(self):
        self.assertIn("= 'bonus'", scope_sql_filter(BONUS_SCOPE))
        self.assertIn("tournament_id IS NULL", scope_sql_filter(RUB_SCOPE))
        trn = scope_sql_filter(tournament_scope(9), "t")
        self.assertIn("t.wallet_kind, 'rub') = 'tournament'", trn)
        self.assertIn("t.tournament_id = 9", trn)


class ScopeGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_chips_player_cannot_sit_at_a_money_table(self):
        conn = ScopeConn(player_kind="bonus")
        with self.assertRaises(HTTPException) as ctx:
            await assert_player_may_sit(conn, {"wallet_kind": "rub"}, 11)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("реальных", str(ctx.exception.detail))

    async def test_money_player_cannot_sit_at_a_chip_table(self):
        conn = ScopeConn(player_kind="rub")
        with self.assertRaises(HTTPException) as ctx:
            await assert_player_may_sit(conn, {"wallet_kind": "bonus"}, 11)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_other_tournament_is_also_refused(self):
        conn = ScopeConn(player_kind="tournament", player_tournament=1)
        with self.assertRaises(HTTPException):
            await assert_player_may_sit(
                conn, {"wallet_kind": "tournament", "tournament_id": 2}, 11
            )
        scope = await assert_player_may_sit(
            conn, {"wallet_kind": "tournament", "tournament_id": 1}, 11
        )
        self.assertEqual(scope, tournament_scope(1))

    async def test_same_scope_passes(self):
        conn = ScopeConn(player_kind="bonus")
        self.assertEqual(
            await assert_player_may_sit(conn, {"wallet_kind": "bonus"}, 11), BONUS_SCOPE
        )

    async def test_house_games_are_real_money_only(self):
        await assert_real_money_only(ScopeConn(player_kind="rub"), 11)
        with self.assertRaises(HTTPException) as ctx:
            await assert_real_money_only(ScopeConn(player_kind="bonus"), 11)
        self.assertEqual(ctx.exception.status_code, 409)


class ScopeInsertTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_parts_carry_the_scope(self):
        cols, params, values = await scope_insert_sql(
            ScopeConn(), "casino_v2_tables", tournament_scope(4), next_index=9
        )
        self.assertEqual(cols, ", wallet_kind, tournament_id")
        self.assertEqual(params, ", $9::varchar, $10::bigint")
        self.assertEqual(values, ["tournament", 4])

    async def test_before_migration_money_tables_still_work(self):
        cols, params, values = await scope_insert_sql(
            ScopeConn(migrated=False), "casino_v2_tables", RUB_SCOPE, next_index=9
        )
        self.assertEqual((cols, params, values), ("", "", []))

    async def test_before_migration_chip_tables_are_refused(self):
        with self.assertRaises(HTTPException) as ctx:
            await scope_insert_sql(
                ScopeConn(migrated=False), "casino_v2_tables", BONUS_SCOPE, next_index=9
            )
        self.assertEqual(ctx.exception.status_code, 409)


class ScopeOrMineTests(unittest.IsolatedAsyncioTestCase):
    async def test_own_seat_survives_a_wallet_switch(self):
        where = await scope_or_mine_filter(
            ScopeConn(), "casino_v2_tables", BONUS_SCOPE, mine_sql="seat.user_id = $3"
        )
        self.assertTrue(where.startswith(" AND (("))
        self.assertIn("= 'bonus'", where)
        self.assertIn("OR seat.user_id = $3", where)

    async def test_before_migration_there_is_nothing_to_filter(self):
        where = await scope_or_mine_filter(
            ScopeConn(migrated=False), "casino_v2_tables", RUB_SCOPE, mine_sql="x = $3"
        )
        self.assertEqual(where, "")


class ChipScaleTests(unittest.TestCase):
    def test_chips_share_the_rub_scale(self):
        """1 фишка = 1.00, иначе движки пришлось бы учить второму типу суммы."""
        from casino_finance import money

        self.assertEqual(money(Decimal("1")), Decimal("1.00"))


if __name__ == "__main__":
    unittest.main()
