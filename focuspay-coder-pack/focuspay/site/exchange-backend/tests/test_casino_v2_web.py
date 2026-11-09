"""V2 web dice: pot/commission numbers, HMAC rolls, bot seats, CAS version."""
from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from casino_finance import calculate_equal_stake_settlement, money
from casino_v2_web import (
    WEB_V2_COMMISSION_RATE,
    WEB_V2_GAME_TYPES,
    WEB_V2_ROLL_TIMEOUT_SECONDS,
    WEB_V2_TELEGRAM_HIT_TIMEOUT_SECONDS,
    TELEGRAM_STALE_IDLE_SECONDS,
    blackjack_hit_timeout_seconds,
    blackjack_hole_cards_hidden,
    blackjack_web_decisions,
    V2WebCreateBody,
    _roster_has_human,
    apply_roll,
    create_web_table,
    fill_hmac_rolls,
    house_fill_table,
    hmac_face,
    hmac_index,
    is_web_card_table,
    leader_seat_nos,
    preview_v2_equal_pot,
    auto_join_due,
    public_table_view,
    scoring_decision,
    seat_totals,
    telegram_play_surface,
    tie_break_state,
    translate_v2,
    v2_play_is_stale,
)


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("Database dependency must be patched in unit tests")


sys.modules.setdefault("db", types.SimpleNamespace(get_pool=_dependency_stub))
import routers.internal_casino as internal_casino
if isinstance(sys.modules.get("db"), types.SimpleNamespace):
    sys.modules.pop("db", None)
from routers.internal_casino import (
    V2TableCommitOutcomeRequest,
    V2TableJoinRequest,
    V2TableSettleRequest,
    commit_v2_table_outcome_with_conn,
    join_v2_table_with_conn,
    settle_v2_table_with_conn,
)


class _V2Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _V2SettleConn:
    def __init__(self, table, seats, reservation=None):
        self.table = table
        self.seats = seats
        self.reservation = reservation
        self.execute = AsyncMock()
        self.fetch = AsyncMock(return_value=seats)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    def transaction(self):
        return _V2Savepoint()

    async def _fetchrow(self, query, *args):
        if "FROM casino_v2_tables" in query:
            return self.table
        if "FROM casino_v2_house_reservations" in query:
            return self.reservation
        if "UPDATE casino_house_accounts" in query:
            return {"id": 3, "balance_rub": Decimal("1000.00")}
        if "UPDATE casino_v2_tables SET status='settling'" in query:
            return {**self.table, "status": "settling", "state_version": self.table["state_version"] + 1}
        if "UPDATE casino_v2_tables SET status='finished'" in query:
            return {**self.table, "status": "finished", "state_version": self.table["state_version"] + 2}
        if "casino_v2_lifecycle_idempotency" in query:
            return None
        return None


class V2WebPotTests(unittest.TestCase):
    def test_two_way_one_hundred_is_two_hundred_pot_ten_commission_one_ninety_net(self):
        preview = preview_v2_equal_pot(Decimal("100"), 2)
        self.assertEqual(preview["pot_rub"], "200.00")
        self.assertEqual(preview["commission_rub"], "10.00")
        self.assertEqual(preview["net_payout_rub"], "190.00")
        self.assertEqual(WEB_V2_COMMISSION_RATE, Decimal("0.05"))

    def test_three_way_one_hundred_is_three_hundred_pot_fifteen_commission(self):
        preview = preview_v2_equal_pot(Decimal("100"), 3)
        self.assertEqual(preview["pot_rub"], "300.00")
        self.assertEqual(preview["commission_rub"], "15.00")
        self.assertEqual(preview["net_payout_rub"], "285.00")

    def test_v2_pot_is_not_the_1x1_equal_stake_helper(self):
        duel = calculate_equal_stake_settlement(Decimal("100"), Decimal("5"))
        v2 = preview_v2_equal_pot(Decimal("100"), 2)
        self.assertEqual(str(duel.pot), "200.00")
        self.assertEqual(str(duel.commission), "5.00")
        self.assertEqual(str(duel.payout), "195.00")
        self.assertEqual(v2["commission_rub"], "10.00")
        self.assertEqual(v2["net_payout_rub"], "190.00")
        self.assertNotEqual(v2["net_payout_rub"], str(duel.payout))


class V2WebHmacTests(unittest.TestCase):
    def test_hmac_face_is_stable_and_not_client_rng(self):
        first = hmac_face(seed="abc", table_id="t1", seat_no=1, index=0, kind="player")
        second = hmac_face(seed="abc", table_id="t1", seat_no=1, index=0, kind="player")
        house = hmac_face(seed="abc", table_id="t1", seat_no=1, index=0, kind="house")
        bot = hmac_face(seed="abc", table_id="t1", seat_no=2, index=0, kind="bot")
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 1)
        self.assertLessEqual(first, 6)
        self.assertGreaterEqual(house, 1)
        self.assertLessEqual(house, 6)
        self.assertGreaterEqual(bot, 1)
        self.assertLessEqual(bot, 6)
        kinds = {hmac_face(seed="abc", table_id="t1", seat_no=1, index=i, kind="player") for i in range(8)}
        kinds |= {hmac_face(seed="abc", table_id="t1", seat_no=1, index=i, kind="house") for i in range(8)}
        self.assertGreater(len(kinds), 1)

    def test_bot_hmac_fills_only_bot_seats(self):
        state = {"seat_nos": [1, 2, 3], "rolls": {}, "rounds": 1, "phase": "rolling"}
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 10},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "Кубик"}},
            {"seat_no": 3, "participant_kind": "player", "telegram_id": 20},
        ]
        filled = fill_hmac_rolls(state, roster, table_id="tbl", seed="seed-1", kinds=frozenset({"bot"}))
        self.assertIn("s2r0", filled["rolls"])
        self.assertNotIn("s1r0", filled["rolls"])
        self.assertNotIn("s3r0", filled["rolls"])
        self.assertEqual(filled["rolls"]["s2r0"], hmac_face(seed="seed-1", table_id="tbl", seat_no=2, index=0, kind="bot"))


class V2WebGameplayTests(unittest.TestCase):
    def test_three_way_highest_pip_wins(self):
        state = {"seat_nos": [1, 2, 3], "rolls": {}, "rounds": 1}
        state = apply_roll(state, seat_no=1, roll_index=0, value=2, required=1)
        state = apply_roll(state, seat_no=2, roll_index=0, value=6, required=1)
        state = apply_roll(state, seat_no=3, roll_index=0, value=5, required=1)
        roster = [{"seat_no": n, "participant_kind": "player"} for n in (1, 2, 3)]
        decision = scoring_decision(state, roster)
        self.assertEqual(decision["kind"], "winner")
        self.assertEqual(decision["winner_seat_nos"], [2])
        self.assertEqual(seat_totals(state["rolls"], [1, 2, 3], 1), {1: 2, 2: 6, 3: 5})

    def test_two_way_tie_requests_tie_break(self):
        state = {"seat_nos": [1, 2], "rolls": {"s1r0": 4, "s2r0": 4}, "rounds": 1, "draw_policy": "tie_break"}
        decision = scoring_decision(state, [{"seat_no": 1}, {"seat_no": 2}])
        self.assertEqual(decision["kind"], "tie_break")
        self.assertEqual(decision["winner_seat_nos"], [1, 2])
        self.assertEqual(leader_seat_nos({1: 4, 2: 4}), [1, 2])

    def test_tie_break_hmac_does_not_reuse_first_round_index(self):
        seed, table_id = "seed-tie", "web-531386ff43fe4fd3"
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 10},
            {"seat_no": 2, "participant_kind": "bot"},
        ]
        first_bot = hmac_face(seed=seed, table_id=table_id, seat_no=2, index=0, kind="bot")
        reroll_bot = hmac_face(seed=seed, table_id=table_id, seat_no=2, index=1, kind="bot")
        first_player = hmac_face(seed=seed, table_id=table_id, seat_no=1, index=0, kind="player")
        reroll_player = hmac_face(seed=seed, table_id=table_id, seat_no=1, index=1, kind="player")
        self.assertNotEqual(first_bot, reroll_bot)
        self.assertNotEqual(first_player, reroll_player)
        state = {
            "seat_nos": [1, 2],
            "rolls": {"s1r0": first_player, "s2r0": first_bot},
            "rounds": 1,
            "phase": "scoring",
            "draw_policy": "tie_break",
        }
        cleared = tie_break_state(state, [1, 2])
        self.assertEqual(cleared["tie_break_round"], 1)
        self.assertEqual(cleared["rolls"], {})
        filled = fill_hmac_rolls(cleared, roster, table_id=table_id, seed=seed, kinds=frozenset({"bot"}))
        self.assertEqual(filled["rolls"]["s2r0"], reroll_bot)
        self.assertNotEqual(filled["rolls"]["s2r0"], first_bot)
        self.assertNotIn("s1r0", filled["rolls"])
        self.assertEqual(hmac_index(cleared, 0), 1)
        self.assertEqual(hmac_index({"rounds": 1}, 0), 0)
        self.assertEqual(hmac_index({"rounds": 2, "tie_break_round": 1}, 1), 3)


class V2WebPublicViewTests(unittest.TestCase):
    def test_strips_hmac_seed_and_top_level_creator_id(self):
        row = {
            "table_id": "web-1",
            "game_type": "pvp_dice",
            "creator_id": 940001,
            "stake_rub": Decimal("100.00"),
            "max_seats": 3,
            "status": "running",
            "state_version": 4,
            "game_state": {
                "hmac": {"seed": "super-secret", "commit": "abc123"},
                "rolls": {"s1r0": 3},
                "rounds": 1,
                "seat_nos": [1, 2],
                "bot_count": 1,
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"profile_key": "pvp", "display_name": "Робот"}},
        ]
        view = public_table_view(row, roster, viewer_id=940001)
        dumped = json.dumps(view)
        self.assertNotIn("creator_id", view)
        self.assertNotIn("super-secret", dumped)
        self.assertEqual(view["game_state"]["commit"], "abc123")
        self.assertNotIn("seed", view["game_state"])
        self.assertEqual(view["roster"][1]["actor"]["user_id"], 0)
        self.assertEqual(view["roster"][1]["actor"]["display_name"], "Робот")
        self.assertTrue(view["roster"][0]["is_you"])
        self.assertFalse(view["can_add_bot"])
        self.assertEqual(view["pot_rub"], "200.00")
        self.assertEqual(view["commission_rub"], "10.00")
        self.assertEqual(view["net_payout_rub"], "190.00")

    def test_blackjack_draw_choice_exposes_flags_and_leaders(self):
        row = {
            "table_id": "web-bj",
            "game_type": "blackjack",
            "creator_id": 940001,
            "stake_rub": Decimal("100.00"),
            "max_seats": 3,
            "status": "running",
            "state_version": 5,
            "game_state": {
                "phase": "draw_choice",
                "tie_break_seat_nos": [1, 2],
                "draw_choice_deadline_at": "2099-01-01T00:00:00+00:00",
                "scores": {"1": 19, "2": 19, "3": 25},
                "hands": {"1": ["A♣", "8♦"], "2": ["A♠", "8♥"], "3": ["8♣", "8♥", "9♥"]},
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 1"}},
            {"seat_no": 3, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 2"}},
        ]
        view = public_table_view(row, roster, viewer_id=940001)
        self.assertTrue(view["can_choose_draw"])
        self.assertEqual(view["game_state"]["phase"], "draw_choice")
        self.assertTrue(view["roster"][0]["is_leader"])
        self.assertTrue(view["roster"][1]["is_leader"])
        self.assertFalse(view["roster"][2]["is_leader"])
        outsider = public_table_view(row, roster, viewer_id=999)
        self.assertFalse(outsider["can_choose_draw"])

    def test_blackjack_hitting_exposes_hit_stand_for_seated_player(self):
        row = {
            "table_id": "web-bj-hit",
            "game_type": "blackjack",
            "creator_id": 940001,
            "stake_rub": Decimal("100.00"),
            "max_seats": 3,
            "status": "running",
            "state_version": 6,
            "game_state": {
                "phase": "hitting",
                "roll_deadline_at": "2099-01-01T00:00:00+00:00",
                "scores": {"1": 12, "2": 19},
                "hands": {"1": ["K♠", "2♦"], "2": ["A♠", "8♥"]},
                "stood_seats": [2],
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 1"}},
        ]
        view = public_table_view(row, roster, viewer_id=940001)
        self.assertTrue(view["can_hit"])
        self.assertTrue(view["can_stand"])
        self.assertFalse(view["can_choose_draw"])
        self.assertEqual(view["game_state"]["phase"], "hitting")
        outsider = public_table_view(row, roster, viewer_id=999)
        self.assertFalse(outsider["can_hit"])

    def test_active_blackjack_hides_other_faces_until_showdown(self):
        row = {
            "table_id": "web-bj-pov",
            "game_type": "blackjack",
            "creator_id": 940001,
            "stake_rub": Decimal("25.00"),
            "max_seats": 2,
            "status": "running",
            "state_version": 6,
            "game_state": {
                "phase": "hitting",
                "seat_nos": [1, 2],
                "scores": {"1": 12, "2": 17},
                "hands": {"1": ["2♥", "A♦"], "2": ["10♦", "7♣"]},
                "stood_seats": [],
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 940002},
        ]
        own = public_table_view(row, roster, viewer_id=940001)
        self.assertTrue(blackjack_hole_cards_hidden(row, row["game_state"], roster))
        self.assertEqual(own["roster"][0]["cards"], ["2♥", "A♦"])
        self.assertEqual(own["roster"][0]["score"], 12)
        self.assertEqual(own["roster"][1]["cards"], ["back", "back"])
        self.assertIsNone(own["roster"][1]["score"])
        drawing = {
            **row,
            "game_state": {
                **row["game_state"],
                "hands": {"1": ["2♥", "A♦", "5♣"], "2": ["10♦", "7♣", "3♠", "K♥"]},
                "scores": {"1": 18, "2": 20},
            },
        }
        drawing_view = public_table_view(drawing, roster, viewer_id=940001)
        self.assertEqual(drawing_view["roster"][0]["cards"], ["2♥", "A♦", "5♣"])
        self.assertEqual(drawing_view["roster"][1]["cards"], ["back", "back"])
        self.assertEqual(drawing_view["game_state"]["hands"]["2"], ["back", "back"])
        watcher = public_table_view(drawing, roster, viewer_id=None)
        self.assertEqual(watcher["roster"][0]["cards"], ["back", "back"])
        self.assertEqual(watcher["roster"][1]["cards"], ["back", "back"])
        watch_dump = json.dumps(watcher, ensure_ascii=False)
        self.assertNotIn("5♣", watch_dump)
        self.assertNotIn("3♠", watch_dump)
        dumped = json.dumps(own, ensure_ascii=False)
        self.assertIn("2♥", dumped)
        self.assertNotIn("10♦", dumped)
        self.assertNotIn("7♣", dumped)
        self.assertEqual(own["game_state"]["hands"]["2"], ["back", "back"])
        self.assertNotIn("2", own["game_state"]["scores"])

        spectator = public_table_view(row, roster, viewer_id=None)
        self.assertEqual(spectator["roster"][0]["cards"], ["back", "back"])
        self.assertEqual(spectator["roster"][1]["cards"], ["back", "back"])
        self.assertIsNone(spectator["roster"][0]["score"])
        spec_dump = json.dumps(spectator, ensure_ascii=False)
        self.assertNotIn("2♥", spec_dump)
        self.assertNotIn("10♦", spec_dump)

        other = public_table_view(row, roster, viewer_id=940002)
        self.assertEqual(other["roster"][1]["cards"], ["10♦", "7♣"])
        self.assertEqual(other["roster"][0]["cards"], ["back", "back"])
        other_dump = json.dumps(other, ensure_ascii=False)
        self.assertNotIn("2♥", other_dump)

    def test_blackjack_deal_window_keeps_other_faces_hidden(self):
        row = {
            "table_id": "web-bj-deal",
            "game_type": "blackjack",
            "creator_id": 940001,
            "stake_rub": Decimal("10.00"),
            "max_seats": 2,
            "status": "running",
            "state_version": 3,
            "game_state": {
                "phase": "scoring",
                "seat_nos": [1, 2],
                "scores": {"1": 20, "2": 21},
                "hands": {"1": ["K♠", "Q♦"], "2": ["A♠", "K♥"]},
                "stood_seats": [],
                "cards_dealt_at": "2026-10-12T21:00:00+00:00",
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 1"}},
        ]
        view = public_table_view(row, roster, viewer_id=940001)
        self.assertTrue(blackjack_hole_cards_hidden(row, row["game_state"], roster))
        self.assertEqual(view["roster"][0]["cards"], ["K♠", "Q♦"])
        self.assertEqual(view["roster"][1]["cards"], ["back", "back"])
        dumped = json.dumps(view, ensure_ascii=False)
        self.assertNotIn("A♠", dumped)
        self.assertNotIn("K♥", dumped)

    def test_blackjack_showdown_and_baccarat_keep_public_faces(self):
        finished = {
            "table_id": "web-bj-done-faces",
            "game_type": "blackjack",
            "creator_id": 940001,
            "stake_rub": Decimal("25.00"),
            "max_seats": 2,
            "status": "finished",
            "state_version": 9,
            "game_state": {
                "phase": "settled",
                "scores": {"1": 12, "2": 17},
                "hands": {"1": ["2♥", "A♦"], "2": ["10♦", "7♣"]},
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 940002},
        ]
        view = public_table_view(finished, roster, viewer_id=None)
        self.assertEqual(view["roster"][0]["cards"], ["2♥", "A♦"])
        self.assertEqual(view["roster"][1]["cards"], ["10♦", "7♣"])

        draw = {
            "table_id": "web-bj-draw",
            "game_type": "blackjack",
            "creator_id": 940001,
            "stake_rub": Decimal("100.00"),
            "max_seats": 2,
            "status": "running",
            "state_version": 5,
            "game_state": {
                "phase": "draw_choice",
                "tie_break_seat_nos": [1, 2],
                "scores": {"1": 19, "2": 19},
                "hands": {"1": ["A♣", "8♦"], "2": ["A♠", "8♥"]},
            },
        }
        draw_view = public_table_view(draw, roster, viewer_id=999)
        self.assertEqual(draw_view["roster"][0]["cards"], ["A♣", "8♦"])
        self.assertIn("A♠", json.dumps(draw_view, ensure_ascii=False))

        baccara = {
            "table_id": "web-bak",
            "game_type": "baccara",
            "creator_id": 940001,
            "stake_rub": Decimal("50.00"),
            "max_seats": 2,
            "status": "running",
            "state_version": 3,
            "game_state": {
                "phase": "scoring",
                "hands": {"1": ["2♠", "7♥"], "2": ["10♥", "5♣"]},
                "scores": {"1": 9, "2": 5},
            },
        }
        bak = public_table_view(baccara, roster, viewer_id=None)
        self.assertEqual(bak["roster"][0]["cards"], ["2♠", "7♥"])
        self.assertEqual(bak["roster"][1]["cards"], ["10♥", "5♣"])

    def test_web_blackjack_decisions_mark_stand_only_when_seat_is_done(self):
        state = {"decisions": {"2": "stand"}}
        still_hitting = blackjack_web_decisions(state, seat_no=1, mark_stand=False)
        self.assertEqual(still_hitting, {"2": "stand"})
        done = blackjack_web_decisions(state, seat_no=1, mark_stand=True)
        self.assertEqual(done, {"2": "stand", "1": "stand"})

    def test_finished_tie_split_exposes_per_seat_payouts(self):
        row = {
            "table_id": "web-bj-done",
            "game_type": "blackjack",
            "creator_id": 940001,
            "stake_rub": Decimal("100.00"),
            "max_seats": 3,
            "status": "finished",
            "state_version": 8,
            "game_state": {"phase": "settled", "scores": {"1": 19, "2": 19, "3": 25}},
            "settlement_payload": {
                "outcome_kind": "tie_split",
                "winner_seat_nos": [1, 2],
                "pot_rub": "300.00",
                "commission_rub": "15.00",
                "payouts": [
                    {"seat_no": 1, "amount_rub": "142.50"},
                    {"seat_no": 2, "amount_rub": "142.50"},
                ],
            },
            "outcome": {"kind": "tie_split", "winner_seat_nos": [1, 2]},
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 1"}},
            {"seat_no": 3, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 2"}},
        ]
        view = public_table_view(row, roster, viewer_id=940001)
        self.assertEqual(view["settlement"]["payouts"][0]["amount_rub"], "142.50")
        self.assertEqual(view["roster"][0]["payout_rub"], "142.50")
        self.assertEqual(view["roster"][1]["payout_rub"], "142.50")
        self.assertIsNone(view["roster"][2]["payout_rub"])
        self.assertTrue(view["roster"][0]["is_winner"])
        self.assertEqual(view["net_payout_rub"], "285.00")

    def test_open_table_lets_seated_player_add_bot(self):
        row = {
            "table_id": "web-open",
            "game_type": "pvp_dice",
            "creator_id": 7,
            "stake_rub": Decimal("50.00"),
            "max_seats": 4,
            "status": "open",
            "state_version": 1,
            "game_state": {"bot_count": 0, "rounds": 1},
        }
        roster = [{"seat_no": 1, "participant_kind": "player", "telegram_id": 7}]
        view = public_table_view(row, roster, viewer_id=7)
        self.assertTrue(view["can_add_bot"])
        self.assertEqual(view["free_seats"], [2, 3, 4])
        outsider = public_table_view(row, roster, viewer_id=8)
        self.assertFalse(outsider["can_add_bot"])

    def test_finished_table_reveals_seed(self):
        row = {
            "table_id": "web-2",
            "game_type": "pvp_dice",
            "creator_id": 1,
            "stake_rub": Decimal("50"),
            "max_seats": 2,
            "status": "finished",
            "state_version": 8,
            "game_state": {"hmac": {"seed": "open-seed", "commit": "ccc"}, "rounds": 1, "rolls": {"s1r0": 6, "s2r0": 1}},
            "settlement_payload": {
                "outcome_kind": "winner",
                "winner_seat_nos": [1],
                "pot_rub": "100.00",
                "commission_rub": "5.00",
                "payouts": [{"seat_no": 1, "amount_rub": "95.00"}],
            },
        }
        view = public_table_view(row, [{"seat_no": 1, "participant_kind": "player", "telegram_id": 1}], viewer_id=1)
        self.assertEqual(view["game_state"]["seed"], "open-seed")
        self.assertEqual(view["settlement"]["pot_rub"], "100.00")
        self.assertEqual([seat["seat_no"] for seat in view["roster"]], [1, 2])
        self.assertEqual(view["roster"][0]["pips"], 6)
        self.assertEqual(view["roster"][1]["pips"], 1)
        self.assertTrue(view["roster"][0]["is_winner"])
        self.assertFalse(view["roster"][1]["is_winner"])

    def test_finished_empty_roster_rebuilds_seats_from_rolls(self):
        row = {
            "table_id": "web-3",
            "game_type": "pvp_dice",
            "creator_id": 11,
            "stake_rub": Decimal("100"),
            "max_seats": 3,
            "status": "finished",
            "state_version": 9,
            "game_state": {
                "hmac": {"seed": "s", "commit": "c"},
                "rounds": 1,
                "seat_nos": [1, 2, 3],
                "rolls": {"s1r0": 2, "s2r0": 6, "s3r0": 5},
            },
            "settlement_payload": {
                "outcome_kind": "winner",
                "winner_seat_nos": [2],
                "pot_rub": "300.00",
                "commission_rub": "15.00",
                "payouts": [{"seat_no": 2, "amount_rub": "285.00"}],
            },
        }
        view = public_table_view(row, [], viewer_id=11)
        self.assertEqual([seat["pips"] for seat in view["roster"]], [2, 6, 5])
        self.assertEqual([seat["is_winner"] for seat in view["roster"]], [False, True, False])
        self.assertEqual(view["net_payout_rub"], "285.00")

    def test_cas_conflict_is_russian(self):
        mapped = translate_v2(HTTPException(status_code=409, detail="V2 table state version conflicts"))
        self.assertEqual(mapped.status_code, 409)
        self.assertIn("изменился", mapped.detail)
        reroll = translate_v2(HTTPException(status_code=409, detail="V2 table cannot enter tie break"))
        self.assertIn("переброс", reroll.detail)

    def test_persist_body_accepts_hmac_rolls_without_house_settlement(self):
        req = internal_casino.V2TablePersistStateRequest(
            expected_state_version=1,
            idempotency_key="hmac-init",
            game_state={
                "hmac": {"seed": "aa", "commit": "bb"},
                "seat_nos": [1, 2],
                "rolls": {"s1r0": 6},
                "phase": "rolling",
            },
        )
        self.assertEqual(req.game_state["rolls"]["s1r0"], 6)
        self.assertEqual(req.game_state["hmac"]["commit"], "bb")


class V2WebJoinConflictTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_state_version_conflicts(self):
        table = {
            "id": 10,
            "table_id": "cas-1",
            "game_type": "pvp_dice",
            "creator_id": 100,
            "stake_rub": Decimal("100.00"),
            "max_seats": 3,
            "status": "open",
            "state_version": 4,
            "game_state": {"bot_count": 0},
        }
        conn = SimpleNamespace(
            execute=AsyncMock(),
            fetch=AsyncMock(),
            fetchrow=AsyncMock(side_effect=[table, None]),
        )
        body = V2TableJoinRequest(telegram_id=200, expected_state_version=1, idempotency_key="stale-join")
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), self.assertRaises(HTTPException) as raised:
            await join_v2_table_with_conn(conn, "cas-1", body)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "V2 table state version conflicts")
        self.assertIn("изменился", translate_v2(raised.exception).detail)
        conn.fetch.assert_not_awaited()


class V2WebSettleNumberTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_player_settle_matches_preview(self):
        preview = preview_v2_equal_pot(Decimal("100"), 2)
        table = {
            "id": 10, "table_id": "two-way", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 2, "status": "outcome_committed", "state_version": 0,
            "game_state": {}, "outcome": {"kind": "winner", "winner_seat_nos": [1]},
        }
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-1"},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 200, "hold_order_ref": "hold-2"},
        ]
        conn = _V2SettleConn(table, seats)
        request = V2TableSettleRequest(
            expected_state_version=0, outcome_kind="winner", winner_seat_nos=[1], idempotency_key="two-way",
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()) as confirm, patch.object(
            internal_casino, "_credit_winner", new=AsyncMock()
        ) as credit:
            result = await settle_v2_table_with_conn(conn, "two-way", request)
        self.assertEqual(result["pot_rub"], preview["pot_rub"])
        self.assertEqual(result["commission_rub"], preview["commission_rub"])
        self.assertEqual(result["payouts"], [{"seat_no": 1, "amount_rub": preview["net_payout_rub"]}])
        self.assertEqual(confirm.await_count, 2)
        self.assertEqual(credit.await_count, 1)
        self.assertEqual(credit.await_args.kwargs["payout_rub"], money(preview["net_payout_rub"]))
        self.assertEqual(credit.await_args.kwargs["winner_id"], 100)
        ledger_sql = " ".join(
            str(call.args[0]) for call in conn.execute.await_args_list if call.args
        )
        ledger_args = " ".join(
            str(arg) for call in conn.execute.await_args_list for arg in call.args[1:]
        )
        self.assertIn("casino_v2_house_ledger", ledger_sql)
        self.assertIn("v2-settlement-two-way", ledger_args)

    async def test_three_player_settle_matches_preview(self):
        preview = preview_v2_equal_pot(Decimal("100"), 3)
        table = {
            "id": 11, "table_id": "three-way", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 3, "status": "outcome_committed", "state_version": 0,
            "game_state": {}, "outcome": {"kind": "winner", "winner_seat_nos": [3]},
        }
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "h1"},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 200, "hold_order_ref": "h2"},
            {"seat_no": 3, "participant_kind": "player", "telegram_id": 300, "hold_order_ref": "h3"},
        ]
        conn = _V2SettleConn(table, seats)
        request = V2TableSettleRequest(
            expected_state_version=0, outcome_kind="winner", winner_seat_nos=[3], idempotency_key="three-way",
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()) as confirm, patch.object(
            internal_casino, "_credit_winner", new=AsyncMock()
        ) as credit:
            result = await settle_v2_table_with_conn(conn, "three-way", request)
        self.assertEqual(result["pot_rub"], "300.00")
        self.assertEqual(result["commission_rub"], "15.00")
        self.assertEqual(result["payouts"], [{"seat_no": 3, "amount_rub": "285.00"}])
        self.assertEqual(result["payouts"][0]["amount_rub"], preview["net_payout_rub"])
        self.assertEqual(confirm.await_count, 3)
        self.assertEqual(credit.await_args.kwargs["winner_id"], 300)
        self.assertEqual(credit.await_args.kwargs["payout_rub"], Decimal("285.00"))


class V2WebBotSeatSettleTests(unittest.IsolatedAsyncioTestCase):
    async def test_player_win_versus_bot_credits_only_the_player(self):
        preview = preview_v2_equal_pot(Decimal("100"), 2)
        table = {
            "id": 12, "table_id": "bot-seat", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 2, "status": "outcome_committed", "state_version": 0,
            "game_state": {"bot_count": 1}, "outcome": {"kind": "winner", "winner_seat_nos": [1]},
        }
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-p"},
            {"seat_no": 2, "participant_kind": "bot", "telegram_id": None, "robot_profile_id": 7, "hold_order_ref": None},
        ]
        reservation = {"id": 1, "account_id": 3, "amount_rub": Decimal("100.00"), "status": "active"}
        conn = _V2SettleConn(table, seats, reservation=reservation)
        request = V2TableSettleRequest(
            expected_state_version=0, outcome_kind="winner", winner_seat_nos=[1], idempotency_key="bot-win-player",
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()) as confirm, patch.object(
            internal_casino, "_credit_winner", new=AsyncMock()
        ) as credit:
            result = await settle_v2_table_with_conn(conn, "bot-seat", request)
        self.assertEqual(result["pot_rub"], "200.00")
        self.assertEqual(result["commission_rub"], "10.00")
        self.assertEqual(result["payouts"][0]["amount_rub"], preview["net_payout_rub"])
        self.assertEqual(confirm.await_count, 1)
        self.assertEqual(confirm.await_args.kwargs["user_id"], 100)
        self.assertEqual(credit.await_count, 1)
        self.assertEqual(credit.await_args.kwargs["winner_id"], 100)

    async def test_bot_win_does_not_credit_a_user_balance(self):
        table = {
            "id": 13, "table_id": "bot-takes", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 2, "status": "outcome_committed", "state_version": 0,
            "game_state": {"bot_count": 1}, "outcome": {"kind": "winner", "winner_seat_nos": [2]},
        }
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-p"},
            {"seat_no": 2, "participant_kind": "bot", "telegram_id": None, "robot_profile_id": 7},
        ]
        reservation = {"id": 1, "account_id": 3, "amount_rub": Decimal("100.00"), "status": "active"}
        conn = _V2SettleConn(table, seats, reservation=reservation)
        request = V2TableSettleRequest(
            expected_state_version=0, outcome_kind="winner", winner_seat_nos=[2], idempotency_key="bot-takes",
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()) as confirm, patch.object(
            internal_casino, "_credit_winner", new=AsyncMock()
        ) as credit:
            result = await settle_v2_table_with_conn(conn, "bot-takes", request)
        self.assertEqual(result["payouts"], [{"seat_no": 2, "amount_rub": "190.00"}])
        self.assertEqual(confirm.await_count, 1)
        self.assertEqual(confirm.await_args.kwargs["user_id"], 100)
        credit.assert_not_awaited()


class V2WebSeatBotModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_table_does_not_seat_a_bot(self):
        conn = SimpleNamespace(fetch=AsyncMock(), fetchrow=AsyncMock(), transaction=AsyncMock())
        joined = await auto_join_due(conn, now=datetime(2026, 10, 13, tzinfo=timezone.utc))
        self.assertEqual(joined, 0)
        conn.fetch.assert_not_called()
        conn.fetchrow.assert_not_called()

    def test_internal_bot_sql_is_pvp_robot_not_house_robot(self):
        import inspect

        source = inspect.getsource(internal_casino._seat_v2_bots_with_conn)
        self.assertIn("pvp_robot", source)
        self.assertNotIn("house_robot", source)
        self.assertNotIn("house_settlement", source)
        self.assertNotIn("calculate_house_settlement", inspect.getsource(internal_casino.settle_v2_table_with_conn))


class V2WebChainedTieBreakTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_tie_break_is_allowed_from_tie_break_running(self):
        table = {
            "id": 20,
            "table_id": "web-reroll",
            "game_type": "pvp_dice",
            "status": "tie_break_running",
            "state_version": 7,
            "game_state": {"tie_break_leaders": [1, 2], "tie_break_round": 1},
        }
        updated = {**table, "state_version": 8}

        async def fetchrow(query, *args):
            if "FROM casino_v2_tables" in query:
                return table
            if "casino_v2_lifecycle_idempotency" in query:
                return None
            if "SET status='tie_break_running'" in query:
                where_clause = query.split("WHERE", 1)[-1]
                if "tie_break_running" not in where_clause:
                    return None
                return updated
            return None

        conn = SimpleNamespace(
            execute=AsyncMock(),
            fetch=AsyncMock(return_value=[{"seat_no": 1}, {"seat_no": 2}]),
            fetchrow=AsyncMock(side_effect=fetchrow),
        )
        body = V2TableCommitOutcomeRequest(
            expected_state_version=7,
            outcome_kind="tie_break",
            winner_seat_nos=[1, 2],
            idempotency_key="second-tie",
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino,
            "_v2_table_response_with_conn",
            new=AsyncMock(return_value={"table_id": "web-reroll", "status": "tie_break_running", "state_version": 8}),
        ), patch.object(
            internal_casino,
            "_record_v2_idempotency_with_conn",
            new=AsyncMock(side_effect=lambda _conn, _table, _op, _body, response: response),
        ):
            result = await commit_v2_table_outcome_with_conn(conn, "web-reroll", body)
        self.assertTrue(result["tie_break"])
        self.assertEqual(result["table"]["status"], "tie_break_running")
        where_clause = conn.fetchrow.await_args_list[-1].args[0].split("WHERE", 1)[-1]
        self.assertIn("tie_break_running", where_clause)


class V2WebBaccaratCreateTests(unittest.TestCase):
    def test_create_body_accepts_baccara(self):
        body = V2WebCreateBody(game_type="baccara", stake_rub=Decimal("50.00"), max_seats=4)
        self.assertEqual(body.game_type, "baccara")
        self.assertIn("baccara", WEB_V2_GAME_TYPES)
        self.assertTrue(is_web_card_table("baccara"))

    def test_create_body_rejects_cub(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            V2WebCreateBody(game_type="cub", stake_rub=Decimal("50.00"), max_seats=2)

    def test_baccarat_draw_choice_exposes_flags(self):
        row = {
            "table_id": "web-ba",
            "game_type": "baccara",
            "creator_id": 940001,
            "stake_rub": Decimal("100.00"),
            "max_seats": 3,
            "status": "running",
            "state_version": 5,
            "game_state": {
                "phase": "draw_choice",
                "tie_break_seat_nos": [1, 2],
                "draw_choice_deadline_at": "2099-01-01T00:00:00+00:00",
                "scores": {"1": 8, "2": 8, "3": 3},
                "hands": {"1": ["A♣", "7♦"], "2": ["A♠", "7♥"], "3": ["2♣", "A♥"]},
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 940001},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 1"}},
            {"seat_no": 3, "participant_kind": "bot", "bot": {"display_name": "PvP Robot 2"}},
        ]
        view = public_table_view(row, roster, viewer_id=940001)
        self.assertTrue(view["can_choose_draw"])
        self.assertFalse(view["can_roll"])
        self.assertEqual(view["roster"][0]["score"], 8)


class V2WebPasswordClientTests(unittest.IsolatedAsyncioTestCase):
    def test_public_view_marks_negative_web_id_as_you(self):
        row = {
            "table_id": "web-bj",
            "game_type": "blackjack",
            "creator_id": -7,
            "stake_rub": Decimal("100.00"),
            "max_seats": 4,
            "status": "open",
            "state_version": 0,
            "game_state": {"bot_count": 0, "draw_policy": "tie_split", "rounds": 1},
        }
        roster = [{"seat_no": 1, "participant_kind": "player", "telegram_id": -7}]
        view = public_table_view(row, roster, viewer_id=-7)
        self.assertTrue(view["roster"][0]["is_you"])
        self.assertTrue(view["is_seated"])
        self.assertTrue(view["is_creator"])
        self.assertTrue(view["can_cancel"])
        self.assertEqual(view["roster"][0]["actor"]["user_id"], -7)

    def test_roster_counts_negative_web_id_as_human(self):
        self.assertTrue(_roster_has_human([{"participant_kind": "player", "telegram_id": -7}]))
        self.assertFalse(_roster_has_human([{"participant_kind": "bot"}]))
        self.assertFalse(_roster_has_human([{"participant_kind": "player", "telegram_id": 0}]))

    async def test_create_web_blackjack_accepts_password_client_id(self):
        conn = AsyncMock()
        body = V2WebCreateBody(
            game_type="blackjack",
            stake_rub=Decimal("100.00"),
            max_seats=4,
            bot_count=0,
            autojoin=False,
        )
        view = {
            "table_id": "web-abc",
            "status": "open",
            "game_type": "blackjack",
            "is_seated": True,
        }
        with patch("casino_v2_web.ensure_closer"), patch(
            "casino_v2_web.load_public_table", new=AsyncMock(return_value=view)
        ), patch(
            "routers.internal_casino.create_v2_table_with_conn",
            new=AsyncMock(return_value={"success": True, "auto_started": False}),
        ) as created, patch(
            "casino_open_alerts.enqueue_open_table_alerts", new=AsyncMock(return_value=0)
        ):
            result = await create_web_table(conn, body, viewer_id=-7)
        self.assertTrue(result["created"])
        request = created.await_args.args[1]
        self.assertEqual(request.creator_id, -7)
        self.assertEqual(request.game_type, "blackjack")
        self.assertEqual(request.max_players, 4)

    async def test_baccarat_first_tick_deals_hands_without_settling(self):
        from casino_v2_web import ensure_blackjack_round

        row = {
            "table_id": "web-ba-stuck",
            "id": 11,
            "game_type": "baccara",
            "status": "running",
            "state_version": 4,
            "game_state": {},
            "creator_id": -7,
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": -7},
            {"seat_no": 2, "participant_kind": "bot"},
            {"seat_no": 3, "participant_kind": "bot"},
            {"seat_no": 4, "participant_kind": "bot"},
        ]
        persisted: dict[str, object] = {}

        async def persist(_conn, _table_id, version, patch, operation):
            persisted["patch"] = patch
            persisted["operation"] = operation
            row["game_state"] = patch
            row["state_version"] = version + 1
            return dict(row)

        settle = AsyncMock()
        with patch("casino_v2_web._reload_row", new=AsyncMock(return_value=row)), patch(
            "routers.internal_casino._v2_table_response_with_conn",
            new=AsyncMock(return_value={"roster": roster}),
        ), patch("casino_v2_web._persist_patch", new=persist), patch(
            "casino_v2_web._settle_blackjack_outcome", new=settle
        ), patch(
            "casino_v2_cards.deal_v2_card_hands",
            return_value={
                1: ["9♠", "K♦"],
                2: ["A♥", "2♣"],
                3: ["3♣", "4♦"],
                4: ["5♥", "6♠"],
            },
        ):
            await ensure_blackjack_round(AsyncMock(), "web-ba-stuck")
        settle.assert_not_called()
        self.assertEqual(persisted["operation"], "card-deal")
        dealt = persisted["patch"]
        assert isinstance(dealt, dict)
        self.assertEqual(dealt["hands"]["1"], ["9♠", "K♦"])
        self.assertEqual(dealt["phase"], "scoring")
        self.assertTrue(dealt.get("cards_dealt_at"))

    async def test_baccarat_tie_after_reveal_redeals_instead_of_split(self):
        from casino_v2_web import ensure_blackjack_round

        dealt_at = "2026-09-02T05:59:41+00:00"
        row = {
            "table_id": "6a60784d-896d-4542-9717-04d1141e8f68",
            "id": 12,
            "game_type": "baccara",
            "status": "running",
            "state_version": 8,
            "game_state": {
                "phase": "scoring",
                "hands": {"1": ["A♣", "A♠", "3♠"], "2": ["Q♥", "J♥", "5♥"]},
                "scores": {"1": 5, "2": 5},
                "cards_dealt_at": dealt_at,
                "draw_policy": "choose",
            },
            "creator_id": 3,
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 3},
            {"seat_no": 2, "participant_kind": "bot"},
        ]
        persisted: dict[str, object] = {}

        async def persist(_conn, _table_id, version, patch, operation):
            persisted["patch"] = patch
            persisted["operation"] = operation
            row["game_state"] = {**row["game_state"], **patch}
            row["state_version"] = version + 1
            return dict(row)

        settle = AsyncMock()
        with patch("casino_v2_web._reload_row", new=AsyncMock(return_value=row)), patch(
            "routers.internal_casino._v2_table_response_with_conn",
            new=AsyncMock(return_value={"roster": roster}),
        ), patch("casino_v2_web._persist_patch", new=persist), patch(
            "casino_v2_web._settle_blackjack_outcome", new=settle
        ), patch(
            "casino_v2_cards.deal_v2_card_hands",
            return_value={1: ["9♠", "K♦"], 2: ["A♥", "2♣"]},
        ):
            await ensure_blackjack_round(
                AsyncMock(),
                "6a60784d-896d-4542-9717-04d1141e8f68",
                now=datetime(2026, 9, 2, 6, 0, 10, tzinfo=timezone.utc),
            )
        settle.assert_not_called()
        self.assertEqual(persisted["operation"], "card-redeal")
        saved = persisted["patch"]
        assert isinstance(saved, dict)
        self.assertEqual(saved["hands"]["1"], ["9♠", "K♦"])
        self.assertEqual(saved["hands"]["2"], ["A♥", "2♣"])
        self.assertEqual(saved["draw_policy"], "tie_break")
        self.assertIn("Переброс лидеров", str(saved.get("board_note") or ""))
        self.assertNotEqual(saved.get("cards_dealt_at"), dealt_at)

    async def test_baccarat_draw_choice_timeout_redeals_not_split(self):
        from casino_v2_web import ensure_blackjack_round

        row = {
            "table_id": "web-ba-timeout",
            "id": 13,
            "game_type": "baccara",
            "status": "running",
            "state_version": 9,
            "game_state": {
                "phase": "draw_choice",
                "hands": {"1": ["A♣", "A♠", "3♠"], "2": ["Q♥", "J♥", "5♥"]},
                "scores": {"1": 5, "2": 5},
                "tie_break_seat_nos": [1, 2],
                "draw_choice_deadline_at": "2026-09-02T06:00:00+00:00",
                "draw_policy": "choose",
            },
            "creator_id": 3,
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 3},
            {"seat_no": 2, "participant_kind": "bot"},
        ]
        persisted: dict[str, object] = {}

        async def persist(_conn, _table_id, version, patch, operation):
            persisted["operation"] = operation
            persisted["patch"] = patch
            row["game_state"] = {**row["game_state"], **patch}
            row["state_version"] = version + 1
            return dict(row)

        settle = AsyncMock()
        with patch("casino_v2_web._reload_row", new=AsyncMock(return_value=row)), patch(
            "routers.internal_casino._v2_table_response_with_conn",
            new=AsyncMock(return_value={"roster": roster}),
        ), patch("casino_v2_web._persist_patch", new=persist), patch(
            "casino_v2_web._settle_blackjack_outcome", new=settle
        ), patch(
            "casino_v2_cards.deal_v2_card_hands",
            return_value={1: ["7♠", "K♣"], 2: ["9♥", "K♦"]},
        ):
            await ensure_blackjack_round(
                AsyncMock(),
                "web-ba-timeout",
                now=datetime(2026, 9, 2, 6, 1, 0, tzinfo=timezone.utc),
            )
        settle.assert_not_called()
        self.assertEqual(persisted["operation"], "card-redeal")


class V2StalePlayTests(unittest.TestCase):
    def test_deadline_and_retired_sport_are_stale(self):
        now = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
        live = {
            "status": "running",
            "game_type": "baccara",
            "started_at": "2026-09-01T07:50:00+00:00",
            "game_state": {"draw_choice_deadline_at": "2026-09-01T12:00:00+00:00"},
        }
        stuck = {
            "status": "tie_break_running",
            "game_type": "baccara",
            "started_at": "2026-09-01T07:50:00+00:00",
            "game_state": {"draw_choice_deadline_at": "2026-08-31T21:00:00+00:00"},
        }
        leftover = {
            "status": "tie_break_running",
            "game_type": "baccara",
            "started_at": "2026-09-01T07:00:00+00:00",
            "game_state": {"draw_choice_deadline_at": "2026-08-31T21:00:00+00:00"},
        }
        sport = {"status": "running", "game_type": "pvp_basketball", "game_state": {}}
        lobby = {"status": "open", "game_type": "pvp_basketball", "game_state": {}}
        self.assertFalse(v2_play_is_stale(live, now=now))
        self.assertFalse(v2_play_is_stale(stuck, now=now))
        self.assertTrue(v2_play_is_stale(leftover, now=now))
        self.assertTrue(v2_play_is_stale(sport, now=now))
        self.assertFalse(v2_play_is_stale(lobby, now=now))

    def test_hitting_blackjack_past_roll_deadline_is_not_stale(self):
        now = datetime(2026, 9, 11, 20, 28, tzinfo=timezone.utc)
        hitting = {
            "status": "running",
            "game_type": "blackjack",
            "started_at": "2026-09-11T20:27:00+00:00",
            "game_chat_id": -1004058942735,
            "game_state": {
                "phase": "hitting",
                "roll_deadline_at": "2026-09-11T20:27:30+00:00",
                "play_chats": [{"chat_id": -1004058942735, "card_msg_id": 1}],
            },
        }
        self.assertFalse(v2_play_is_stale(hitting, now=now))
        leftover = dict(hitting)
        leftover["started_at"] = "2026-09-11T19:50:00+00:00"
        leftover["created_at"] = "2026-09-11T19:50:00+00:00"
        self.assertTrue(v2_play_is_stale(leftover, now=now))

    def test_telegram_blackjack_hit_timeout_is_three_minutes(self):
        self.assertEqual(WEB_V2_TELEGRAM_HIT_TIMEOUT_SECONDS, 180)
        self.assertEqual(WEB_V2_ROLL_TIMEOUT_SECONDS, 30)
        group = {
            "game_chat_id": -100123,
            "game_state": {"play_chats": [{"chat_id": -100123}]},
        }
        web = {"game_chat_id": None, "game_state": {}}
        dm = {
            "game_chat_id": 1245341695,
            "game_state": {
                "listing_chat_id": -1004058942735,
                "play_chats": [{"chat_id": 1245341695}],
            },
        }
        self.assertEqual(blackjack_hit_timeout_seconds(group), 180)
        self.assertEqual(blackjack_hit_timeout_seconds(web), 30)
        self.assertEqual(blackjack_hit_timeout_seconds(dm), 30)

    def test_telegram_dice_ignores_web_roll_deadline(self):
        now = datetime(2026, 9, 2, 11, 40, tzinfo=timezone.utc)
        group = {
            "status": "running",
            "game_type": "pvp_dice",
            "game_chat_id": -100123,
            "updated_at": "2026-09-02T10:40:00+00:00",
            "started_at": "2026-09-02T11:19:00+00:00",
            "game_state": {
                "play_chats": [{"chat_id": -100123, "card_msg_id": 71}],
                "roll_deadline_at": "2026-09-02T11:00:00+00:00",
            },
        }
        self.assertTrue(telegram_play_surface(group))
        self.assertFalse(v2_play_is_stale(group, now=now))
        idle = dict(group)
        idle["started_at"] = "2026-09-02T10:40:00+00:00"
        idle["updated_at"] = "2026-09-02T11:19:00+00:00"
        self.assertTrue(v2_play_is_stale(idle, now=now))
        self.assertGreaterEqual(TELEGRAM_STALE_IDLE_SECONDS, 30 * 60)

    def test_telegram_dice_stale_ignores_fresh_updated_at(self):
        now = datetime(2026, 9, 2, 11, 40, tzinfo=timezone.utc)
        group = {
            "status": "running",
            "game_type": "pvp_dice",
            "game_chat_id": -100123,
            "started_at": "2026-09-02T10:40:00+00:00",
            "created_at": "2026-09-02T10:40:00+00:00",
            "updated_at": "2026-09-02T11:19:50+00:00",
            "game_state": {"play_chats": [{"chat_id": -100123, "card_msg_id": 71}]},
        }
        self.assertTrue(v2_play_is_stale(group, now=now))

    def test_listing_only_is_not_telegram_group_surface(self):
        dm = {
            "game_chat_id": 1245341695,
            "game_state": {
                "listing_chat_id": -1004058942735,
                "chat_id": 1245341695,
                "play_chats": [{"chat_id": 1245341695, "card_msg_id": 4747}],
            },
        }
        self.assertFalse(telegram_play_surface(dm))
        group = {
            "game_chat_id": -1004058942735,
            "game_state": {
                "listing_chat_id": -1004058942735,
                "play_chats": [{"chat_id": -1004058942735, "card_msg_id": 8470}],
            },
        }
        self.assertTrue(telegram_play_surface(group))

    def test_web_turn_deadline_does_not_race_autofill_with_refund(self):
        now = datetime(2026, 9, 2, 11, 0, 30, tzinfo=timezone.utc)
        for key in ("roll_deadline_at", "draw_choice_deadline_at"):
            with self.subTest(key=key):
                table = {"status": "running", "game_type": "pvp_dice",
                         "started_at": datetime(2026, 9, 2, 11, 0, tzinfo=timezone.utc),
                         "game_state": {key: now.isoformat()}}
                self.assertFalse(v2_play_is_stale(table, now=now))

    def test_web_dice_stale_only_after_recovery_window(self):
        now = datetime(2026, 9, 2, 11, 40, tzinfo=timezone.utc)
        web = {
            "status": "running",
            "game_type": "pvp_dice",
            "game_chat_id": None,
            "game_state": {"roll_deadline_at": "2026-09-02T11:00:00+00:00"},
        }
        self.assertFalse(telegram_play_surface(web))
        self.assertTrue(v2_play_is_stale(web, now=now))


class V2BlackjackCloserTests(unittest.IsolatedAsyncioTestCase):
    async def test_expire_stale_skips_hitting_blackjack(self):
        table = {
            "id": 91,
            "table_id": "1ce5f178-87c1-4baa-bd56-ea6307e66f25",
            "status": "running",
            "game_type": "blackjack",
            "started_at": datetime(2026, 9, 11, 20, 27, tzinfo=timezone.utc),
            "game_state": {
                "phase": "hitting",
                "roll_deadline_at": "2026-09-11T20:27:30+00:00",
            },
        }
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[table])
        expire_table = AsyncMock()
        with patch("routers.internal_casino._expire_stale_v2_play_table", new=expire_table):
            closed = await internal_casino.expire_stale_v2_play_with_conn(
                conn, now=datetime(2026, 9, 11, 20, 28, tzinfo=timezone.utc)
            )
        self.assertEqual(closed, 0)
        expire_table.assert_not_awaited()

    async def test_hitting_deadline_auto_stands_and_settles(self):
        from casino_v2_web import ensure_blackjack_round

        clock = datetime(2026, 9, 11, 20, 28, tzinfo=timezone.utc)
        row = {
            "table_id": "1ce5f178-87c1-4baa-bd56-ea6307e66f25",
            "id": 91,
            "game_type": "blackjack",
            "status": "running",
            "state_version": 9,
            "game_chat_id": -1004058942735,
            "started_at": datetime(2026, 9, 11, 20, 27, tzinfo=timezone.utc),
            "game_state": {
                "phase": "hitting",
                "hands": {"1": ["7♦", "A♠"], "2": ["J♥", "7♦"]},
                "scores": {"1": 18, "2": 17},
                "stood_seats": [],
                "cards_dealt_at": "2026-09-11T20:27:00+00:00",
                "roll_deadline_at": "2026-09-11T20:27:30+00:00",
                "play_chats": [{"chat_id": -1004058942735, "card_msg_id": 1}],
                "hmac": {"seed": "ab" * 32},
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
        ]
        persisted: list[str] = []

        async def persist(_conn, _table_id, version, patch, operation):
            persisted.append(operation)
            state = dict(row["game_state"])
            state.update(patch)
            row["game_state"] = state
            row["state_version"] = version + 1
            return dict(row)

        settle = AsyncMock()
        with patch("casino_v2_web._reload_row", new=AsyncMock(return_value=row)), patch(
            "routers.internal_casino._v2_table_response_with_conn",
            new=AsyncMock(return_value={"roster": roster}),
        ), patch("casino_v2_web._persist_patch", new=persist), patch(
            "casino_v2_web._settle_blackjack_outcome", new=settle
        ):
            await ensure_blackjack_round(AsyncMock(), row["table_id"], now=clock)
        self.assertIn("bj-auto-stand", persisted)
        settle.assert_awaited()
        self.assertEqual(settle.await_args.kwargs["kind"], "winner")
        self.assertEqual(settle.await_args.kwargs["winners"], [1])

    async def test_telegram_group_hitting_deadline_is_180s(self):
        from casino_v2_web import ensure_blackjack_round

        clock = datetime(2026, 9, 11, 20, 27, tzinfo=timezone.utc)
        row = {
            "table_id": "24e620b5-e340-449f-8a31-0cfa62eb7ac9",
            "id": 92,
            "game_type": "blackjack",
            "status": "running",
            "state_version": 5,
            "game_chat_id": -100123,
            "started_at": datetime(2026, 9, 11, 20, 26, tzinfo=timezone.utc),
            "game_state": {
                "phase": "scoring",
                "hands": {"1": ["7♥", "9♣"], "2": ["6♣", "A♦"]},
                "scores": {"1": 16, "2": 17},
                "stood_seats": [],
                "cards_dealt_at": "2026-09-11T20:26:00+00:00",
                "play_chats": [{"chat_id": -100123, "card_msg_id": 9}],
                "hmac": {"seed": "cd" * 32},
            },
        }
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 22},
        ]
        persisted: dict[str, object] = {}

        async def persist(_conn, _table_id, version, patch, operation):
            persisted["patch"] = patch
            persisted["operation"] = operation
            row["game_state"] = {**row["game_state"], **patch}
            row["state_version"] = version + 1
            return dict(row)

        with patch("casino_v2_web._reload_row", new=AsyncMock(return_value=row)), patch(
            "routers.internal_casino._v2_table_response_with_conn",
            new=AsyncMock(return_value={"roster": roster}),
        ), patch("casino_v2_web._persist_patch", new=persist), patch(
            "casino_v2_web._settle_blackjack_outcome", new=AsyncMock()
        ):
            await ensure_blackjack_round(AsyncMock(), row["table_id"], now=clock)
        self.assertEqual(persisted["operation"], "bj-hitting")
        body = persisted["patch"]
        assert isinstance(body, dict)
        due = datetime.fromisoformat(str(body["roll_deadline_at"]))
        self.assertEqual((due - clock).total_seconds(), 180)


class TelegramHouseFillTests(unittest.IsolatedAsyncioTestCase):
    async def test_house_fill_skips_telegram_group_dice(self):
        row = {
            "status": "running",
            "game_type": "pvp_dice",
            "game_chat_id": -100123,
            "state_version": 4,
            "game_state": {
                "play_chats": [{"chat_id": -100123, "card_msg_id": 71}],
                "roll_deadline_at": "2026-01-01T00:00:00+00:00",
                "hmac": {"seed": "ab" * 32},
            },
        }
        conn = AsyncMock()
        with patch("casino_v2_web._reload_row", new=AsyncMock(return_value=row)), patch(
            "casino_v2_web.ensure_round_ready", new=AsyncMock()
        ) as ready, patch("casino_v2_web.fill_hmac_rolls") as fill, patch(
            "casino_v2_web.maybe_score", new=AsyncMock()
        ) as score:
            await house_fill_table(conn, "5fdf15b4-154e-484f-b826-19dfb0a4b2bd", now=datetime(2026, 9, 2, tzinfo=timezone.utc))
        ready.assert_not_awaited()
        fill.assert_not_called()
        score.assert_not_awaited()

    async def test_house_fill_web_dice_still_fills_after_deadline(self):
        row = {
            "status": "running",
            "game_type": "pvp_dice",
            "game_chat_id": None,
            "state_version": 4,
            "game_state": {
                "roll_deadline_at": "2026-01-01T00:00:00+00:00",
                "hmac": {"seed": "ab" * 32},
                "rolls": {},
            },
        }
        filled_state = {**row["game_state"], "rolls": {"s1r0": 6}, "phase": "scoring"}
        conn = AsyncMock()
        reload = AsyncMock(return_value=row)
        persist = AsyncMock(return_value={"state_version": 5, "game_state": filled_state, "roster": []})
        with patch("casino_v2_web._reload_row", new=reload), patch(
            "casino_v2_web.ensure_round_ready", new=AsyncMock()
        ), patch("casino_v2_web.fill_hmac_rolls", return_value=filled_state) as fill, patch(
            "casino_v2_web._persist_patch", new=persist
        ), patch("casino_v2_web.maybe_score", new=AsyncMock()) as score, patch(
            "routers.internal_casino._v2_table_response_with_conn",
            new=AsyncMock(return_value={"roster": [{"seat_no": 1, "participant_kind": "player", "telegram_id": 11}]}),
        ):
            await house_fill_table(conn, "web-dice", now=datetime(2026, 9, 2, tzinfo=timezone.utc))
        fill.assert_called()
        persist.assert_awaited()
        score.assert_awaited()

    async def test_house_fill_dm_listing_empty_deadline_fills(self):
        row = {
            "status": "running",
            "game_type": "pvp_dice",
            "game_chat_id": 1245341695,
            "started_at": datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc),
            "state_version": 4,
            "game_state": {
                "listing_chat_id": -1004058942735,
                "play_chats": [{"chat_id": 1245341695, "card_msg_id": 4747}],
                "roll_deadline_at": None,
                "hmac": {"seed": "ab" * 32},
                "rolls": {"s2r0": 3},
            },
        }
        filled_state = {**row["game_state"], "rolls": {"s1r0": 4, "s2r0": 3}, "phase": "scoring"}
        conn = AsyncMock()
        reload = AsyncMock(return_value=row)
        persist = AsyncMock(return_value={"state_version": 5, "game_state": filled_state, "roster": []})
        with patch("casino_v2_web._reload_row", new=reload), patch(
            "casino_v2_web.ensure_round_ready", new=AsyncMock()
        ), patch("casino_v2_web.fill_hmac_rolls", return_value=filled_state) as fill, patch(
            "casino_v2_web._persist_patch", new=persist
        ), patch("casino_v2_web.maybe_score", new=AsyncMock()) as score, patch(
            "routers.internal_casino._v2_table_response_with_conn",
            new=AsyncMock(return_value={"roster": [
                {"seat_no": 1, "participant_kind": "player", "telegram_id": 11},
                {"seat_no": 2, "participant_kind": "bot"},
            ]}),
        ):
            await house_fill_table(conn, "dm-listed", now=datetime(2026, 9, 2, 1, 0, tzinfo=timezone.utc))
        fill.assert_called()
        persist.assert_awaited()
        score.assert_awaited()


class HouseWebClosedTests(unittest.TestCase):
    def test_play_and_house_table_create_reject_head_to_head_house(self):
        from pathlib import Path

        user = Path(__file__).resolve().parents[1].joinpath("routers", "user_casino.py").read_text(encoding="utf-8")
        play = user.split("async def play_house_round", 1)[1].split("async def ", 1)[0]
        create = user.split("async def create_house_table", 1)[1].split("async def ", 1)[0]
        self.assertIn("стол с игроками", play)
        self.assertIn("cub", play)
        self.assertIn("baccara", play)
        self.assertIn("blackjack", play)
        self.assertIn("Стол против казино закрыт", create)
        internal_paths = {getattr(route, "path", None) for route in internal_casino.router.routes}
        self.assertIn("/v2/tables/{table_id}/bots", internal_paths)
        self.assertIn("/rooms", internal_paths)
        self.assertIn("/rooms/{room_id}", internal_paths)
        self.assertIn("/rooms/{room_id}/join", internal_paths)
        self.assertIn("/rooms/{room_id}/leave", internal_paths)
        self.assertIn("/rooms/{room_id}/cancel", internal_paths)
        self.assertIn("/rooms/{room_id}/bots", internal_paths)


if __name__ == "__main__":
    unittest.main()
