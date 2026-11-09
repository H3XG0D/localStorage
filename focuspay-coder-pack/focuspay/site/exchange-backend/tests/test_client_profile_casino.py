"""Operator/admin casino slice of the client profile."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from permissions import PERM_CASINO_PAYOUT, permissions_for_operator_roles, require_permission

ROOT = Path(__file__).resolve().parents[1]


def _profile_mod():
    try:
        import casino_client_profile as mod
    except ModuleNotFoundError as exc:
        if exc.name in {"asyncpg", "fastapi"}:
            raise unittest.SkipTest(f"{exc.name} is not installed") from exc
        raise
    return mod


class ScopeAndSnapshotTests(unittest.TestCase):
    def test_normalize_scope(self):
        mod = _profile_mod()
        self.assertEqual(mod.normalize_scope("OPERATOR"), mod.SCOPE_OPERATOR)
        self.assertEqual(mod.normalize_scope("admin"), mod.SCOPE_ADMIN)
        with self.assertRaises(ValueError):
            mod.normalize_scope("finance")

    def test_operator_drops_risk_and_house_net(self):
        mod = _profile_mod()
        out = mod.apply_scope(
            {
                "available_rub": 10,
                "risk": {"house_net_rub": 42.5, "player_rtp_pct": 110},
                "house_net_rub": 42.5,
            },
            scope=mod.SCOPE_OPERATOR,
        )
        self.assertEqual(out["scope"], "operator")
        self.assertNotIn("risk", out)
        self.assertNotIn("house_net_rub", out)
        self.assertEqual(out["available_rub"], 10)

    def test_admin_keeps_risk(self):
        mod = _profile_mod()
        risk = {"house_net_rub": 12.0, "net_rub": -12.0, "risk": "high"}
        out = mod.apply_scope({"risk": risk}, scope=mod.SCOPE_ADMIN)
        self.assertEqual(out["scope"], "admin")
        self.assertEqual(out["risk"]["house_net_rub"], 12.0)

    def test_payout_snapshot_shape(self):
        mod = _profile_mod()
        snap = mod.payout_player_snapshot(
            {
                "player_id": 9,
                "player": {"display_name": "Игрок", "avatar_url": "https://x"},
                "available_rub": "123.456",
                "wagering": {"locked_rub": "10.00"},
                "payout_rail": {"crypto_allowed": True},
                "raffle": {"campaign_id": 3, "tickets": 7},
                "recent_games": [
                    {
                        "game_type": "roulette",
                        "label": "Рулетка",
                        "result": "win",
                        "result_label": "Выигрыш",
                        "stake_rub": "100.00",
                        "settled_at": "2026-08-31T10:00:00+00:00",
                        "href": "/casino/play/roulette",
                    }
                ],
            }
        )
        self.assertEqual(snap["user_id"], 9)
        self.assertEqual(snap["display_name"], "Игрок")
        self.assertEqual(snap["available_rub"], 123.46)
        self.assertEqual(snap["raffle_tickets"], 7)
        self.assertEqual(snap["raffle_campaign_id"], 3)
        self.assertEqual(len(snap["recent_games"]), 1)
        self.assertNotIn("href", snap["recent_games"][0])
        self.assertNotIn("risk", snap)
        self.assertNotIn("house_net_rub", snap)


class PermissionAndWiringTests(unittest.TestCase):
    def test_client_role_cannot_open_casino_tab(self):
        with self.assertRaises(HTTPException) as ctx:
            require_permission(
                {"id": 1, "permissions": permissions_for_operator_roles(["client"])},
                PERM_CASINO_PAYOUT,
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_finance_default_still_lacks_casino_payout(self):
        self.assertNotIn(PERM_CASINO_PAYOUT, permissions_for_operator_roles(["finance"]))

    def test_operator_router_wires_profile_and_history(self):
        router = (ROOT / "routers" / "operator_casino_payouts.py").read_text()
        self.assertIn('"/users/{user_id}/casino"', router)
        self.assertIn('"/users/{user_id}/casino/history"', router)
        self.assertIn("_require_casino_payout", router)
        self.assertIn("PERM_CASINO_PAYOUT", router)
        self.assertIn("build_casino_client_profile", router)
        self.assertIn("load_casino_client_history", router)
        self.assertIn("payout_player_snapshot", router)
        self.assertIn("raise_if_missing=False", router)

    def test_admin_router_wires_full_profile(self):
        router = (ROOT / "routers" / "admin_casino.py").read_text()
        self.assertIn('"/casino/players/{player_id}/profile"', router)
        self.assertIn('"/casino/players/{player_id}/history"', router)
        self.assertIn("SCOPE_ADMIN", router)
        self.assertIn("get_current_admin", router)

    def test_builder_checks_player_exists(self):
        src = (ROOT / "casino_client_profile.py").read_text()
        self.assertIn('detail="Игрок не найден"', src)
        self.assertIn("player_exists", src)
        self.assertIn("raise_if_missing", src)
        self.assertNotRegex(
            src.split("async def build_casino_client_profile")[1].split("async def load_casino")[0],
            r"if scoped == SCOPE_OPERATOR:[\s\S]*risk",
        )


class BuilderMissingPlayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_player_404(self):
        mod = _profile_mod()
        conn = AsyncMock()
        with patch("casino_player_profile.player_exists", new=AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                await mod.build_casino_client_profile(conn, 404, scope="operator")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Игрок не найден")

    async def test_operator_build_has_no_risk_key(self):
        mod = _profile_mod()
        conn = AsyncMock()
        web = {
            "player": {"user_id": 1, "display_name": "A"},
            "registered_at": "2026-01-01",
            "week_start": "2026-08-31",
            "wager_rub": "0.00",
            "lifetime_wager_rub": "0.00",
            "wager_by_game": [],
            "level": {"index": 1},
            "next_level": None,
            "own": {
                "available_rub": "50.00",
                "commission_profile": "wagering_complete",
                "commission_rate": "5.00",
                "cashback_percent": "0.00",
                "wagering": {"locked_rub": "0.00"},
                "payout_rail": {"crypto_allowed": True, "remaining_rub": "0.00"},
            },
        }
        with (
            patch("casino_player_profile.player_exists", new=AsyncMock(return_value=True)),
            patch("casino_player_profile.load_web_player_profile", new=AsyncMock(return_value=web)),
            patch(
                "casino_player_history.load_player_history",
                new=AsyncMock(return_value={"items": [], "next_before": None}),
            ),
            patch.object(mod, "_load_raffle", new=AsyncMock(return_value={"campaign_id": None, "tickets": 0, "status": None})),
            patch.object(mod, "_load_withdrawals", new=AsyncMock(return_value=[])),
            patch.object(mod, "_player_risk", new=AsyncMock(return_value={"house_net_rub": 99})),
        ):
            out = await mod.build_casino_client_profile(conn, 1, scope="operator")
        self.assertEqual(out["scope"], "operator")
        self.assertNotIn("risk", out)
        self.assertNotIn("house_net_rub", out)
        self.assertEqual(out["available_rub"], 50.0)

    async def test_admin_build_includes_risk(self):
        mod = _profile_mod()
        conn = AsyncMock()
        web = {
            "player": {"user_id": 1, "display_name": "A"},
            "registered_at": None,
            "week_start": "2026-08-31",
            "wager_rub": "100.00",
            "lifetime_wager_rub": "100.00",
            "wager_by_game": [],
            "level": {"index": 1},
            "next_level": None,
            "own": {
                "available_rub": "0",
                "commission_profile": "wagering_complete",
                "commission_rate": "5.00",
                "cashback_percent": "0.00",
                "wagering": {},
                "payout_rail": {},
            },
        }
        risk = {"house_net_rub": 40.0, "net_rub": -40.0, "risk": "medium"}
        with (
            patch("casino_player_profile.player_exists", new=AsyncMock(return_value=True)),
            patch("casino_player_profile.load_web_player_profile", new=AsyncMock(return_value=web)),
            patch(
                "casino_player_history.load_player_history",
                new=AsyncMock(return_value={"items": [{"game_type": "roulette"}], "next_before": None}),
            ),
            patch.object(mod, "_load_raffle", new=AsyncMock(return_value={"campaign_id": 1, "tickets": 2, "status": "active"})),
            patch.object(mod, "_load_withdrawals", new=AsyncMock(return_value=[])),
            patch.object(mod, "_player_risk", new=AsyncMock(return_value=risk)),
        ):
            out = await mod.build_casino_client_profile(conn, 1, scope="admin")
        self.assertEqual(out["scope"], "admin")
        self.assertEqual(out["risk"]["house_net_rub"], 40.0)
        self.assertTrue(out["played"])


if __name__ == "__main__":
    unittest.main()
