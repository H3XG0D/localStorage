"""Waiting 1×1 cancel + 10-minute unjoined expiry."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from casino_waiting import (
    REASON_TIMEOUT,
    WAITING_JOIN_TIMEOUT_SECONDS,
    cancel_player_duel,
    cancel_waiting_duel,
    expire_unjoined_due,
    expire_unjoined_v2,
    expire_waiting_duels,
    waiting_cutoff,
)


NOW = datetime(2026, 8, 29, 19, 0, tzinfo=timezone.utc)


class WaitingConn:
    def __init__(self, game, hold=None):
        self.game = dict(game) if game is not None else None
        self.hold = dict(hold) if hold is not None else None
        self.released: list[tuple] = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetch = AsyncMock(side_effect=self._fetch)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _execute(self, query, *args):
        if "pg_advisory" in query:
            return "SELECT"
        if "UPDATE casino_balance_holds" in query:
            if self.hold:
                self.hold["status"] = "released"
            return "UPDATE 1"
        raise AssertionError(query)

    async def _fetch(self, query, *args):
        if "duel:expire-unjoined" in query:
            cutoff = args[0]
            if (
                self.game
                and str(self.game["status"]) == "waiting"
                and self.game["opponent_id"] is None
                and self.game["created_at"] <= cutoff
            ):
                return [{"game_id": self.game["game_id"]}]
            return []
        if "v2:expire-unjoined" in query:
            return []
        if "house:expire-unjoined" in query:
            return []
        raise AssertionError(query)

    async def _fetchrow(self, query, *args):
        if "FROM casino_games" in query and "FOR UPDATE" in query:
            return self.game
        if "FROM casino_balance_holds" in query:
            return self.hold
        if "UPDATE casino_games" in query:
            if not self.game or str(self.game["status"]) != "waiting" or self.game["opponent_id"] is not None:
                return None
            self.game = {
                **self.game,
                "status": "cancelled",
                "game_data": {"release_reason": args[1]},
            }
            return self.game
        raise AssertionError(query)


def _waiting_game(**kwargs):
    row = {
        "game_id": "web-03e1a2745423",
        "game_type": "baccara",
        "creator_id": 940002,
        "creator_hold_id": "casino-web-03e1a2745423-creator",
        "bet_rub": Decimal("100.00"),
        "status": "waiting",
        "opponent_id": None,
        "created_at": NOW - timedelta(minutes=11),
        "game_state": {},
        "outcome": None,
        "game_data": {},
    }
    row.update(kwargs)
    return row


def _hold(game):
    return {
        "hold_id": game["creator_hold_id"],
        "telegram_id": game["creator_id"],
        "game_id": game["game_id"],
        "amount_rub": game["bet_rub"],
        "ledger_order_ref": f"ref-{game['game_id']}",
        "status": "active",
    }


class CutoffTests(unittest.TestCase):
    def test_timeout_is_ten_minutes(self):
        self.assertEqual(WAITING_JOIN_TIMEOUT_SECONDS, 600)
        cut = waiting_cutoff(NOW)
        self.assertEqual(cut, NOW - timedelta(minutes=10))


class CancelWaitingDuelTests(unittest.IsolatedAsyncioTestCase):
    async def test_creator_cancels_waiting_and_releases_hold(self):
        game = _waiting_game()
        conn = WaitingConn(game, _hold(game))
        with patch("casino_waiting.release_unified_hold", new=AsyncMock()) as release:
            row = await cancel_waiting_duel(conn, game["game_id"], actor_id=940002)
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["game_data"]["release_reason"], "creator_cancelled")
        release.assert_awaited_once()
        self.assertEqual(release.await_args.kwargs["user_id"], 940002)
        self.assertEqual(release.await_args.kwargs["amount_rub"], Decimal("100.00"))

    async def test_non_creator_forbidden(self):
        game = _waiting_game()
        conn = WaitingConn(game, _hold(game))
        with self.assertRaises(HTTPException) as err:
            await cancel_waiting_duel(conn, game["game_id"], actor_id=1)
        self.assertEqual(err.exception.status_code, 403)

    async def test_join_race_conflicts(self):
        game = _waiting_game(opponent_id=77, status="waiting")
        conn = WaitingConn(game, _hold(game))
        with self.assertRaises(HTTPException) as err:
            await cancel_waiting_duel(conn, game["game_id"], actor_id=940002)
        self.assertEqual(err.exception.status_code, 409)

    async def test_active_game_not_cancelled(self):
        game = _waiting_game(status="active", opponent_id=77)
        conn = WaitingConn(game, _hold(game))
        with self.assertRaises(HTTPException) as err:
            await cancel_waiting_duel(conn, game["game_id"], actor_id=940002)
        self.assertEqual(err.exception.status_code, 409)


class ExpireWaitingTests(unittest.IsolatedAsyncioTestCase):
    async def test_expires_waiting_older_than_ten_minutes(self):
        game = _waiting_game(created_at=NOW - timedelta(minutes=10, seconds=1))
        conn = WaitingConn(game, _hold(game))
        with patch("casino_waiting.release_unified_hold", new=AsyncMock()):
            n = await expire_waiting_duels(conn, now=NOW)
        self.assertEqual(n, 1)
        self.assertEqual(conn.game["status"], "cancelled")
        self.assertEqual(conn.game["game_data"]["release_reason"], REASON_TIMEOUT)

    async def test_skips_waiting_younger_than_ten_minutes(self):
        game = _waiting_game(created_at=NOW - timedelta(minutes=9))
        conn = WaitingConn(game, _hold(game))
        n = await expire_waiting_duels(conn, now=NOW)
        self.assertEqual(n, 0)
        self.assertEqual(conn.game["status"], "waiting")

    async def test_does_not_expire_active(self):
        game = _waiting_game(status="active", opponent_id=5)
        conn = WaitingConn(game, _hold(game))
        n = await expire_waiting_duels(conn, now=NOW)
        self.assertEqual(n, 0)

    async def test_expire_due_counts_zero_v2_and_house_on_empty(self):
        game = _waiting_game(created_at=NOW - timedelta(minutes=9))
        conn = WaitingConn(game, _hold(game))
        with patch("casino_waiting.expire_unjoined_v2", new=AsyncMock(return_value=0)), patch(
            "casino_waiting.expire_open_house_unjoined", new=AsyncMock(return_value=0)
        ), patch(
            "casino_pvp_cards.abort_unfinishable_card_duels_due", new=AsyncMock(return_value=0)
        ), patch(
            "casino_waiting.expire_stale_v2_play", new=AsyncMock(return_value=0)
        ):
            out = await expire_unjoined_due(conn, now=NOW)
        self.assertEqual(out, {"duels": 0, "v2": 0, "stale_play": 0, "house": 0, "cards": 0})

    async def test_v2_open_tables_are_not_expired_by_join_timeout(self):
        closed = await expire_unjoined_v2(None, now=NOW)
        self.assertEqual(closed, 0)


class RouteImportTests(unittest.TestCase):
    def test_user_cancel_duel_route_exists(self):
        from routers import user_casino

        paths = {getattr(route, "path", None) for route in user_casino.router.routes}
        self.assertIn("/casino/duels/{game_id}/cancel", paths)


class CancelPlayerDuelTests(unittest.IsolatedAsyncioTestCase):
    async def test_stuck_demo_aborts_instead_of_waiting_cancel(self):
        cancelled = {"game_id": "web-demo-baccara-waiting", "status": "cancelled"}
        conn = WaitingConn(_waiting_game(status="active", opponent_id=940002))
        with patch(
            "casino_pvp_cards.abort_unfinishable_card_duel",
            new=AsyncMock(return_value=cancelled),
        ) as abort:
            row = await cancel_player_duel(conn, "web-demo-baccara-waiting", actor_id=940002)
        abort.assert_awaited_once()
        self.assertEqual(row["status"], "cancelled")

    async def test_waiting_still_cancels_when_abort_is_noop(self):
        game = _waiting_game()
        conn = WaitingConn(game, _hold(game))
        with patch(
            "casino_pvp_cards.abort_unfinishable_card_duel",
            new=AsyncMock(return_value=None),
        ), patch("casino_waiting.release_unified_hold", new=AsyncMock()):
            row = await cancel_player_duel(conn, game["game_id"], actor_id=940002)
        self.assertEqual(row["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
