"""Public casino lobby snapshot — enabled flags must come from settings, not the catalog."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("dependency override required")


_db_module = sys.modules.get("db")
if _db_module is None:
    sys.modules["db"] = types.SimpleNamespace(get_pool=_dependency_stub)

try:
    from casino_finance import KNOWN_GAME_TYPES, canonical_casino_settings
    from routers.public_casino import LOBBY_CATALOG, build_public_lobby
finally:
    if _db_module is None:
        del sys.modules["db"]


class PublicCasinoLobbyTests(unittest.TestCase):
    def test_disabled_raffle_stays_listed_and_waiting_has_no_creator_id(self):
        settings = canonical_casino_settings(
            [
                {"key": "enabled_games", "value": {"pvp_dice": True, "raffle": False, "cub": True}},
                {"key": "min_bet_rub", "value": {"amount": 10}},
                {"key": "max_bet_rub", "value": {"amount": 100000}},
                {"key": "commission_rate_wagering_complete", "value": {"percent": 5}},
            ]
        )
        payload = build_public_lobby(
            settings,
            [
                {
                    "game_id": "duel-1",
                    "game_type": "pvp_dice",
                    "bet_rub": Decimal("50.00"),
                    "created_at": datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
                    "creator_id": 941001,
                }
            ],
        )
        by_id = {item["id"]: item for item in payload["games"]}
        self.assertTrue(by_id["pvp_dice"]["enabled"])
        self.assertFalse(by_id["raffle"]["enabled"])
        self.assertEqual(payload["min_bet_rub"], 10.0)
        self.assertEqual(payload["commission_percent"], 5.0)
        self.assertEqual(len(payload["open_duels"]), 1)
        self.assertEqual(payload["open_duels"][0]["bet_rub"], 50.0)
        self.assertNotIn("creator_id", payload["open_duels"][0])
        self.assertNotIn("creator_id", payload)
        self.assertEqual(len(payload["games"]), 11)
        self.assertFalse(by_id["russian_draughts"]["enabled"])
        self.assertEqual({item["id"] for item in LOBBY_CATALOG}, set(KNOWN_GAME_TYPES))
        self.assertIn("roulette", by_id)
        self.assertFalse(by_id["roulette"]["enabled"])
        self.assertEqual([item["id"] for item in LOBBY_CATALOG].count("roulette"), 1)
        self.assertEqual(set(payload["open_duels"][0]), {"game_id", "game_type", "bet_rub", "opened_at"})
