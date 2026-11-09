from decimal import Decimal
import unittest

from casino_risk import (
    actual_rtp,
    build_risk_payload,
    corridor_half_width_pp,
    exposure_pct,
    house_theoretical_rtp,
    max_single_payout,
    pvp_theoretical_rtp,
    verify_sql,
)


class CasinoRiskMathTests(unittest.TestCase):
    def test_pvp_commission_15_is_92_50_rtp(self):
        self.assertEqual(pvp_theoretical_rtp("15"), Decimal("92.50"))

    def test_house_fair_coin_times_two_is_100(self):
        self.assertEqual(house_theoretical_rtp("0.5", "2"), Decimal("100.00"))

    def test_actual_rtp_850_of_1000(self):
        self.assertEqual(actual_rtp("1000", "850"), Decimal("85.00"))

    def test_corridor_100_rounds_is_10pp(self):
        self.assertEqual(corridor_half_width_pp(100), Decimal("10.00"))

    def test_exposure_and_max_payout(self):
        self.assertEqual(exposure_pct("500", "10000"), Decimal("5.00"))
        self.assertEqual(max_single_payout("10000", "5"), Decimal("500.00"))

    def test_verify_sql_is_sum_bet_rub_without_status(self):
        sql = verify_sql("7d")
        self.assertIn("SUM(bet_rub)", sql)
        self.assertIn("7 days", sql)
        self.assertNotIn("status", sql)

    def test_payload_wires_verify_number_and_anomaly_threshold(self):
        payload = build_risk_payload(
            window="7d",
            deviation_pp=Decimal("15"),
            settings={
                "commission_rate_wagering_complete": {"percent": 15.0},
                "bankroll_floor_rub": {"amount": 1000.0},
                "max_profit_pct_per_round": {"percent": 5.0},
            },
            house={"balance_rub": Decimal("10000"), "reserved_rub": Decimal("500")},
            open_pvp_banks_rub=Decimal("200"),
            house_liability_rub=Decimal("300"),
            verify_bet_rub=Decimal("1234.56"),
            game_rows=[
                {
                    "game_type": "pvp_dice",
                    "rounds": 100,
                    "wager_rub": Decimal("10000"),
                    "returned_rub": Decimal("8500"),
                }
            ],
            policy_rows=[{"game_type": "cub", "win_probability": Decimal("0.5"), "payout_multiplier": Decimal("2")}],
            player_rows=[
                {
                    "telegram_id": 77,
                    "username": "hot",
                    "game_type": "pvp_dice",
                    "rounds": 20,
                    "wager_rub": Decimal("1000"),
                    "returned_rub": Decimal("1500"),
                },
                {
                    "telegram_id": 88,
                    "username": "cold",
                    "game_type": "pvp_dice",
                    "rounds": 20,
                    "wager_rub": Decimal("1000"),
                    "returned_rub": Decimal("700"),
                },
            ],
        )
        self.assertEqual(payload["verify"]["value_rub"], 1234.56)
        self.assertEqual(payload["bankroll"]["available_rub"], 9500.0)
        self.assertEqual(payload["bankroll"]["target_rub"], 2000.0)
        self.assertEqual(payload["bankroll"]["max_payout_rub"], 475.0)
        self.assertEqual(payload["exposure"]["total_rub"], 500.0)
        dice = next(item for item in payload["games"] if item["game_type"] == "pvp_dice")
        self.assertEqual(dice["theoretical_rtp_pct"], 92.5)
        self.assertEqual(dice["actual_rtp_pct"], 85.0)
        self.assertEqual(dice["rounds"], 100)
        cub = next(item for item in payload["games"] if item["game_type"] == "cub")
        self.assertEqual(cub["theoretical_rtp_pct"], 100.0)
        hot = next(item for item in payload["anomalies"] if item["telegram_id"] == 77)
        self.assertEqual(hot["player_rtp_pct"], 150.0)
        self.assertEqual(hot["game_rtp_pct"], 92.5)
        self.assertEqual(hot["risk"], "high")
        self.assertEqual(payload["winners"][0]["telegram_id"], 77)
        self.assertEqual(payload["losers"][0]["telegram_id"], 88)


class _RiskConn:
    def __init__(self):
        self.queries: list[str] = []

    async def fetch(self, query, *args):
        self.queries.append(query)
        if "FROM casino_settings" in query:
            return [
                {"key": "commission_rate_wagering_complete", "value": {"percent": 15.0}},
                {"key": "bankroll_floor_rub", "value": {"amount": 0.0}},
                {"key": "max_profit_pct_per_round", "value": {"percent": 5.0}},
            ]
        if "casino_house_policies" in query:
            return []
        if "bot_users" in query:
            return [
                {
                    "telegram_id": 11,
                    "username": "alice",
                    "game_type": "pvp_dice",
                    "rounds": 4,
                    "wager_rub": Decimal("400"),
                    "returned_rub": Decimal("370"),
                }
            ]
        if "GROUP BY game_type" in query:
            return [
                {
                    "game_type": "pvp_dice",
                    "rounds": 4,
                    "wager_rub": Decimal("400"),
                    "returned_rub": Decimal("370"),
                }
            ]
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        if "casino_house_accounts" in query:
            return {"balance_rub": Decimal("5170"), "reserved_rub": Decimal("700")}
        if "SUM(bet_rub)" in query:
            return {"bet_rub": Decimal("99.00")}
        if "casino_house_reservations" in query:
            return {"amount_rub": Decimal("40")}
        if "status IN ('waiting', 'active')" in query:
            return {"amount_rub": Decimal("80")}
        raise AssertionError(query)


class FetchRiskSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_uses_sum_bet_rub_as_verify_kpi(self):
        from casino_risk import fetch_risk_snapshot

        conn = _RiskConn()
        payload = await fetch_risk_snapshot(conn, window="7d", deviation_pp=15)
        self.assertEqual(payload["verify"]["value_rub"], 99.0)
        self.assertIn("SUM(bet_rub)", payload["verify"]["sql"])
        self.assertTrue(any("SUM(bet_rub)" in query and "status" not in query for query in conn.queries))
        self.assertEqual(payload["bankroll"]["available_rub"], 4470.0)
        self.assertEqual(payload["exposure"]["open_pvp_banks_rub"], 80.0)
        self.assertEqual(payload["exposure"]["house_liability_rub"], 40.0)
        self.assertTrue(any("game_type = ANY" in query for query in conn.queries))
