"""PvP dice join deadline, HMAC rolls, house fill."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from casino_duels import build_duel_room
from casino_finance import canonical_casino_settings
from casino_pvp_dice import (
    EVENT_ROLL_PROMPT,
    EVENT_ROLL_PROMPT_GROUP,
    HMAC_DATA_KEY,
    PVP_DICE_ROLL_TIMEOUT_SECONDS,
    activate_on_join,
    dice_rolls,
    enqueue_roll_prompts,
    hmac_pip,
    house_fill_game,
    merge_join_state,
    merge_persisted_game_state,
    outcome_from_rolls,
    parse_deadline,
    prompt_text,
    record_roll,
    rolls_needed,
    room_roll_fields,
    seat_for_player,
)


def _settings():
    return canonical_casino_settings(
        [
            {"key": "enabled_games", "value": {"pvp_dice": True}},
            {"key": "min_bet_rub", "value": {"amount": 10}},
            {"key": "max_bet_rub", "value": {"amount": 100000}},
            {"key": "commission_rate_wagering_complete", "value": {"percent": 5}},
        ]
    )


class PvpDiceModelTests(unittest.TestCase):
    def test_hmac_pip_is_stable_one_to_six(self):
        first = hmac_pip("abc", game_id="g1", seat="creator", index=0, kind="player")
        second = hmac_pip("abc", game_id="g1", seat="creator", index=0, kind="player")
        house = hmac_pip("abc", game_id="g1", seat="creator", index=0, kind="house")
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 1)
        self.assertLessEqual(first, 6)
        self.assertGreaterEqual(house, 1)
        self.assertLessEqual(house, 6)

    def test_rolls_needed_defaults_to_one(self):
        self.assertEqual(rolls_needed({"game_data": {}}), 1)
        self.assertEqual(rolls_needed({"game_data": {"pvp": {"rounds": 2}}}), 2)

    def test_join_state_sets_deadline_without_wiping_rolls(self):
        deadline = datetime(2026, 8, 29, 12, 0, 30, tzinfo=timezone.utc)
        merged = merge_join_state(
            {"chat_id": -100, "creator_rolls": [4], "creator_name": "Ann"},
            deadline_at=deadline,
        )
        self.assertEqual(merged["creator_rolls"], [4])
        self.assertEqual(merged["opponent_rolls"], [])
        self.assertEqual(merged["roll_deadline_at"], deadline.isoformat())
        self.assertEqual(merged["chat_id"], -100)

    def test_persist_merge_keeps_longer_hmac_rolls_and_deadline(self):
        existing = {
            "creator_rolls": [6],
            "opponent_rolls": [2],
            "roll_deadline_at": "2026-08-29T12:00:30+00:00",
            "house_rolled": {"opponent": [0]},
        }
        incoming = {
            "chat_id": -100,
            "creator_rolls": [],
            "opponent_rolls": [],
            "roll_msg_id": 9,
        }
        merged = merge_persisted_game_state(existing, incoming)
        self.assertEqual(merged["creator_rolls"], [6])
        self.assertEqual(merged["opponent_rolls"], [2])
        self.assertEqual(merged["roll_deadline_at"], existing["roll_deadline_at"])
        self.assertEqual(merged["roll_msg_id"], 9)
        self.assertEqual(merged["house_rolled"]["opponent"], [0])

    def test_persist_merge_does_not_invent_rolls_on_unrelated_snapshot(self):
        self.assertEqual(merge_persisted_game_state({}, {"roll": 6}), {"roll": 6})

    def test_outcome_draw_and_winner(self):
        draw = outcome_from_rolls(
            creator_rolls=[3], opponent_rolls=[3], creator_id=1, opponent_id=2,
        )
        self.assertEqual(draw["kind"], "draw")
        win = outcome_from_rolls(
            creator_rolls=[6], opponent_rolls=[1], creator_id=1, opponent_id=2,
        )
        self.assertEqual(win["kind"], "winner")
        self.assertEqual(win["winner_id"], 1)

    def test_room_can_roll_only_for_participant_with_empty_seat(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        row = {
            "game_id": "d1",
            "game_type": "pvp_dice",
            "bet_rub": Decimal("50"),
            "created_at": started,
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "game_state": {
                "creator_rolls": [],
                "opponent_rolls": [],
                "roll_deadline_at": (started + timedelta(seconds=30)).isoformat(),
            },
            "game_data": {},
        }
        creator = room_roll_fields(row, viewer_id=10)
        other = room_roll_fields(row, viewer_id=99)
        waiting = room_roll_fields({**row, "opponent_id": None, "status": "waiting"}, viewer_id=10)
        self.assertTrue(creator["can_roll"])
        self.assertTrue(creator["house_will_roll"])
        self.assertEqual(creator["rolls_needed"], 1)
        self.assertFalse(other["can_roll"])
        self.assertFalse(waiting["can_roll"])
        self.assertEqual(waiting["roll_deadline_at"], None)

    def test_build_duel_room_exposes_roll_fields(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        room = build_duel_room(
            {
                "game_id": "d1",
                "game_type": "pvp_dice",
                "bet_rub": Decimal("50"),
                "created_at": started,
                "creator_id": 10,
                "opponent_id": 20,
                "status": "active",
                "game_state": {
                    "creator_rolls": [5],
                    "opponent_rolls": [],
                    "roll_deadline_at": (started + timedelta(seconds=30)).isoformat(),
                },
            },
            _settings(),
            viewer_id=20,
        )
        self.assertTrue(room["can_roll"])
        self.assertEqual(room["my_roll_count"], 0)
        self.assertEqual(room["rolls_needed"], 1)
        self.assertEqual(room["steps"][0]["value"], 5)
        self.assertNotIn("creator_id", room)

    def test_prompt_mentions_timeout(self):
        self.assertIn(str(PVP_DICE_ROLL_TIMEOUT_SECONDS), prompt_text())
        self.assertIn("Соперник зашёл", prompt_text())
        self.assertNotIn("Соперник зашёл", prompt_text(group=True))
        self.assertIn("этот чат", prompt_text(group=True))

    def test_parse_deadline_falls_back_to_started_at(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        deadline = parse_deadline({}, started)
        self.assertEqual(deadline, started + timedelta(seconds=30))

    def test_seat_for_player(self):
        game = {"creator_id": 1, "opponent_id": 2}
        self.assertEqual(seat_for_player(game, 1), "creator")
        self.assertEqual(seat_for_player(game, 2), "opponent")
        self.assertIsNone(seat_for_player(game, 3))

    def test_dice_rolls_drop_out_of_range(self):
        self.assertEqual(dice_rolls([1, 6, 0, 7, "x"]), [1, 6])


class PvpDiceHoldTouchTests(unittest.IsolatedAsyncioTestCase):
    async def test_activate_on_join_extends_active_holds(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        stored = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "state_version": 2,
            "game_state": {"chat_id": -100123, "creator_rolls": [], "opponent_rolls": []},
            "game_data": {"pvp": {"rounds": 1}},
            "started_at": started,
            "bet_rub": Decimal("50"),
            "creator_hold_id": "h1",
            "opponent_hold_id": "h2",
            "counterparty_kind": "player",
            "created_at": started,
            "outcome": None,
            "outcome_committed_at": None,
            "finished_at": None,
            "game_chat_id": -100123,
            "game_chat_binding_id": None,
            "game_chat_binding_revision": None,
        }
        conn = SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(return_value=stored))
        await activate_on_join(conn, stored)
        touch = conn.execute.await_args_list[0]
        self.assertIn("expires_at = now() + interval '2 hours'", str(touch.args[0]))
        self.assertEqual(touch.args[1], "g1")


class PvpDiceOutboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_prompts_group_only_when_bound_to_group(self):
        conn = SimpleNamespace(execute=AsyncMock())
        await enqueue_roll_prompts(
            conn, game_id="g1", creator_id=10, opponent_id=20, chat_id=-100123,
        )
        events = [call.args[2] for call in conn.execute.await_args_list]
        recipients = [call.args[4] for call in conn.execute.await_args_list]
        payloads = [json.loads(call.args[5]) for call in conn.execute.await_args_list]
        self.assertEqual(events, [EVENT_ROLL_PROMPT_GROUP])
        self.assertEqual(recipients, [10])
        self.assertEqual(payloads[0]["chat_id"], -100123)
        self.assertNotIn("Соперник зашёл", payloads[0]["text"])
        self.assertIn("этот чат", payloads[0]["text"])

    async def test_enqueue_prompts_dm_when_no_group(self):
        conn = SimpleNamespace(execute=AsyncMock())
        await enqueue_roll_prompts(
            conn, game_id="g1", creator_id=10, opponent_id=20, chat_id=None,
        )
        events = [call.args[2] for call in conn.execute.await_args_list]
        recipients = [call.args[4] for call in conn.execute.await_args_list]
        self.assertEqual(events, [EVENT_ROLL_PROMPT, EVENT_ROLL_PROMPT])
        self.assertEqual(recipients, [10, 20])
        self.assertIn("Соперник зашёл", json.loads(conn.execute.await_args_list[0].args[5])["text"])

    async def test_enqueue_skips_non_positive_recipient(self):
        conn = SimpleNamespace(execute=AsyncMock())
        await enqueue_roll_prompts(
            conn, game_id="g1", creator_id=-3, opponent_id=20, chat_id=None,
        )
        self.assertEqual(conn.execute.await_count, 1)
        self.assertEqual(conn.execute.await_args.args[4], 20)

    async def test_activate_on_join_writes_deadline_seed_and_outbox(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        stored = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "state_version": 2,
            "game_state": {"chat_id": -100123, "creator_rolls": [], "opponent_rolls": []},
            "game_data": {"pvp": {"rounds": 1}},
            "started_at": started,
            "bet_rub": Decimal("50"),
            "creator_hold_id": "h1",
            "opponent_hold_id": "h2",
            "counterparty_kind": "player",
            "created_at": started,
            "outcome": None,
            "outcome_committed_at": None,
            "finished_at": None,
            "game_chat_id": -100123,
            "game_chat_binding_id": None,
            "game_chat_binding_revision": None,
        }
        conn = SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(return_value=stored))
        latest = await activate_on_join(conn, stored)
        self.assertEqual(latest["game_id"], "g1")
        update = conn.fetchrow.await_args
        self.assertIn("pvp_dice_hmac", call_arg_contains_hmac(update))
        self.assertGreaterEqual(conn.execute.await_count, 2)

    async def test_house_fill_skips_before_deadline(self):
        started = datetime.now(timezone.utc)
        game = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "state_version": 3,
            "counterparty_kind": "player",
            "game_state": {
                "creator_rolls": [],
                "opponent_rolls": [],
                "roll_deadline_at": (started + timedelta(seconds=30)).isoformat(),
            },
            "game_data": {HMAC_DATA_KEY: {"seed": "aa" * 16, "commit": "c"}},
            "started_at": started,
        }
        conn = SimpleNamespace(fetchrow=AsyncMock(), execute=AsyncMock())
        after = await house_fill_game(conn, game, now=started + timedelta(seconds=5))
        conn.fetchrow.assert_not_awaited()
        self.assertEqual(after["state_version"], 3)

    async def test_web_roll_hmac_is_idempotent_when_seat_is_full(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        game = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "state_version": 5,
            "counterparty_kind": "player",
            "bet_rub": Decimal("50"),
            "creator_hold_id": "h1",
            "opponent_hold_id": "h2",
            "game_state": {
                "creator_rolls": [4],
                "opponent_rolls": [],
                "roll_deadline_at": (started + timedelta(seconds=30)).isoformat(),
            },
            "game_data": {HMAC_DATA_KEY: {"seed": "aa" * 16, "commit": "c"}},
            "started_at": started,
            "created_at": started,
            "outcome": None,
            "outcome_committed_at": None,
            "finished_at": None,
            "game_chat_id": None,
            "game_chat_binding_id": None,
            "game_chat_binding_revision": None,
        }
        conn = SimpleNamespace(fetchrow=AsyncMock(), execute=AsyncMock())
        with patch("routers.internal_casino.lock_casino_game", new=AsyncMock()), patch(
            "routers.internal_casino._game_for_update", new=AsyncMock(return_value=game)
        ), patch("casino_pvp_dice.maybe_finish_pvp_dice", new=AsyncMock(side_effect=lambda _c, g: dict(g))):
            result = await record_roll(conn, game_id="g1", telegram_id=10)
        self.assertTrue(result["idempotent"])
        conn.fetchrow.assert_not_awaited()

    async def test_web_roll_writes_hmac_pip(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        seed = "aa" * 16
        game = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "state_version": 3,
            "counterparty_kind": "player",
            "bet_rub": Decimal("50"),
            "creator_hold_id": "h1",
            "opponent_hold_id": "h2",
            "game_state": {
                "creator_rolls": [],
                "opponent_rolls": [],
                "roll_deadline_at": (started + timedelta(seconds=30)).isoformat(),
            },
            "game_data": {HMAC_DATA_KEY: {"seed": seed, "commit": "c"}},
            "started_at": started,
            "created_at": started,
            "outcome": None,
            "outcome_committed_at": None,
            "finished_at": None,
            "game_chat_id": None,
            "game_chat_binding_id": None,
            "game_chat_binding_revision": None,
        }
        pip = hmac_pip(seed, game_id="g1", seat="creator", index=0, kind="player")

        async def fetchrow(query, *args):
            state = json.loads(args[2])
            return {**game, "game_state": state, "state_version": 4}

        conn = SimpleNamespace(fetchrow=AsyncMock(side_effect=fetchrow), execute=AsyncMock())
        with patch("routers.internal_casino.lock_casino_game", new=AsyncMock()), patch(
            "routers.internal_casino._game_for_update", new=AsyncMock(return_value=game)
        ), patch("casino_pvp_dice.maybe_finish_pvp_dice", new=AsyncMock(side_effect=lambda _c, g: dict(g))):
            result = await record_roll(conn, game_id="g1", telegram_id=10)
        self.assertFalse(result["idempotent"])
        state = json.loads(conn.fetchrow.await_args.args[3])
        self.assertEqual(state["creator_rolls"], [pip])
        self.assertEqual(conn.execute.await_count, 3)
        self.assertIn("expires_at = now() + interval '2 hours'", str(conn.execute.await_args_list[0].args[0]))

    async def test_house_fill_after_deadline_writes_house_pips(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        seed = "aa" * 16
        game = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "state_version": 3,
            "counterparty_kind": "player",
            "bet_rub": Decimal("50"),
            "game_state": {
                "creator_rolls": [],
                "opponent_rolls": [],
                "roll_deadline_at": (started + timedelta(seconds=30)).isoformat(),
            },
            "game_data": {HMAC_DATA_KEY: {"seed": seed, "commit": "c"}},
            "started_at": started,
        }
        creator_pip = hmac_pip(seed, game_id="g1", seat="creator", index=0, kind="house")
        opponent_pip = hmac_pip(seed, game_id="g1", seat="opponent", index=0, kind="house")

        async def fetchrow(query, *args):
            state = json.loads(args[2])
            return {**game, "game_state": state, "state_version": 4}

        conn = SimpleNamespace(fetchrow=AsyncMock(side_effect=fetchrow), execute=AsyncMock())
        with patch("casino_pvp_dice.maybe_finish_pvp_dice", new=AsyncMock(side_effect=lambda _c, g: dict(g))):
            after = await house_fill_game(conn, game, now=started + timedelta(seconds=31))
        state = json.loads(conn.fetchrow.await_args.args[3])
        self.assertEqual(state["creator_rolls"], [creator_pip])
        self.assertEqual(state["opponent_rolls"], [opponent_pip])
        self.assertEqual(state["house_rolled"]["creator"], [0])
        self.assertEqual(state["house_rolled"]["opponent"], [0])
        self.assertEqual(after["state_version"], 4)

    async def test_both_seats_settled_after_second_roll(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        seed = "aa" * 16
        game = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "status": "active",
            "state_version": 4,
            "counterparty_kind": "player",
            "bet_rub": Decimal("50"),
            "creator_hold_id": "h1",
            "opponent_hold_id": "h2",
            "game_state": {
                "creator_rolls": [6],
                "opponent_rolls": [],
                "roll_deadline_at": (started + timedelta(seconds=30)).isoformat(),
            },
            "game_data": {HMAC_DATA_KEY: {"seed": seed, "commit": "c"}},
            "started_at": started,
            "created_at": started,
            "outcome": None,
            "outcome_committed_at": None,
            "finished_at": None,
            "game_chat_id": None,
            "game_chat_binding_id": None,
            "game_chat_binding_revision": None,
        }
        finished = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": 20,
            "stake_rub": "50.00",
            "status": "finished",
            "state_version": 6,
        }

        async def fetchrow(query, *args):
            state = json.loads(args[2])
            return {**game, "game_state": state, "state_version": 5}

        conn = SimpleNamespace(fetchrow=AsyncMock(side_effect=fetchrow), execute=AsyncMock())
        commit = AsyncMock(return_value={"game": {**game, "status": "outcome_committed", "state_version": 6}})
        settle = AsyncMock(return_value={"game": finished})
        with patch("routers.internal_casino.lock_casino_game", new=AsyncMock()), patch(
            "routers.internal_casino._game_for_update", new=AsyncMock(return_value=game)
        ), patch("routers.internal_casino.commit_game_outcome_with_conn", new=commit), patch(
            "routers.internal_casino.settle_committed_outcome_with_conn", new=settle
        ):
            result = await record_roll(conn, game_id="g1", telegram_id=20, value=1)
        self.assertFalse(result["idempotent"])
        commit.assert_awaited()
        settle.assert_awaited()
        self.assertEqual(result["game"]["status"], "finished")

    async def test_robot_activate_is_noop(self):
        game = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": None,
            "counterparty_kind": "pvp_robot",
            "status": "active",
            "game_state": {},
        }
        conn = SimpleNamespace(fetchrow=AsyncMock(), execute=AsyncMock())
        after = await activate_on_join(conn, game)
        conn.fetchrow.assert_not_awaited()
        self.assertEqual(after["counterparty_kind"], "pvp_robot")

    async def test_house_fill_skips_robot(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        game = {
            "game_id": "g1",
            "game_type": "pvp_dice",
            "creator_id": 10,
            "opponent_id": -1,
            "counterparty_kind": "pvp_robot",
            "status": "active",
            "state_version": 2,
            "game_state": {"creator_rolls": [], "opponent_rolls": []},
            "started_at": started,
        }
        conn = SimpleNamespace(fetchrow=AsyncMock(), execute=AsyncMock())
        after = await house_fill_game(conn, game, now=started + timedelta(seconds=60))
        conn.fetchrow.assert_not_awaited()
        self.assertEqual(after["state_version"], 2)


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class PvpDiceCloserIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_house_fill_due_continues_after_one_failure(self):
        from fastapi import HTTPException

        from casino_pvp_dice import house_fill_due

        expired = {"game_id": "expired-old"}
        live = {"game_id": "live-new"}
        conn = SimpleNamespace(
            fetch=AsyncMock(return_value=[expired, live]),
            fetchrow=AsyncMock(side_effect=[expired, live]),
            transaction=lambda: _Txn(),
        )

        async def fill(_conn, game, *, now=None):
            if game["game_id"] == "expired-old":
                raise HTTPException(status_code=409, detail="Hold casino-expired-old-creator has expired")
            return {**game, "status": "finished", "state_version": 9}

        recover = AsyncMock()
        with patch("casino_pvp_dice.house_fill_game", new=fill), patch(
            "casino_pvp_dice._recover_failed_fill", new=recover
        ):
            filled = await house_fill_due(conn)

        self.assertEqual(filled, 1)
        recover.assert_awaited()
        self.assertEqual(recover.await_args.args[1]["game_id"], "expired-old")

    def test_stale_hold_error_matches_expired_detail(self):
        from fastapi import HTTPException

        from casino_pvp_dice import _is_stale_hold_error

        self.assertTrue(_is_stale_hold_error(HTTPException(status_code=409, detail="Hold x has expired")))
        self.assertFalse(_is_stale_hold_error(RuntimeError("db down")))


def call_arg_contains_hmac(call) -> str:
    for arg in call.args:
        text = str(arg)
        if HMAC_DATA_KEY in text:
            return text
    return ""


if __name__ == "__main__":
    unittest.main()
