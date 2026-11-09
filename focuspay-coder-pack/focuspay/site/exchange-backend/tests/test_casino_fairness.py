"""Provably-fair session + public verifier. These must fail if verify always says fair."""
from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from casino_cards import CARD_SHUFFLE_ALGORITHM, dealt_cards, game_commit, pair_commit, verify_card_round
from casino_fairness import rotate_fairness_session, seed_rotation_allowed


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

try:
    from routers.internal_casino import (
        CardsDealRequest,
        CardsPrepareRequest,
        deal_cards_with_conn,
        prepare_cards_with_conn,
    )
    from routers.public_casino import FairnessVerifyRequest, verify_fairness
    import routers.internal_casino as internal_casino
finally:
    if _auth_module is None:
        del sys.modules["auth"]
    if _db_module is None:
        del sys.modules["db"]

BACKEND = Path(__file__).resolve().parents[1]
CARD_SEED = "ab" * 32
CARD_GAME_ID = "baccara-fair-1"
CARD_COMMIT = game_commit(CARD_SEED, CARD_GAME_ID)


def _active_card_game():
    return {
        "game_id": CARD_GAME_ID,
        "game_type": "baccara",
        "creator_id": 11,
        "opponent_id": 22,
        "bet_rub": Decimal("30.00"),
        "winner_id": None,
        "creator_hold_id": "casino-baccara-fair-1-creator",
        "opponent_hold_id": "casino-baccara-fair-1-opponent",
        "status": "active",
        "state_version": 2,
        "game_state": {},
        "outcome": None,
        "game_data": {
            "card_rng": {
                "algorithm": CARD_SHUFFLE_ALGORITHM,
                "commit": CARD_COMMIT,
                "creator_cards": [],
                "opponent_cards": [],
            }
        },
        "created_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
        "started_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
        "outcome_committed_at": None,
        "finished_at": None,
    }


class SeatDealConn:
    def __init__(self, game, rng):
        self.game = dict(game)
        self.rng = rng
        self.execute = AsyncMock(side_effect=self._execute)

    async def fetchrow(self, query, *args):
        if "FROM casino_games" in query:
            return self.game
        if "FROM casino_house_rng_commits" in query:
            return self.rng
        raise AssertionError(query)

    async def _execute(self, query, *args):
        if "SET game_data = $2::jsonb" in query:
            self.game["game_data"] = json.loads(args[1])
            return
        raise AssertionError(query)


class FairnessConn:
    def __init__(self, *, rotation_allowed=True, session=None):
        self.rotation_allowed = rotation_allowed
        self.session = session or {
            "telegram_id": 11,
            "server_seed": CARD_SEED,
            "commit_hash": pair_commit(CARD_SEED),
            "client_seed": "alice",
            "nonce": 3,
            "previous_server_seed": None,
            "previous_commit": None,
        }
        self.queries = []

    async def fetchrow(self, query, *args):
        self.queries.append(("fetchrow", query, args))
        if "seed_rotation_allowed" in query:
            return {"value": {"enabled": self.rotation_allowed}}
        if "FROM casino_fairness_seeds" in query:
            return dict(self.session)
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.queries.append(("execute", query, args))
        if "SET server_seed" in query:
            self.session = {
                **self.session,
                "server_seed": args[1],
                "commit_hash": args[2],
                "nonce": 0,
                "previous_server_seed": args[3],
                "previous_commit": args[4],
            }
            return "UPDATE 1"
        if "nonce = nonce + 1" in query:
            self.session["nonce"] = int(self.session["nonce"]) + 1
            return "UPDATE 1"
        if "INSERT INTO casino_house_rng_commits" in query:
            return "INSERT 0 1"
        if "SET client_seed" in query:
            self.session["client_seed"] = args[1]
            return "UPDATE 1"
        return "UPDATE 1"


class PrepareConn:
    def __init__(self, *, existing=None, session=None):
        self.existing = existing
        self.session = session or {
            "telegram_id": 11,
            "server_seed": CARD_SEED,
            "commit_hash": pair_commit(CARD_SEED),
            "client_seed": "alice",
            "nonce": 3,
            "previous_server_seed": None,
            "previous_commit": None,
        }
        self.executes = []
        self.nonce_updates = 0

    async def fetchrow(self, query, *args):
        if "FROM casino_house_rng_commits" in query:
            return self.existing
        if "FROM casino_fairness_seeds" in query:
            return dict(self.session)
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.executes.append((query, args))
        if "nonce = nonce + 1" in query:
            self.nonce_updates += 1
            self.session["nonce"] = int(self.session["nonce"]) + 1
            return "UPDATE 1"
        return "INSERT 0 1"


class PublicCasinoFairnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_verify_endpoint_confirms_matching_seed_and_rejects_tamper(self):
        seed = CARD_SEED
        commit = game_commit(seed, CARD_GAME_ID)
        cards = dealt_cards(seed, CARD_GAME_ID, "creator", 2, client_seed="alice", nonce=3)
        ok = await verify_fairness(
            FairnessVerifyRequest(
                game_type="baccara",
                game_id=CARD_GAME_ID,
                server_seed=seed,
                client_seed="alice",
                nonce=3,
                commit=commit,
                side="creator",
                expected_cards=cards,
            )
        )
        self.assertTrue(ok["matches"])
        self.assertTrue(ok["fair"])
        self.assertEqual(ok["algorithm"], CARD_SHUFFLE_ALGORITHM)

        seat_cards = dealt_cards(seed, CARD_GAME_ID, "seat2", 2, client_seed="alice", nonce=3)
        seat_ok = await verify_fairness(
            FairnessVerifyRequest(
                game_type="baccara",
                game_id=CARD_GAME_ID,
                server_seed=seed,
                client_seed="alice",
                nonce=3,
                commit=commit,
                side="seat2",
                expected_cards=seat_cards,
            )
        )
        self.assertTrue(seat_ok["matches"])
        self.assertEqual(seat_ok["cards"]["seat2"], seat_cards)

        tampered = seed[:-1] + ("0" if seed[-1] != "0" else "1")
        bad = await verify_fairness(
            FairnessVerifyRequest(
                game_type="baccara",
                game_id=CARD_GAME_ID,
                server_seed=tampered,
                client_seed="alice",
                nonce=3,
                commit=commit,
            )
        )
        self.assertFalse(bad["matches"])
        self.assertFalse(bad["fair"])
        self.assertFalse(bad["commit_matches"])

    async def test_holdem_verify_matches_shared_board_and_rejects_wrong_board(self):
        from casino_cards import holdem_shuffled_deck, verify_holdem_round
        from casino_holdem import deal_holdem

        seed = CARD_SEED
        hand_id = "holdem-hand-fair-1"
        commit = game_commit(seed, hand_id)
        deck = holdem_shuffled_deck(seed, client_seed="alice", nonce=4, hand_id=hand_id)
        _holes, _burns, board = deal_holdem(list(deck), [1, 2])
        ok = await verify_fairness(
            FairnessVerifyRequest(
                game_type="holdem",
                game_id=hand_id,
                server_seed=seed,
                client_seed="alice",
                nonce=4,
                commit=commit,
                expected_cards=board,
            )
        )
        self.assertTrue(ok["matches"])
        self.assertEqual(ok["board"], board)
        self.assertEqual(ok["cards"]["holdem"], board)
        self.assertNotIn("holes", ok)
        self.assertNotIn("burns", ok)
        local = verify_holdem_round(
            server_seed=seed,
            client_seed="alice",
            nonce=4,
            hand_id=hand_id,
            commit=commit,
            expected_board=board,
        )
        self.assertTrue(local["matches"])
        bad = await verify_fairness(
            FairnessVerifyRequest(
                game_type="holdem",
                game_id=hand_id,
                server_seed=seed,
                client_seed="alice",
                nonce=4,
                commit=commit,
                expected_cards=["A♠", "A♥", "A♦", "A♣", "K♠"],
            )
        )
        self.assertFalse(bad["matches"])
        self.assertFalse(bad["cards_match"])

    def test_main_includes_public_casino_router(self):
        src = (BACKEND / "main.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(public_casino.router, prefix=\"/api/public\"", src)
        self.assertIn("@router.post(\"/casino/fairness/verify\")", (BACKEND / "routers/public_casino.py").read_text(encoding="utf-8"))


class FairnessRotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rotate_reveals_previous_seed_and_changes_commit(self):
        conn = FairnessConn()
        old_seed = conn.session["server_seed"]
        old_commit = conn.session["commit_hash"]
        result = await rotate_fairness_session(conn, 11)
        self.assertEqual(result["previous_server_seed"], old_seed)
        self.assertEqual(result["previous_commit"], old_commit)
        self.assertNotEqual(result["commit_hash"], old_commit)
        self.assertEqual(result["nonce"], 0)
        self.assertNotIn("server_seed", result)
        self.assertTrue(any("SET server_seed" in query for _kind, query, _args in conn.queries if isinstance(query, str)))

    async def test_rotate_is_blocked_when_setting_is_off(self):
        conn = FairnessConn(rotation_allowed=False)
        with self.assertRaises(HTTPException) as raised:
            await rotate_fairness_session(conn, 11)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(any("SET server_seed" in query for _kind, query, _args in conn.queries if isinstance(query, str)))

    async def test_seed_rotation_defaults_on_when_row_missing(self):
        conn = types.SimpleNamespace(fetchrow=AsyncMock(return_value=None))
        self.assertTrue(await seed_rotation_allowed(conn))


class FairnessNonceTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_increments_session_nonce_once_per_new_game(self):
        conn = PrepareConn()
        first = await prepare_cards_with_conn(
            conn,
            CardsPrepareRequest(game_id=CARD_GAME_ID, game_type="baccara", telegram_id=11),
        )
        self.assertEqual(first["nonce"], 3)
        self.assertEqual(first["client_seed"], "alice")
        self.assertEqual(first["rng_commit"], CARD_COMMIT)
        self.assertEqual(conn.nonce_updates, 1)
        self.assertNotIn("rng_seed", first)
        insert = next(args for query, args in conn.executes if "INSERT INTO casino_house_rng_commits" in query)
        self.assertEqual(insert[5], 3)
        self.assertEqual(insert[6], "alice")

        conn.existing = {
            "game_id": CARD_GAME_ID,
            "commit_hash": CARD_COMMIT,
            "server_seed": CARD_SEED,
            "nonce": 3,
            "status": "pending",
            "telegram_id": 11,
            "game_type": "baccara",
            "client_seed": "alice",
        }
        again = await prepare_cards_with_conn(
            conn,
            CardsPrepareRequest(game_id=CARD_GAME_ID, game_type="baccara", telegram_id=11),
        )
        self.assertEqual(again["nonce"], 3)
        self.assertEqual(conn.nonce_updates, 1)

    async def test_both_seats_see_the_same_commit(self):
        rng = {
            "commit_hash": CARD_COMMIT,
            "server_seed": CARD_SEED,
            "status": "pending",
            "client_seed": "alice",
            "nonce": 3,
        }
        conn = SeatDealConn(_active_card_game(), rng)
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()):
            creator = await deal_cards_with_conn(
                conn,
                CardsDealRequest(game_id=CARD_GAME_ID, telegram_id=11, hand_size=2),
            )
            opponent = await deal_cards_with_conn(
                conn,
                CardsDealRequest(game_id=CARD_GAME_ID, telegram_id=22, hand_size=2),
            )
        self.assertEqual(creator["rng_commit"], opponent["rng_commit"])
        self.assertEqual(creator["client_seed"], opponent["client_seed"])
        self.assertEqual(creator["nonce"], opponent["nonce"])
        self.assertEqual(creator["rng_commit"], CARD_COMMIT)
        self.assertNotEqual(creator["cards"], opponent["cards"])


class VerifyFunctionTamperTests(unittest.TestCase):
    def test_function_and_endpoint_share_the_same_false_on_tamper(self):
        seed = CARD_SEED
        commit = game_commit(seed, CARD_GAME_ID)
        tampered = seed[:-1] + ("0" if seed[-1] != "0" else "1")
        result = verify_card_round(
            server_seed=tampered,
            client_seed="alice",
            nonce=3,
            game_id=CARD_GAME_ID,
            commit=commit,
        )
        self.assertIs(result["matches"], False)
