"""Shared roulette table: one HMAC pocket, each seat vs the house."""
from __future__ import annotations

import sys
import types
import unittest
from contextlib import ExitStack
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("Database dependency must be patched in unit tests")


sys.modules.setdefault("db", types.SimpleNamespace(get_pool=_dependency_stub))

from casino_cards import game_commit  # noqa: E402
from casino_finance import calculate_house_settlement  # noqa: E402
from casino_roulette import (  # noqa: E402
    pocket_color,
    resolve_roulette_round,
    roulette_pocket,
    verify_roulette_round,
)
from casino_roulette_table import (  # noqa: E402
    CLIENT_SEED,
    NONCE,
    RouletteTableConfig,
    _lock_and_settle,
    _normalize_table_chip,
    maybe_close_due,
    snapshot,
    place_bet,
    place_bets,
    publish,
    subscribe,
    unsubscribe,
)

SEED = "cd" * 32
ROUND_ID = "rt-shared-1"
COMMIT = game_commit(SEED, ROUND_ID)


def _cfg() -> RouletteTableConfig:
    return RouletteTableConfig(
        enabled=True,
        collect_seconds=25,
        max_players=24,
        min_bet=Decimal("10"),
        max_bet=Decimal("100000"),
    )


def _round(*, status="open", pocket=None):
    return {
        "id": 1,
        "round_id": ROUND_ID,
        "status": status,
        "commit_hash": COMMIT,
        "server_seed": SEED,
        "closes_at": None,
        "pocket": pocket,
        "created_at": None,
        "locked_at": None,
        "settled_at": None,
    }


class RouletteTableMathTests(unittest.TestCase):
    def test_one_round_id_draws_one_pocket(self):
        first = roulette_pocket(SEED, ROUND_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        second = roulette_pocket(SEED, ROUND_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 37)
        verified = verify_roulette_round(
            server_seed=SEED,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            game_id=ROUND_ID,
            commit=COMMIT,
            expected_pocket=first,
        )
        self.assertTrue(verified["matches"])
        self.assertEqual(verified["pocket"], first)

    def test_straight_chip_uses_straight_cap_not_table_max(self):
        cfg = RouletteTableConfig(
            enabled=True,
            collect_seconds=25,
            max_players=24,
            min_bet=Decimal("10"),
            max_bet=Decimal("500"),
            max_even_bet=Decimal("500"),
            max_straight_bet=Decimal("27.78"),
        )
        key, chip = _normalize_table_chip(Decimal("25"), "22", cfg)
        self.assertEqual(key, "22")
        self.assertEqual(chip, Decimal("25.00"))
        _normalize_table_chip(Decimal("100"), "red", cfg)
        with self.assertRaises(HTTPException) as raised:
            _normalize_table_chip(Decimal("100"), "15", cfg)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("27.78", str(raised.exception.detail))
        self.assertIn("₽", str(raised.exception.detail))
        with self.assertRaises(HTTPException) as raised_zero:
            _normalize_table_chip(Decimal("50"), "zero", cfg)
        self.assertIn("27.78", str(raised_zero.exception.detail))

    def test_red_and_seventeen_pay_independently_on_the_same_pocket(self):
        """17 is black: red loses, straight 17 wins 35:1. Same HMAC pocket, two settlements."""
        round_id = None
        for index in range(8000):
            candidate = f"rt-17-{index}"
            if roulette_pocket(SEED, candidate, client_seed=CLIENT_SEED, nonce=NONCE) == 17:
                round_id = candidate
                break
        self.assertIsNotNone(round_id)
        self.assertEqual(pocket_color(17), "black")
        red = resolve_roulette_round(
            seed=SEED,
            game_id=round_id,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            stake_rub=Decimal("100"),
            bet="red",
            commission_rate=Decimal("5"),
        )
        straight = resolve_roulette_round(
            seed=SEED,
            game_id=round_id,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            stake_rub=Decimal("10"),
            bet="17",
            commission_rate=Decimal("5"),
        )
        self.assertEqual(red["pocket"], 17)
        self.assertEqual(straight["pocket"], 17)
        self.assertFalse(red["won"])
        self.assertTrue(straight["won"])
        expected_17 = calculate_house_settlement(Decimal("10"), Decimal("36"), Decimal("5"))
        self.assertEqual(red["settlement"].payout, Decimal("0"))
        self.assertEqual(straight["settlement"].payout, expected_17.payout)
        self.assertEqual(straight["settlement"].payout, Decimal("342.50"))

    def test_even_money_commission_is_the_same_as_1x1(self):
        settlement = calculate_house_settlement(Decimal("100"), Decimal("2"), Decimal("5"))
        self.assertEqual(settlement.payout, Decimal("195.00"))
        self.assertEqual(settlement.commission, Decimal("5.00"))


class SettleConn:
    def __init__(self, bets, *, status="open"):
        self.bets = bets
        self.round = _round(status=status)
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)
        self.plays = []

    async def _execute(self, query, *args):
        q = " ".join(query.split())
        if "status = 'locked'" in q:
            self.round["status"] = "locked"
            self.round["pocket"] = args[1]
        elif "status = 'spinning'" in q:
            self.round["status"] = "spinning"
        elif "status = 'settled'" in q:
            self.round["status"] = "settled"
        return "UPDATE 1"

    async def _fetchrow(self, query, *args):
        if "FROM casino_roulette_rounds" in query:
            return dict(self.round)
        raise AssertionError(query)


def _bet(user_id, bet, stake, reserve, bet_id=1, notify_chat_id=None):
    return {
        "id": bet_id,
        "user_id": user_id,
        "bet": bet,
        "stake_rub": Decimal(stake),
        "hold_order_ref": f"hold-{user_id}-{bet}",
        "house_reserve_rub": Decimal(reserve),
        "display_name": str(user_id),
        "game_id": None,
        "notify_chat_id": notify_chat_id,
    }


class RouletteTableSettleTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_players_share_one_pocket_and_settle_apart(self):
        pocket = roulette_pocket(SEED, ROUND_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        events = []
        plays = []

        async def fake_play(conn, **kwargs):
            plays.append(kwargs)
            return {
                "bet": kwargs["bet"],
                "won": True,
                "payout_rub": "195.00" if kwargs["bet"] == "red" else "342.50",
            }

        conn = SettleConn(
            [
                _bet(11, "red", "100", "195.00", 1),
                _bet(22, "17", "10", "342.50", 2),
            ]
        )
        with (
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=conn.bets)),
            patch("casino_roulette_table._named_public", new=AsyncMock(return_value={"players": []})),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table.play_roulette_known_pocket_with_conn", new=fake_play),
            patch("casino_roulette_table.publish", side_effect=lambda payload: events.append(dict(payload))),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        self.assertEqual(len(plays), 2)
        self.assertEqual(plays[0]["pocket"], pocket)
        self.assertEqual(plays[1]["pocket"], pocket)
        self.assertEqual(plays[0]["hmac_game_id"], ROUND_ID)
        self.assertEqual(plays[1]["hmac_game_id"], ROUND_ID)
        self.assertEqual(plays[0]["bet"], "red")
        self.assertEqual(plays[1]["bet"], "17")
        self.assertEqual(plays[0]["hold_order_ref"], "hold-11-red")
        self.assertEqual(plays[0]["game_id"], f"{ROUND_ID}-b1")
        self.assertEqual(plays[1]["game_id"], f"{ROUND_ID}-b2")
        types = [event["type"] for event in events]
        self.assertEqual(types, ["lock", "spin", "settled"])
        # No sleep between spin and settled — the client must keep the wheel
        # going after `settled`, otherwise the round snaps instead of spinning.
        self.assertEqual(events[1]["pocket"], pocket)
        self.assertEqual(conn.round["status"], "settled")
        self.assertEqual(conn.round["pocket"], pocket)

    async def test_one_player_two_spots_settle_as_two_holds(self):
        plays = []

        async def fake_play(conn, **kwargs):
            plays.append(kwargs)
            return {
                "bet": kwargs["bet"],
                "won": kwargs["bet"] == "22",
                "payout_rub": "855.00" if kwargs["bet"] == "22" else "0.00",
            }

        conn = SettleConn(
            [
                _bet(11, "red", "50", "97.50", 4),
                _bet(11, "22", "25", "855.00", 5),
            ]
        )
        with (
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=conn.bets)),
            patch("casino_roulette_table._named_public", new=AsyncMock(return_value={"players": []})),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table.play_roulette_known_pocket_with_conn", new=fake_play),
            patch("casino_roulette_table.publish"),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        self.assertEqual(len(plays), 2)
        self.assertEqual(plays[0]["bet"], "red")
        self.assertEqual(plays[1]["bet"], "22")
        self.assertEqual(plays[0]["stake_rub"], Decimal("50"))
        self.assertEqual(plays[1]["stake_rub"], Decimal("25"))
        self.assertEqual(plays[0]["game_id"], f"{ROUND_ID}-b4")
        self.assertEqual(plays[1]["game_id"], f"{ROUND_ID}-b5")
        self.assertEqual(plays[0]["hmac_game_id"], ROUND_ID)

    async def test_empty_round_does_not_spin(self):
        events = []
        conn = SettleConn([])
        fake_play = AsyncMock()
        with (
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=[])),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table.play_roulette_known_pocket_with_conn", new=fake_play),
            patch("casino_roulette_table.publish", side_effect=lambda payload: events.append(dict(payload))),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        fake_play.assert_not_awaited()
        self.assertEqual([event["type"] for event in events], ["idle"])
        self.assertIsNone(conn.round["pocket"])

    async def test_spinning_round_resumes_and_opens_the_next(self):
        pocket = roulette_pocket(SEED, ROUND_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        events = []
        plays = []
        done = _bet(11, "red", "100", "195.00", 1)
        done["game_id"] = f"{ROUND_ID}-b1"
        leftover = _bet(22, "17", "10", "342.50", 2)

        async def fake_play(conn, **kwargs):
            plays.append(kwargs)
            return {"bet": kwargs["bet"], "won": True, "payout_rub": "342.50"}

        conn = SettleConn([done, leftover], status="spinning")
        conn.round["pocket"] = pocket
        with (
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=conn.bets)),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table.play_roulette_known_pocket_with_conn", new=fake_play),
            patch("casino_roulette_table.publish", side_effect=lambda payload: events.append(dict(payload))),
            patch("casino_roulette_table._enqueue_telegram_results", new=AsyncMock()),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        self.assertEqual([event["type"] for event in events], ["settled"])
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["bet"], "17")
        self.assertEqual(conn.round["status"], "settled")

    async def test_sse_subscribers_see_lock(self):
        queue = subscribe()
        try:
            pocket = roulette_pocket(SEED, ROUND_ID, client_seed=CLIENT_SEED, nonce=NONCE)
            conn = SettleConn([_bet(11, "red", "100", "195.00", 1)])
            with (
                patch("casino_roulette_table._bets", new=AsyncMock(return_value=conn.bets)),
                patch("casino_roulette_table._named_public", new=AsyncMock(return_value={"players": []})),
                patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
                patch(
                    "casino_roulette_table.play_roulette_known_pocket_with_conn",
                    new=AsyncMock(return_value={"bet": "red", "won": False, "payout_rub": "0.00"}),
                ),
            ):
                await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
            first = queue.get_nowait()
            self.assertEqual(first["type"], "lock")
            spin = queue.get_nowait()
            self.assertEqual(spin["type"], "spin")
            self.assertEqual(spin["pocket"], pocket)
        finally:
            unsubscribe(queue)


class RouletteTableBetTests(unittest.IsolatedAsyncioTestCase):
    def _place_patches(self, *, bets, seat=None):
        seat = seat or types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("97.50")),
            profile={"account_id": 8},
        )
        return (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_roulette_table.maybe_close_due", new=AsyncMock()),
            patch("casino_roulette_table.lock_casino_users", new=AsyncMock()),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=bets)),
            patch("casino_roulette_table.load_roulette_house_seat", new=AsyncMock(return_value=seat)),
            patch("casino_roulette_table._adjust_house_reserve", new=AsyncMock()),
            patch("casino_roulette_table.public_actors", new=AsyncMock(return_value={})),
            patch("casino_roulette_table.actor_chip", return_value={"display_name": "A", "initial": "A"}),
            patch(
                "casino_roulette_table._named_public",
                new=AsyncMock(return_value={"round_id": ROUND_ID, "players": []}),
            ),
            patch("casino_roulette_table.publish"),
        )

    def _enter_place(self, stack: ExitStack, *, bets, seat=None, release=None, reserve=None):
        for cm in self._place_patches(bets=bets, seat=seat):
            stack.enter_context(cm)
        if release is not None:
            stack.enter_context(patch("casino_roulette_table.release_unified_hold", new=release))
        if reserve is not None:
            stack.enter_context(patch("casino_roulette_table.reserve_unified_funds", new=reserve))

    async def test_second_spot_keeps_the_first_hold(self):
        conn = SettleConn([])
        release = AsyncMock()
        reserve = AsyncMock()
        bets = [_bet(11, "red", "50", "97.50", 3)]
        seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("855.00")),
            profile={"account_id": 8},
        )
        with ExitStack() as stack:
            self._enter_place(stack, bets=bets, seat=seat, release=release, reserve=reserve)
            await place_bet(conn, user_id=11, amount_rub=Decimal("25"), bet="22")
        release.assert_not_awaited()
        reserve.assert_awaited()
        self.assertEqual(reserve.await_args.kwargs["amount_rub"], Decimal("25"))
        inserted = [
            call for call in conn.execute.await_args_list if "INSERT INTO casino_roulette_bets" in call.args[0]
        ]
        self.assertTrue(inserted)
        self.assertEqual(inserted[0].args[3], "22")
        self.assertEqual(inserted[0].args[4], Decimal("25"))

    async def test_second_chip_on_the_same_spot_stacks(self):
        conn = SettleConn([])
        release = AsyncMock()
        reserve = AsyncMock()
        bets = [_bet(11, "red", "50", "97.50", 3)]
        seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("195.00")),
            profile={"account_id": 8},
        )
        with ExitStack() as stack:
            self._enter_place(stack, bets=bets, seat=seat, release=release, reserve=reserve)
            await place_bet(conn, user_id=11, amount_rub=Decimal("50"), bet="red")
        release.assert_awaited()
        self.assertEqual(release.await_args.kwargs["amount_rub"], Decimal("50"))
        reserve.assert_awaited()
        self.assertEqual(reserve.await_args.kwargs["amount_rub"], Decimal("100"))
        updated = [call for call in conn.execute.await_args_list if "UPDATE casino_roulette_bets" in call.args[0]]
        self.assertTrue(updated)
        self.assertEqual(updated[0].args[1], 3)
        self.assertEqual(updated[0].args[2], Decimal("100"))

    async def test_extra_chips_from_one_player_do_not_fill_the_table(self):
        cfg = RouletteTableConfig(
            enabled=True,
            collect_seconds=25,
            max_players=2,
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
        )
        conn = SettleConn([])
        bets = [
            _bet(11, "red", "50", "97.50", 1),
            _bet(11, "22", "25", "855.00", 2),
        ]
        seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("97.50")),
            profile={"account_id": 8},
        )
        settle = AsyncMock()
        with (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=cfg)),
            patch("casino_roulette_table.maybe_close_due", new=AsyncMock()),
            patch("casino_roulette_table.lock_casino_users", new=AsyncMock()),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch(
                "casino_roulette_table._bets",
                new=AsyncMock(side_effect=[bets, bets + [_bet(11, "black", "10", "19.50", 3)]]),
            ),
            patch("casino_roulette_table.load_roulette_house_seat", new=AsyncMock(return_value=seat)),
            patch("casino_roulette_table._adjust_house_reserve", new=AsyncMock()),
            patch("casino_roulette_table.release_unified_hold", new=AsyncMock()),
            patch("casino_roulette_table.reserve_unified_funds", new=AsyncMock()),
            patch("casino_roulette_table.public_actors", new=AsyncMock(return_value={})),
            patch("casino_roulette_table.actor_chip", return_value={"display_name": "A", "initial": "A"}),
            patch(
                "casino_roulette_table._named_public",
                new=AsyncMock(return_value={"round_id": ROUND_ID, "players": []}),
            ),
            patch("casino_roulette_table.publish"),
            patch("casino_roulette_table._lock_and_settle", new=settle),
        ):
            await place_bet(conn, user_id=11, amount_rub=Decimal("10"), bet="black")
        settle.assert_not_awaited()

    async def test_clear_one_spot_releases_only_that_hold(self):
        from casino_roulette_table import clear_bets

        conn = SettleConn([])
        conn.fetchrow = AsyncMock(side_effect=[_round(), _round()])
        release = AsyncMock()
        bets = [
            _bet(11, "red", "50", "97.50", 3),
            _bet(11, "22", "25", "855.00", 4),
        ]
        seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("97.50")),
            profile={"account_id": 8},
        )
        with (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_roulette_table.maybe_close_due", new=AsyncMock()),
            patch("casino_roulette_table.lock_casino_users", new=AsyncMock()),
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=bets)),
            patch("casino_roulette_table.load_roulette_house_seat", new=AsyncMock(return_value=seat)),
            patch("casino_roulette_table.release_unified_hold", new=release),
            patch("casino_roulette_table._adjust_house_reserve", new=AsyncMock()),
            patch(
                "casino_roulette_table._named_public",
                new=AsyncMock(return_value={"round_id": ROUND_ID, "players": []}),
            ),
            patch("casino_roulette_table.publish"),
        ):
            await clear_bets(conn, user_id=11, bet="red")
        release.assert_awaited_once()
        self.assertEqual(release.await_args.kwargs["amount_rub"], Decimal("50"))
        deleted = [call for call in conn.execute.await_args_list if "DELETE FROM casino_roulette_bets" in call.args[0]]
        self.assertEqual(len(deleted), 1)
        self.assertEqual(deleted[0].args[1], 3)

    async def test_bankroll_overflow_never_holds(self):
        conn = SettleConn([])
        reserve = AsyncMock()
        with (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_roulette_table.maybe_close_due", new=AsyncMock()),
            patch("casino_roulette_table.lock_casino_users", new=AsyncMock()),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=[])),
            patch(
                "casino_roulette_table.load_roulette_house_seat",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="House bankroll is insufficient")),
            ),
            patch("casino_roulette_table.reserve_unified_funds", new=reserve),
        ):
            with self.assertRaises(HTTPException) as raised:
                await place_bet(conn, user_id=11, amount_rub=Decimal("100"), bet="17")
        self.assertEqual(raised.exception.status_code, 409)
        reserve.assert_not_awaited()

    async def test_empty_chip_list_is_rejected(self):
        conn = SettleConn([])
        with self.assertRaises(HTTPException) as raised:
            await place_bets(conn, user_id=11, chips=[])
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Нет фишек", str(raised.exception.detail))
        conn.execute.assert_not_awaited()

    async def test_batch_two_spots_one_publish(self):
        conn = SettleConn([])
        reserve = AsyncMock()
        events = []
        red_seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("97.50")),
            profile={"account_id": 8},
        )
        straight_seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("855.00")),
            profile={"account_id": 8},
        )
        with ExitStack() as stack:
            self._enter_place(
                stack,
                bets=[],
                seat=red_seat,
                reserve=reserve,
            )
            stack.enter_context(
                patch(
                    "casino_roulette_table.load_roulette_house_seat",
                    new=AsyncMock(side_effect=[red_seat, straight_seat]),
                )
            )
            stack.enter_context(
                patch(
                    "casino_roulette_table.publish",
                    side_effect=lambda payload: events.append(dict(payload)),
                )
            )
            await place_bets(
                conn,
                user_id=11,
                chips=[
                    {"bet": "red", "amount_rub": Decimal("50")},
                    {"bet": "22", "amount_rub": Decimal("25")},
                ],
            )
        self.assertEqual(reserve.await_count, 2)
        self.assertEqual(reserve.await_args_list[0].kwargs["amount_rub"], Decimal("50"))
        self.assertEqual(reserve.await_args_list[1].kwargs["amount_rub"], Decimal("25"))
        inserted = [
            call for call in conn.execute.await_args_list if "INSERT INTO casino_roulette_bets" in call.args[0]
        ]
        self.assertEqual(len(inserted), 2)
        self.assertEqual(inserted[0].args[3], "red")
        self.assertEqual(inserted[0].args[4], Decimal("50"))
        self.assertEqual(inserted[1].args[3], "22")
        self.assertEqual(inserted[1].args[4], Decimal("25"))
        self.assertEqual([event["type"] for event in events], ["bet"])

    async def test_batch_second_spot_bankroll_never_holds(self):
        conn = SettleConn([])
        reserve = AsyncMock()
        adjust = AsyncMock()
        ok_seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("97.50")),
            profile={"account_id": 8},
        )
        with (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_roulette_table.maybe_close_due", new=AsyncMock()),
            patch("casino_roulette_table.lock_casino_users", new=AsyncMock()),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=[])),
            patch(
                "casino_roulette_table.load_roulette_house_seat",
                new=AsyncMock(
                    side_effect=[
                        ok_seat,
                        HTTPException(status_code=409, detail="House bankroll is insufficient"),
                    ]
                ),
            ),
            patch("casino_roulette_table._adjust_house_reserve", new=adjust),
            patch("casino_roulette_table.reserve_unified_funds", new=reserve),
        ):
            with self.assertRaises(HTTPException) as raised:
                await place_bets(
                    conn,
                    user_id=11,
                    chips=[
                        {"bet": "red", "amount_rub": Decimal("50")},
                        {"bet": "22", "amount_rub": Decimal("25")},
                    ],
                )
        self.assertEqual(raised.exception.status_code, 409)
        reserve.assert_not_awaited()
        adjust.assert_not_awaited()

    async def test_batch_on_locked_round_never_holds(self):
        conn = SettleConn([])
        reserve = AsyncMock()
        with (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_roulette_table.maybe_close_due", new=AsyncMock()),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round(status="locked"))),
            patch("casino_roulette_table.reserve_unified_funds", new=reserve),
        ):
            with self.assertRaises(HTTPException) as raised:
                await place_bets(
                    conn,
                    user_id=11,
                    chips=[{"bet": "red", "amount_rub": Decimal("50")}],
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("крутится", str(raised.exception.detail))
        reserve.assert_not_awaited()

    async def test_due_closer_with_no_open_window_is_a_noop(self):
        conn = SettleConn([])
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())):
            await maybe_close_due(conn)
        conn.execute.assert_not_awaited()

    async def test_telegram_settle_enqueues_one_outbox_per_chat(self):
        conn = SettleConn(
            [
                _bet(11, "red", "50", "97.50", 1, notify_chat_id=-1001),
                _bet(22, "17", "10", "342.50", 2, notify_chat_id=-1001),
                _bet(33, "black", "10", "19.50", 3, notify_chat_id=33),
            ]
        )

        async def fake_play(conn, **kwargs):
            return {"bet": kwargs["bet"], "won": False, "payout_rub": "0.00"}

        with (
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=conn.bets)),
            patch("casino_roulette_table._named_public", new=AsyncMock(return_value={"players": []})),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table.play_roulette_known_pocket_with_conn", new=fake_play),
            patch("casino_roulette_table.publish"),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        outbox = [
            call
            for call in conn.execute.await_args_list
            if "INSERT INTO casino_notification_outbox" in call.args[0]
        ]
        self.assertEqual(len(outbox), 2)
        chats = {call.args[5] for call in outbox}
        self.assertTrue(any("-1001" in str(payload) for payload in chats))
        self.assertTrue(any('"chat_id": 33' in str(payload) or '"chat_id":33' in str(payload) for payload in chats))

    async def test_site_only_settle_skips_outbox(self):
        conn = SettleConn([_bet(11, "red", "50", "97.50", 1)])

        async def fake_play(conn, **kwargs):
            return {"bet": kwargs["bet"], "won": False, "payout_rub": "0.00"}

        with (
            patch("casino_roulette_table._bets", new=AsyncMock(return_value=conn.bets)),
            patch("casino_roulette_table._named_public", new=AsyncMock(return_value={"players": []})),
            patch("casino_roulette_table._lock_open", new=AsyncMock(return_value=_round())),
            patch("casino_roulette_table.play_roulette_known_pocket_with_conn", new=fake_play),
            patch("casino_roulette_table.publish"),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        outbox = [
            call
            for call in conn.execute.await_args_list
            if "INSERT INTO casino_notification_outbox" in call.args[0]
        ]
        self.assertEqual(outbox, [])

    async def test_telegram_notify_chat_survives_a_second_chip(self):
        conn = SettleConn([])
        bets = [_bet(11, "red", "50", "97.50", 3, notify_chat_id=-1001)]
        seat = types.SimpleNamespace(
            max_settlement=types.SimpleNamespace(payout=Decimal("855.00")),
            profile={"account_id": 8},
        )
        with ExitStack() as stack:
            self._enter_place(stack, bets=bets, seat=seat, release=AsyncMock(), reserve=AsyncMock())
            await place_bet(
                conn, user_id=11, amount_rub=Decimal("25"), bet="22", notify_chat_id=11
            )
        inserted = [
            call for call in conn.execute.await_args_list if "INSERT INTO casino_roulette_bets" in call.args[0]
        ]
        self.assertTrue(inserted)
        self.assertEqual(inserted[0].args[8], -1001)


class RouletteTableSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_returns_even_if_due_close_hits_stake_window(self):
        conn = types.SimpleNamespace(
            fetchrow=AsyncMock(
                side_effect=[
                    {"id": 17, "status": "open", "round_id": "rt-due", "commit_hash": COMMIT},
                    None,
                ]
            )
        )
        named = {
            "status": "open",
            "round_id": "rt-due",
            "history": [{"id": "rt-old", "pocket": 34}],
            "chips": [],
        }
        with (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())),
            patch(
                "casino_roulette_table.maybe_close_due",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=409, detail="Ставка вне лимита (10.00–277.58 ₽)"
                    )
                ),
            ),
            patch(
                "casino_roulette_table._bets",
                new=AsyncMock(return_value=[_bet(11, "11", "300", "10275", 1)]),
            ),
            patch("casino_roulette_table._named_public", new=AsyncMock(return_value=named)),
        ):
            snap = await snapshot(conn, viewer_id=11)
        self.assertEqual(snap["status"], "open")
        self.assertEqual(snap["history"][0]["pocket"], 34)

    async def test_snapshot_keeps_empty_open_round_instead_of_recent_settled(self):
        conn = types.SimpleNamespace(
            fetchrow=AsyncMock(
                side_effect=[
                    {"id": 18, "status": "open", "round_id": "rt-new", "commit_hash": COMMIT},
                    {"id": 17, "status": "settled", "round_id": "rt-old", "pocket": 17},
                ]
            )
        )
        named = AsyncMock(return_value={"status": "open", "round_id": "rt-new", "history": []})
        with (
            patch("casino_roulette_table.load_table_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_roulette_table.maybe_close_due", new=AsyncMock()),
            patch("casino_roulette_table._named_public", new=named),
        ):
            snap = await snapshot(conn, viewer_id=11)
        self.assertEqual(snap["round_id"], "rt-new")
        self.assertEqual(named.await_args.args[1]["status"], "open")
        self.assertEqual(named.await_args.args[1]["round_id"], "rt-new")


if __name__ == "__main__":
    unittest.main()
