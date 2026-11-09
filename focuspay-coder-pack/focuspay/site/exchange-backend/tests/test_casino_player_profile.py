from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import unittest

from fastapi import HTTPException

from casino_player_profile import load_web_player_profile, _iso_date
from casino_tier_config import DEFAULT_CASHBACK_VOLUME_TIERS, DEFAULT_COMMISSION_VOLUME_TIERS
from casino_tier_config import cashback_tiers_to_public, commission_tiers_to_public

_EMPTY_RAIL = {
    "fiat_deposited_rub": Decimal("0"),
    "card_withdrawn_rub": Decimal("0"),
    "remaining_rub": Decimal("0"),
    "crypto_allowed": True,
}


class _ProfileConn:
    def __init__(self, *, exists=True):
        self.exists = exists

    async def fetchrow(self, query, *args):
        if "SELECT 1 AS ok" in query:
            return {"ok": 1} if self.exists else None
        if "first_seen_at" in query:
            return {
                "first_seen_at": datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
                "created_at": None,
            }
        if "casino_chat_presence" in query:
            return {"display_name": "Ира"}
        if "FROM bot_users" in query:
            return {"username": "ira", "first_name": "Ира"}
        if "FROM web_users" in query:
            return None
        if "FROM casino_settings WHERE key" in query:
            return {"value": [{"min_wager_rub": 50000, "bonus_rub": 500}]}
        if "SUM(wager_rub)" in query or "wagers" in query:
            return {"wager_rub": Decimal("46141")}
        if "notify_open_tables" in query:
            return {"notify_open_tables": False}
        raise AssertionError(query)

    async def fetch(self, query, *args):
        if "casino_player_cosmetics" in query:
            return []
        if "key = ANY" in query:
            return [
                {"key": "cashback_volume_tiers", "value": cashback_tiers_to_public(DEFAULT_CASHBACK_VOLUME_TIERS)},
                {
                    "key": "commission_volume_tiers",
                    "value": commission_tiers_to_public(DEFAULT_COMMISSION_VOLUME_TIERS),
                },
            ]
        if "GROUP BY game_type" in query:
            return [
                {"game_type": "pvp_dice", "wager_rub": Decimal("30000")},
                {"game_type": "cub", "wager_rub": Decimal("16141")},
            ]
        raise AssertionError(query)


class CasinoPlayerProfileTests(unittest.IsolatedAsyncioTestCase):
    def test_registered_at_is_calendar_day(self):
        self.assertEqual(
            _iso_date(datetime(2026, 1, 15, 23, 59, tzinfo=timezone.utc)),
            "2026-01-15",
        )

    async def test_other_profile_hides_own_fields_and_bonus_copy(self):
        payload = await load_web_player_profile(_ProfileConn(), 9, viewer_id=1)
        self.assertFalse(payload["is_own"])
        self.assertEqual(payload["registered_at"], "2026-01-15")
        self.assertEqual(payload["player"]["display_name"], "Ира")
        self.assertNotIn("own", payload)
        self.assertNotIn("reach_bonus_rub", payload["level"])
        self.assertNotIn("reach_bonus_rub", payload["next_level"] or {})
        self.assertEqual(payload["wager_by_game"][0]["game_type"], "pvp_dice")
        self.assertEqual(payload["lifetime_wager_rub"], "46141.00")
        self.assertEqual(payload["next_level"]["remaining_wager_rub"], "3859.00")
        self.assertEqual(payload["next_level"]["index"], 2)
        self.assertEqual(payload["next_level"]["cashback_percent"], "5.00")
        self.assertEqual(payload["next_level"]["commission_complete_rate"], "4.00")

    async def test_own_profile_includes_balance_and_bonus_when_configured(self):
        with (
            patch(
                "casino_player_profile.commission_profile_for_player",
                new=AsyncMock(return_value=("wagering_complete", Decimal("5"))),
            ),
            patch(
                "casino_player_profile.wagering_progress",
                new=AsyncMock(
                    return_value={
                        "remaining_house_take_rub": Decimal("0"),
                        "required_house_take_rub": Decimal("0"),
                    }
                ),
            ),
            patch("casino_player_profile._own_available", new=AsyncMock(return_value=Decimal("120.50"))),
            patch("casino_player_profile.payout_rail_progress", new=AsyncMock(return_value=_EMPTY_RAIL)),
        ):
            payload = await load_web_player_profile(_ProfileConn(), 9, viewer_id=9)
        self.assertTrue(payload["is_own"])
        self.assertEqual(payload["own"]["available_rub"], "120.50")
        self.assertEqual(payload["own"]["payout_rail"]["crypto_allowed"], True)
        self.assertEqual(payload["own"]["payout_rail"]["remaining_rub"], "0.00")
        self.assertFalse(payload["own"]["notify_open_tables"])
        self.assertEqual(payload["next_level"]["reach_bonus_rub"], "500.00")
        self.assertEqual(payload["next_level"]["remaining_wager_rub"], "3859.00")

    async def test_own_web_client_negative_id_is_allowed(self):
        with (
            patch(
                "casino_player_profile.commission_profile_for_player",
                new=AsyncMock(return_value=("wagering_complete", Decimal("5"))),
            ),
            patch(
                "casino_player_profile.wagering_progress",
                new=AsyncMock(
                    return_value={
                        "remaining_house_take_rub": Decimal("0"),
                        "required_house_take_rub": Decimal("0"),
                    }
                ),
            ),
            patch("casino_player_profile._own_available", new=AsyncMock(return_value=Decimal("570.00"))),
            patch("casino_player_profile.payout_rail_progress", new=AsyncMock(return_value=_EMPTY_RAIL)),
        ):
            payload = await load_web_player_profile(_ProfileConn(), -1, viewer_id=-1)
        self.assertTrue(payload["is_own"])
        self.assertEqual(payload["player"]["user_id"], -1)
        self.assertEqual(payload["own"]["available_rub"], "570.00")

    async def test_unknown_other_player_is_not_found(self):
        with self.assertRaises(HTTPException) as raised:
            await load_web_player_profile(_ProfileConn(exists=False), 99, viewer_id=1)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Игрок не найден")
