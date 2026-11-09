"""Duel lobby: net payout, stake bands, autojoin, sequential reveal."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from casino_duels import (
    BAND_HIGH,
    BAND_LOW,
    BAND_MID,
    assemble_duels_payload,
    build_duel_card,
    build_duel_room,
    duel_stake_band,
    fill_duel_actors,
    fill_eta_seconds,
    fill_label,
    group_duel_cards,
    net_payout_for_stake,
    pick_autojoin_target,
    public_duel_hands,
    pov_duel_hands,
    sequential_card_reveal_steps,
    sequential_reveal_steps,
)
from casino_finance import canonical_casino_settings


def _settings(**enabled: object):
    return canonical_casino_settings(
        [
            {"key": "enabled_games", "value": {"pvp_dice": True, "raffle": False, **enabled}},
            {"key": "min_bet_rub", "value": {"amount": 10}},
            {"key": "max_bet_rub", "value": {"amount": 100000}},
            {"key": "commission_rate_wagering_complete", "value": {"percent": 5}},
        ]
    )


class DuelLobbyModelTests(unittest.TestCase):
    def test_bands_match_plan_thresholds(self):
        self.assertEqual(duel_stake_band("499.99"), BAND_LOW)
        self.assertEqual(duel_stake_band("500"), BAND_MID)
        self.assertEqual(duel_stake_band("5000"), BAND_MID)
        self.assertEqual(duel_stake_band("5000.01"), BAND_HIGH)

    def test_net_payout_is_not_the_gross_pot(self):
        pot, commission, payout = net_payout_for_stake(_settings(), Decimal("100"))
        self.assertEqual(pot, Decimal("200.00"))
        self.assertEqual(commission, Decimal("5.00"))
        self.assertEqual(payout, Decimal("195.00"))
        self.assertNotEqual(payout, pot)

    def test_card_hides_creator_id_and_marks_mine(self):
        settings = _settings()
        row = {
            "game_id": "duel-mine",
            "game_type": "pvp_dice",
            "bet_rub": Decimal("50.00"),
            "created_at": datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            "creator_id": 941001,
            "opponent_id": None,
            "status": "waiting",
        }
        mine = build_duel_card(row, settings, viewer_id=941001)
        other = build_duel_card(row, settings, viewer_id=77)
        public = build_duel_card(row, settings, viewer_id=None)
        self.assertNotIn("creator_id", mine)
        self.assertIsNone(mine["creator"])
        self.assertIsNone(mine["opponent"])
        self.assertTrue(mine["is_mine"])
        self.assertFalse(other["is_mine"])
        self.assertFalse(public["is_mine"])
        self.assertEqual(mine["net_payout_rub"], 97.5)
        self.assertEqual(mine["bank_rub"], 100.0)
        self.assertFalse(mine["opponent_occupied"])

    def test_autojoin_picks_oldest_equal_stake_not_own(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        waiting = [
            {"game_id": "new", "game_type": "pvp_dice", "bet_rub": Decimal("50"), "creator_id": 2, "opponent_id": None, "status": "waiting", "created_at": now},
            {"game_id": "old", "game_type": "pvp_dice", "bet_rub": Decimal("50"), "creator_id": 3, "opponent_id": None, "status": "waiting", "created_at": now - timedelta(minutes=8)},
            {"game_id": "own", "game_type": "pvp_dice", "bet_rub": Decimal("50"), "creator_id": 1, "opponent_id": None, "status": "waiting", "created_at": now - timedelta(hours=1)},
            {"game_id": "other-stake", "game_type": "pvp_dice", "bet_rub": Decimal("100"), "creator_id": 4, "opponent_id": None, "status": "waiting", "created_at": now - timedelta(hours=2)},
        ]
        picked = pick_autojoin_target(waiting, game_type="pvp_dice", stake_rub="50", viewer_id=1)
        self.assertEqual(picked["game_id"], "old")

    def test_sequential_reveal_never_emits_both_seats_in_one_step(self):
        steps = sequential_reveal_steps(
            {"creator_rolls": [6, 4], "opponent_rolls": [3, 5]},
        )
        self.assertEqual([step["seat"] for step in steps], ["creator", "opponent", "creator", "opponent"])
        self.assertEqual([step["value"] for step in steps], [6, 3, 4, 5])
        self.assertEqual(steps[0]["leader"], "creator")
        self.assertEqual(steps[1]["leader"], "creator")
        self.assertEqual(steps[3]["leader"], "creator")
        for step in steps:
            self.assertIn(step["seat"], {"creator", "opponent"})

    def test_room_decodes_asyncpg_jsonb_string_into_sequential_steps(self):
        room = build_duel_room(
            {
                "game_id": "done",
                "game_type": "pvp_dice",
                "bet_rub": Decimal("50"),
                "created_at": datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
                "creator_id": 1,
                "opponent_id": 2,
                "status": "finished",
                "game_state": '{"creator_rolls":[2],"opponent_rolls":[5]}',
            },
            _settings(),
        )
        self.assertEqual([step["seat"] for step in room["steps"]], ["creator", "opponent"])
        self.assertEqual([step["value"] for step in room["steps"]], [2, 5])
        self.assertEqual(room["steps"][1]["leader"], "opponent")

    def test_fill_eta_median_and_stale_queue_label(self):
        self.assertEqual(fill_eta_seconds([60, 180, 900], fallback=120), 180)
        self.assertEqual(fill_eta_seconds([], fallback=900), 900)
        stale = fill_label(eta_seconds=300, oldest_wait_seconds=16 * 60, open_count=1)
        self.assertIn("стынет", stale)
        empty = fill_label(eta_seconds=120, oldest_wait_seconds=None, open_count=0)
        self.assertIn("обычно", empty)

    def test_group_keeps_three_bands_in_order(self):
        settings = _settings()
        cards = [
            build_duel_card(
                {"game_id": "a", "game_type": "pvp_dice", "bet_rub": Decimal("10"), "created_at": "", "creator_id": 1, "opponent_id": None, "status": "waiting"},
                settings,
            ),
            build_duel_card(
                {"game_id": "b", "game_type": "pvp_dice", "bet_rub": Decimal("8000"), "created_at": "", "creator_id": 2, "opponent_id": None, "status": "waiting"},
                settings,
            ),
        ]
        grouped = group_duel_cards(cards)
        self.assertEqual([item["band"] for item in grouped], [BAND_LOW, BAND_MID, BAND_HIGH])
        self.assertEqual(len(grouped[0]["duels"]), 1)
        self.assertEqual(len(grouped[1]["duels"]), 0)
        self.assertEqual(len(grouped[2]["duels"]), 1)

    def test_assemble_payload_has_fill_labels_and_no_creator_id(self):
        settings = _settings()
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        payload = assemble_duels_payload(
            settings,
            [
                {
                    "game_id": "x",
                    "game_type": "pvp_dice",
                    "bet_rub": Decimal("50"),
                    "created_at": now,
                    "creator_id": 9,
                    "opponent_id": None,
                    "status": "waiting",
                }
            ],
            [{"bet_rub": Decimal("50"), "wait_s": 90}],
            viewer_id=9,
        )
        dumped = str(payload)
        self.assertNotIn("creator_id", dumped)
        self.assertEqual(payload["commission_percent"], 5.0)
        low = payload["groups"][0]
        self.assertTrue(low["duels"][0]["is_mine"])
        self.assertIn("fill_label", low)


def _baccara_row(**overrides):
    row = {
        "game_id": "bak-1",
        "game_type": "baccara",
        "bet_rub": Decimal("100"),
        "created_at": datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        "creator_id": 11,
        "opponent_id": 22,
        "status": "finished",
        "game_state": {},
        "outcome": {
            "creator_cards": ["A♠", "9♦"],
            "opponent_cards": ["K♥", "2♣"],
        },
        "game_data": {},
    }
    row.update(overrides)
    return row


class DuelCardHandsTests(unittest.TestCase):
    def test_waiting_room_does_not_leak_faces_from_game_data(self):
        hidden = ["A♠", "9♦"]
        room = build_duel_room(
            _baccara_row(
                status="waiting",
                opponent_id=None,
                outcome={},
                game_data={"card_rng": {"creator_cards": hidden, "opponent_cards": ["K♥", "2♣"]}},
                game_state={"cards_creator": hidden, "cards_opponent": ["K♥", "2♣"]},
            ),
            _settings(baccara=True),
        )
        dumped = str(room)
        self.assertEqual(room["hands"], {"creator": [], "opponent": []})
        self.assertEqual(room["steps"], [])
        self.assertNotIn("A♠", dumped)
        self.assertNotIn("creator_id", dumped)
        self.assertEqual(room["net_payout_rub"], 195.0)

    def test_finished_baccarat_room_deals_one_seat_per_step(self):
        room = build_duel_room(_baccara_row(), _settings(baccara=True), viewer_id=99)
        self.assertEqual(room["hands"]["creator"], ["A♠", "9♦"])
        self.assertEqual(room["hands"]["opponent"], ["K♥", "2♣"])
        seats = [step["seat"] for step in room["steps"]]
        self.assertEqual(seats, ["creator", "opponent", "creator", "opponent"])
        for step in room["steps"]:
            self.assertIn("card", step)
            self.assertIsInstance(step["value"], int)
        self.assertEqual([step["card"] for step in room["steps"]], ["A♠", "K♥", "9♦", "2♣"])
        self.assertEqual(room["steps"][-1]["creator_sum"], 0)
        self.assertEqual(room["steps"][-1]["opponent_sum"], 2)
        self.assertEqual(room["steps"][-1]["leader"], "opponent")
        self.assertNotIn("creator_id", room)
        self.assertEqual(room["net_payout_rub"], 195.0)

    def test_finished_hands_from_game_data_json_string(self):
        room = build_duel_room(
            _baccara_row(
                outcome={},
                game_data='{"card_rng":{"creator_cards":["A♠","9♦"],"opponent_cards":["K♥","2♣"]}}',
            ),
            _settings(baccara=True),
        )
        self.assertEqual(room["hands"]["creator"], ["A♠", "9♦"])
        self.assertEqual(room["steps"][0]["card"], "A♠")

    def test_active_blackjack_hides_faces_until_finished(self):
        creator, opponent = public_duel_hands(
            {
                "status": "active",
                "outcome": {},
                "game_data": {"card_rng": {"creator_cards": ["A♠", "K♥"], "opponent_cards": ["9♦", "8♣"]}},
                "game_state": {"cards_creator": ["A♠", "K♥"]},
            }
        )
        self.assertEqual(creator, [])
        self.assertEqual(opponent, [])

    def test_active_viewer_sees_own_face_and_opponent_backs(self):
        row = _baccara_row(
            status="active",
            outcome={},
            game_data={"card_rng": {"creator_cards": ["A♠", "9♦"], "opponent_cards": ["K♥", "2♣"]}},
        )
        own, hidden = pov_duel_hands(row, viewer_id=11)
        self.assertEqual(own, ["A♠", "9♦"])
        self.assertEqual(hidden, [])
        other, own_opp = pov_duel_hands(row, viewer_id=22)
        self.assertEqual(other, [])
        self.assertEqual(own_opp, ["K♥", "2♣"])
        spectator_c, spectator_o = pov_duel_hands(row, viewer_id=99)
        self.assertEqual(spectator_c, [])
        self.assertEqual(spectator_o, [])
        room = build_duel_room(row, _settings(baccara=True), viewer_id=11)
        self.assertEqual(room["hands"]["creator"], ["A♠", "9♦"])
        self.assertEqual(room["hands"]["opponent"], [])
        dumped = str(room)
        self.assertIn("A♠", dumped)
        self.assertNotIn("K♥", dumped)

    def test_blackjack_steps_score_blackjack_and_never_both_seats(self):
        steps = sequential_card_reveal_steps(
            ["A♠", "K♥"],
            ["9♦", "8♣"],
            game_type="blackjack",
        )
        self.assertEqual([step["seat"] for step in steps], ["creator", "opponent", "creator", "opponent"])
        self.assertEqual(steps[-1]["creator_sum"], 21)
        self.assertEqual(steps[-1]["opponent_sum"], 17)
        self.assertEqual(steps[-1]["leader"], "creator")
        for step in steps:
            self.assertIn(step["seat"], {"creator", "opponent"})


class DuelActorFillTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_seat_stays_null_and_creator_has_nick(self):
        settings = _settings()
        row = {
            "game_id": "duel-open",
            "game_type": "pvp_dice",
            "bet_rub": Decimal("50.00"),
            "created_at": datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            "creator_id": 941001,
            "opponent_id": None,
            "status": "waiting",
        }
        card = build_duel_card(row, settings, viewer_id=77)

        class _Conn:
            async def fetch(self, query, *args):
                if "casino_player_cosmetics" in query:
                    return []
                raise AssertionError(query)

            async def fetchrow(self, query, *args):
                if "casino_chat_presence" in query:
                    return None
                if "FROM bot_users" in query:
                    return {"username": "ira", "first_name": "Ира"}
                if "FROM web_users" in query:
                    return None
                raise AssertionError(query)

        filled = await fill_duel_actors(_Conn(), card, row)
        self.assertEqual(filled["creator"]["user_id"], 941001)
        self.assertEqual(filled["creator"]["display_name"], "@ira")
        self.assertIsNone(filled["opponent"])
        self.assertNotIn("creator_id", filled)
        self.assertNotIn("level", filled["creator"])

    async def test_robot_seat_is_named_without_profile_id(self):
        settings = _settings()
        row = {
            "game_id": "duel-bot",
            "game_type": "pvp_dice",
            "bet_rub": Decimal("50.00"),
            "created_at": datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            "creator_id": 941001,
            "opponent_id": None,
            "status": "active",
            "game_data": {"robot_profile": {"display_name": "Куба"}},
        }
        card = build_duel_card(row, settings, viewer_id=77)

        class _Conn:
            async def fetch(self, query, *args):
                if "casino_player_cosmetics" in query:
                    return []
                raise AssertionError(query)

            async def fetchrow(self, query, *args):
                if "casino_chat_presence" in query:
                    return None
                if "FROM bot_users" in query:
                    return {"username": "ira", "first_name": "Ира"}
                if "FROM web_users" in query:
                    return None
                raise AssertionError(query)

        filled = await fill_duel_actors(_Conn(), card, row)
        self.assertEqual(filled["opponent"]["display_name"], "Куба")
        self.assertEqual(filled["opponent"]["user_id"], 0)
        self.assertEqual(filled["opponent"]["initial"], "К")
        self.assertTrue(str(filled["opponent"]["avatar_url"]).startswith("/api/public/casino-idents/"))
        self.assertTrue(filled["opponent_occupied"])
        self.assertEqual(filled["opponent_label"], "Куба")
        self.assertNotIn("creator_id", filled)
