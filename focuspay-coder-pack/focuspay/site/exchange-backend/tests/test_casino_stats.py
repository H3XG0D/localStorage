"""Casino stats: GGR = handle − player payouts; breakdown sums; dashboard uses handle."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

async def _dependency_stub(*args, **kwargs):
    raise AssertionError("dependency override required")


_auth_module = sys.modules.get("auth")
_db_module = sys.modules.get("db")
if _auth_module is None:
    sys.modules["auth"] = types.SimpleNamespace(
        get_current_admin=_dependency_stub,
        get_current_finance_owner=_dependency_stub,
        get_current_user=_dependency_stub,
    )
if _db_module is None:
    sys.modules["db"] = types.SimpleNamespace(get_pool=_dependency_stub)

from casino_stats import (  # noqa: E402
    SHARE_TABLE_LIMIT,
    _CREATOR_DIST_SQL,
    _REFERRAL_DIST_SQL,
    _ROUNDS_SQL,
    assemble_casino_stats,
    chart_from_stats,
    clip_share_table,
    dashboard_from_stats,
    empty_casino_stats,
    fetch_casino_stats,
)
from routers import admin_casino  # noqa: E402

# These import-only dependency stubs must not poison later route imports.
if _auth_module is None:
    del sys.modules["auth"]
if _db_module is None:
    del sys.modules["db"]


def _round(
    *,
    day="2026-09-01",
    surface="v2",
    game_type="pvp_dice",
    round_key="t1",
    player_count=2,
    bot_count=0,
    handle_rub=50,
    house_stake_rub=0,
    player_payout_rub=47.5,
    rake_rub=2.5,
):
    return {
        "day": date.fromisoformat(day) if isinstance(day, str) else day,
        "surface": surface,
        "game_type": game_type,
        "round_key": round_key,
        "player_count": player_count,
        "bot_count": bot_count,
        "handle_rub": Decimal(str(handle_rub)),
        "house_stake_rub": Decimal(str(house_stake_rub)),
        "player_payout_rub": Decimal(str(player_payout_rub)),
        "rake_rub": Decimal(str(rake_rub)),
    }


class AssembleCasinoStatsTests(unittest.TestCase):
    def test_empty_period_is_zero(self):
        got = assemble_casino_stats(round_rows=[], player_rows=[], d_from=date(2026, 8, 1), d_to=date(2026, 8, 1))
        self.assertEqual(got["volume"]["rounds"], 0)
        self.assertEqual(got["volume"]["handle_rub"], 0.0)
        self.assertEqual(got["volume"]["ggr_rub"], 0.0)
        self.assertEqual(got["ngr_rub"], 0.0)
        self.assertEqual(got["distributions"]["referrals"]["rows"], [])
        self.assertEqual(got["distributions"]["creators"]["total_rub"], 0.0)
        self.assertEqual(got["distributions"]["cashback"]["hidden_count"], 0)
        self.assertEqual(got["distributions"]["bonuses"]["shown_rub"], 0.0)
        self.assertEqual(got["daily"][0]["date"], "2026-08-01")
        self.assertEqual(got["daily"][0]["ggr_rub"], 0.0)

    def test_handle_minus_payouts_is_ggr(self):
        rows = [
            _round(round_key="human", handle_rub=50, player_payout_rub=47.5, rake_rub=2.5, bot_count=0),
            _round(
                round_key="bot-loss",
                handle_rub=50,
                player_payout_rub=95,
                house_stake_rub=50,
                rake_rub=5,
                player_count=1,
                bot_count=1,
            ),
            _round(
                surface="jackpot",
                game_type="jackpot",
                round_key="jp",
                handle_rub=65,
                player_payout_rub=61.75,
                rake_rub=3.25,
                player_count=3,
                bot_count=0,
            ),
        ]
        got = assemble_casino_stats(round_rows=rows, player_rows=[])
        self.assertEqual(got["volume"]["handle_rub"], 165.0)
        self.assertEqual(got["volume"]["player_payout_rub"], 204.25)
        self.assertEqual(got["volume"]["ggr_rub"], -39.25)
        self.assertEqual(
            got["volume"]["ggr_rub"],
            round(got["volume"]["handle_rub"] - got["volume"]["player_payout_rub"], 2),
        )

    def test_breakdown_sums_to_ggr_and_bot_rake_is_inside_house(self):
        rows = [
            _round(round_key="h1", handle_rub=100, player_payout_rub=95, rake_rub=5, bot_count=0),
            _round(round_key="h2", game_type="baccara", handle_rub=50, player_payout_rub=47.5, rake_rub=2.5, bot_count=0),
            _round(
                round_key="bot",
                handle_rub=50,
                player_payout_rub=95,
                house_stake_rub=50,
                rake_rub=5,
                player_count=1,
                bot_count=1,
            ),
            _round(
                surface="jackpot",
                game_type="jackpot",
                round_key="jp",
                handle_rub=90,
                player_payout_rub=85.5,
                rake_rub=4.5,
                player_count=2,
            ),
            _round(
                surface="rooms",
                game_type="fixed_room",
                round_key="rm",
                handle_rub=80,
                player_payout_rub=76,
                rake_rub=4,
                player_count=4,
            ),
        ]
        got = assemble_casino_stats(round_rows=rows, player_rows=[])
        br = got["ggr_breakdown"]
        summed = round(br["pvp_rake_rub"] + br["jackpot_rake_rub"] + br["rooms_rake_rub"] + br["house_vs_bots_rub"], 2)
        self.assertEqual(summed, got["volume"]["ggr_rub"])
        self.assertEqual(br["pvp_rake_rub"], 7.5)
        self.assertEqual(br["jackpot_rake_rub"], 4.5)
        self.assertEqual(br["rooms_rake_rub"], 4.0)
        self.assertEqual(br["house_vs_bots_rub"], -45.0)
        self.assertEqual(got["volume"]["rounds"], 5)
        self.assertEqual(sum(row["rounds"] for row in got["by_type"]), 5)

    def test_prod_day_four_rubles(self):
        """Live 2026-09-01: 1030 handle, 1026 payouts, 4 GGR. Bot table ate the rake."""
        human = [
            _round(round_key=f"h{i}", handle_rub=handle, player_payout_rub=payout, rake_rub=rake, game_type=gtype)
            for i, (gtype, handle, payout, rake) in enumerate(
                [
                    ("baccara", 50, 47.5, 2.5),
                    ("baccara", 50, 47.5, 2.5),
                    ("baccara", 100, 95, 5),
                    ("blackjack", 100, 95, 5),
                    ("blackjack", 100, 95, 5),
                    ("pvp_dice", 200, 190, 10),
                    ("pvp_dice", 20, 19, 1),
                    ("pvp_dice", 50, 47.5, 2.5),
                    ("pvp_dice", 20, 19, 1),
                ]
            )
        ]
        bot = _round(
            round_key="bot11",
            handle_rub=50,
            player_payout_rub=95,
            house_stake_rub=50,
            rake_rub=5,
            player_count=1,
            bot_count=1,
        )
        jackpots = [
            _round(surface="jackpot", game_type="jackpot", round_key="jp1", handle_rub=65, player_payout_rub=61.75, rake_rub=3.25),
            _round(surface="jackpot", game_type="jackpot", round_key="jp2", handle_rub=90, player_payout_rub=85.5, rake_rub=4.5),
            _round(surface="jackpot", game_type="jackpot", round_key="jp3", handle_rub=135, player_payout_rub=128.25, rake_rub=6.75),
        ]
        got = assemble_casino_stats(
            round_rows=human + [bot] + jackpots,
            player_rows=[],
            owner={"commission_profit_rub": 0.0, "house_game_profit_rub": 4.0, "owner_profit_rub": 4.0},
        )
        self.assertEqual(got["volume"]["handle_rub"], 1030.0)
        self.assertEqual(got["volume"]["player_payout_rub"], 1026.0)
        self.assertEqual(got["volume"]["ggr_rub"], 4.0)
        self.assertEqual(got["volume"]["rounds"], 13)
        self.assertEqual(got["ggr_breakdown"]["house_vs_bots_rub"], -45.0)
        self.assertEqual(got["reconciliation"]["diff_rub"], 0.0)
        self.assertEqual(sum(row["rounds"] for row in got["by_type"]), 13)
        self.assertNotIn("fixed_room", {row["game_type"] for row in got["by_type"]})

    def test_ngr_subtracts_costs(self):
        rows = [_round(handle_rub=100, player_payout_rub=95, rake_rub=5)]
        got = assemble_casino_stats(
            round_rows=rows,
            player_rows=[],
            costs_row={"cashback_rub": 1, "bonus_rub": 0.5, "creator_share_rub": 0.25, "referral_share_rub": 0.25},
        )
        self.assertEqual(got["volume"]["ggr_rub"], 5.0)
        self.assertEqual(got["costs"]["total_rub"], 2.0)
        self.assertEqual(got["ngr_rub"], 3.0)

    def test_distribution_sums_match_costs(self):
        got = assemble_casino_stats(
            round_rows=[_round(handle_rub=100, player_payout_rub=95, rake_rub=5)],
            player_rows=[],
            costs_row={"cashback_rub": 3, "bonus_rub": 2, "creator_share_rub": 1.5, "referral_share_rub": 4},
            referral_rows=[
                {
                    "level": "l1",
                    "recipient_id": 10,
                    "recipient_username": "ref1",
                    "source_player_id": 20,
                    "source_username": "player",
                    "games": 2,
                    "amount_rub": 3,
                },
                {
                    "level": "l2",
                    "recipient_id": 11,
                    "recipient_username": "ref2",
                    "source_player_id": 20,
                    "source_first_name": "Pete",
                    "games": 1,
                    "amount_rub": 1,
                },
            ],
            creator_rows=[
                {
                    "creator_account_id": 1,
                    "recipient_id": 99,
                    "recipient_username": "creator",
                    "source_player_id": 20,
                    "source_username": "player",
                    "games": 3,
                    "amount_rub": 1.5,
                }
            ],
            cashback_rows=[{"recipient_id": 20, "recipient_username": "player", "games": 1, "amount_rub": 3}],
            bonus_rows=[{"recipient_id": 20, "recipient_first_name": "Player", "games": 1, "amount_rub": 2}],
        )
        dist = got["distributions"]
        self.assertEqual(dist["referrals"]["total_rub"], got["costs"]["referral_share_rub"])
        self.assertEqual(dist["creators"]["total_rub"], got["costs"]["creator_share_rub"])
        self.assertEqual(dist["cashback"]["total_rub"], got["costs"]["cashback_rub"])
        self.assertEqual(dist["bonuses"]["total_rub"], got["costs"]["bonus_rub"])
        self.assertEqual(
            round(dist["referrals"]["shown_rub"] + dist["referrals"]["hidden_rub"], 2),
            got["costs"]["referral_share_rub"],
        )
        self.assertEqual(dist["referrals"]["rows"][0]["level"], "l1")
        self.assertEqual(dist["referrals"]["rows"][0]["source_player_id"], 20)
        self.assertEqual(dist["referrals"]["rows"][1]["level"], "l2")
        self.assertEqual(dist["referrals"]["rows"][1]["source_username"], "Pete")
        self.assertEqual(dist["creators"]["rows"][0]["recipient_username"], "creator")
        self.assertEqual(dist["cashback"]["rows"][0]["recipient_id"], 20)
        self.assertEqual(dist["bonuses"]["rows"][0]["recipient_username"], "Player")

    def test_share_table_clips_at_limit_and_keeps_identity(self):
        rows = [{"recipient_id": i, "amount_rub": 1, "games": 1} for i in range(SHARE_TABLE_LIMIT + 5)]
        got = clip_share_table(rows, total_rub=float(SHARE_TABLE_LIMIT + 5))
        self.assertEqual(len(got["rows"]), SHARE_TABLE_LIMIT)
        self.assertEqual(got["hidden_count"], 5)
        self.assertEqual(got["shown_rub"] + got["hidden_rub"], got["total_rub"])
        self.assertEqual(got["total_rub"], float(SHARE_TABLE_LIMIT + 5))

    def test_sql_joins_commission_to_source_player(self):
        self.assertIn("referrer_l1", _REFERRAL_DIST_SQL)
        self.assertIn("WHEN g.winner_id = g.creator_id THEN g.opponent_id", _REFERRAL_DIST_SQL)
        self.assertIn("creator_account_id", _CREATOR_DIST_SQL)
        self.assertIn("web_users", _CREATOR_DIST_SQL)

    def test_refunded_jackpot_is_not_a_round(self):
        got = assemble_casino_stats(round_rows=[], player_rows=[])
        self.assertEqual(got["volume"]["rounds"], 0)
        self.assertIn("status = 'settled'", _ROUNDS_SQL)
        self.assertNotIn("refunded", _ROUNDS_SQL.split("casino_jackpot_rounds")[1].split("UNION ALL")[0])

    def test_sql_counts_player_handle_not_bot_pot(self):
        self.assertIn("t.stake_rub * players.n AS handle_rub", _ROUNDS_SQL)
        self.assertIn("participant_kind = 'bot'", _ROUNDS_SQL)
        self.assertIn("FROM casino_v2_settlements", _ROUNDS_SQL)
        self.assertNotIn("FROM casino_v2_tables t WHERE t.status", _ROUNDS_SQL)

    def test_new_players_use_first_seen(self):
        got = assemble_casino_stats(
            round_rows=[],
            player_rows=[{"player_id": 1, "handle_rub": 10, "payout_rub": 0, "rounds": 1, "username": "a"}],
            first_seen_rows=[{"player_id": 1, "first_day": date(2026, 9, 1)}, {"player_id": 2, "first_day": date(2026, 8, 1)}],
            period_player_ids=[1, 2],
            d_from=date(2026, 9, 1),
            d_to=date(2026, 9, 1),
        )
        self.assertEqual(got["players"]["active"], 2)
        self.assertEqual(got["players"]["new"], 1)

    def test_dashboard_maps_handle_not_pot(self):
        lifetime = assemble_casino_stats(
            round_rows=[
                _round(handle_rub=50, player_payout_rub=47.5, rake_rub=2.5),
                _round(round_key="bot", handle_rub=50, player_payout_rub=95, house_stake_rub=50, rake_rub=5, player_count=1, bot_count=1),
            ],
            player_rows=[{"player_id": 7, "username": "Ada", "rounds": 2, "handle_rub": 100, "payout_rub": 142.5}],
            owner={"commission_profit_rub": 0, "house_game_profit_rub": -42.5, "owner_profit_rub": -42.5},
        )
        today = empty_casino_stats()
        dash = dashboard_from_stats(lifetime, today)
        self.assertEqual(dash["total_turnover_rub"], 100.0)
        self.assertEqual(dash["total_games"], 2)
        self.assertEqual(dash["games_by_type"], {"pvp_dice": 2})
        self.assertEqual(dash["top_players"][0]["total_bet"], 100.0)
        self.assertEqual(dash["owner_profit_rub"], -42.5)

    def test_chart_points_use_daily_handle_and_ggr(self):
        stats = assemble_casino_stats(
            round_rows=[_round(day="2026-09-01", handle_rub=50, player_payout_rub=47.5, rake_rub=2.5)],
            player_rows=[],
            owner_daily={"2026-09-01": 2.5},
            d_from=date(2026, 9, 1),
            d_to=date(2026, 9, 1),
        )
        chart = chart_from_stats(stats)
        self.assertEqual(chart[0]["turnover_rub"], 50.0)
        self.assertEqual(chart[0]["ggr_rub"], 2.5)
        self.assertEqual(chart[0]["owner_profit_rub"], 2.5)


class FetchCasinoStatsSqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_passes_dates_and_calls_owner_helper(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("casino_stats.fetch_casino_owner_profit", new=AsyncMock(return_value={"commission_profit_rub": 0, "house_game_profit_rub": 0, "owner_profit_rub": 0})) as profit, patch(
            "casino_stats.fetch_casino_owner_profit_daily", new=AsyncMock(return_value={})
        ), patch("casino_stats.clans_list_top", new=AsyncMock(return_value={"clans": []})):
            got = await fetch_casino_stats(conn, date(2026, 9, 1), date(2026, 9, 1))
        self.assertEqual(got["volume"]["ggr_rub"], 0.0)
        profit.assert_awaited()
        sqls = [call.args[0] for call in conn.fetch.await_args_list]
        self.assertTrue(any("casino_v2_settlements" in sql for sql in sqls))
        self.assertTrue(any("status = 'settled'" in sql for sql in sqls))


class DashboardEndpointUsesStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_endpoint_uses_fetch_casino_stats(self):
        lifetime = assemble_casino_stats(
            round_rows=[_round(handle_rub=1030, player_payout_rub=1026, rake_rub=54, player_count=20)],
            player_rows=[{"player_id": 42, "username": "Player Name", "rounds": 2, "handle_rub": 200, "payout_rub": 190}],
            owner={"commission_profit_rub": 0, "house_game_profit_rub": 4, "owner_profit_rub": 4},
        )
        today = assemble_casino_stats(round_rows=[_round(handle_rub=50, player_payout_rub=47.5, rake_rub=2.5)], player_rows=[])

        async def fake_stats(conn, d_from=None, d_to=None):
            if d_from is None:
                return lifetime
            return today

        class _Conn:
            pass

        class _Pool:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return _Conn()

                    async def __aexit__(self, *args):
                        return False

                return _Ctx()

        async def get_pool():
            return _Pool()

        with patch("routers.admin_casino.get_pool", new=get_pool), patch(
            "routers.admin_casino.fetch_casino_stats", side_effect=fake_stats
        ), patch("routers.admin_casino.today_moscow", return_value=date(2026, 9, 1)):
            response = await admin_casino.get_casino_dashboard(admin={"id": 7})

        self.assertEqual(response.total_turnover_rub, 1030.0)
        self.assertEqual(response.total_games, 1)
        self.assertEqual(response.owner_profit_rub, 4.0)
        self.assertEqual(response.top_players[0]["username"], "Player Name")
        self.assertEqual(response.turnover_today_rub, 50.0)

    async def test_chart_endpoint_uses_stats_daily(self):
        stats = assemble_casino_stats(
            round_rows=[_round(day="2026-09-01", handle_rub=50, player_payout_rub=47.5, rake_rub=2.5)],
            player_rows=[],
            owner_daily={"2026-09-01": 2.5},
            d_from=date(2026, 8, 3),
            d_to=date(2026, 9, 1),
        )

        class _Pool:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *args):
                        return False

                return _Ctx()

        async def get_pool():
            return _Pool()

        with patch("routers.admin_casino.get_pool", new=get_pool), patch(
            "routers.admin_casino.fetch_casino_stats", new=AsyncMock(return_value=stats)
        ), patch("routers.admin_casino.today_moscow", return_value=date(2026, 9, 1)):
            response = await admin_casino.get_casino_chart_data(admin={"id": 7}, days=30)

        self.assertEqual(response[-1]["turnover_rub"], 50.0)
        self.assertEqual(len(response), 30)


if __name__ == "__main__":
    unittest.main()
