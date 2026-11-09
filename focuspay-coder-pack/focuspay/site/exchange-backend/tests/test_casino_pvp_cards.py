"""Site baccarat must finish without Telegram hit/stand DMs.

Live hang: web-f31b85ae252f stayed active after @alwayss hit because the site
creator never received bak_hit_/bak_stand_ (msg_id_creator was null).
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from casino_cards import baccarat_hand_score
from casino_pvp_cards import (
    DEMO_JOIN_DETAIL,
    abort_unfinishable_card_duel,
    assert_card_duel_joinable,
    card_duel_is_unfinishable,
    complete_site_card_duel_after_join,
    complete_site_card_duel_if_due,
    is_demo_duel_id,
    is_site_card_duel,
    is_site_duel_id,
    merge_dealt_hand,
    pvp_card_outcome,
)


class SiteDuelIdTests(unittest.TestCase):
    def test_web_hex_id_matches_site_create(self):
        self.assertTrue(is_site_duel_id("web-f31b85ae252f"))
        self.assertTrue(is_site_duel_id("web-03e1a2745423"))
        self.assertFalse(is_site_duel_id("web-demo-baccara-waiting"))
        self.assertFalse(is_site_duel_id("baccara-11111111-1111-1111-1111-111111111111"))
        self.assertFalse(is_site_duel_id("web-F31B85AE252F"))

    def test_demo_prefix_is_not_a_live_site_id(self):
        self.assertTrue(is_demo_duel_id("web-demo-baccara-waiting"))
        self.assertFalse(is_demo_duel_id("web-f31b85ae252f"))


class MergeDealtHandTests(unittest.TestCase):
    def test_empty_takes_house_draw(self):
        house = ["2♣", "Q♣", "9♦"]
        self.assertEqual(merge_dealt_hand([], house), house)

    def test_extends_site_creator_two_cards_when_house_owes_a_third(self):
        stored = ["2♣", "Q♣"]
        house = ["2♣", "Q♣", "9♦"]
        self.assertEqual(merge_dealt_hand(stored, house), house)
        self.assertEqual(baccarat_hand_score(stored), 2)

    def test_keeps_telegram_hit_that_already_has_three(self):
        stored = ["4♦", "7♣", "K♠"]
        house = ["4♦", "7♣", "K♠"]
        self.assertEqual(merge_dealt_hand(stored, house), stored)
        self.assertEqual(baccarat_hand_score(stored), 1)

    def test_does_not_shrink_a_player_hit_past_house_size(self):
        stored = ["4♦", "7♣", "K♠"]
        house = ["4♦", "7♣"]
        self.assertEqual(merge_dealt_hand(stored, house), stored)

    def test_mismatch_keeps_the_live_hand(self):
        self.assertEqual(merge_dealt_hand(["A♠", "2♣"], ["K♥", "Q♣", "9♦"]), ["A♠", "2♣"])


class PvpCardOutcomeTests(unittest.TestCase):
    def test_stuck_web_f31b_hands_have_a_winner_if_creator_never_clicked(self):
        payload = pvp_card_outcome(
            "baccara",
            ["2♣", "Q♣"],
            ["4♦", "7♣", "K♠"],
            creator_id=940002,
            opponent_id=7869431717,
        )
        self.assertEqual(payload["kind"], "winner")
        self.assertEqual(payload["reason"], "site_card_auto")
        self.assertEqual(payload["winner_id"], 940002)
        self.assertEqual(payload["creator_score"], 2)
        self.assertEqual(payload["opponent_score"], 1)

    def test_higher_baccarat_mod10_wins(self):
        payload = pvp_card_outcome(
            "baccara",
            ["2♣", "Q♣"],
            ["4♦", "7♣", "K♠"],
            creator_id=11,
            opponent_id=22,
        )
        self.assertEqual(payload["kind"], "winner")
        self.assertEqual(payload["winner_id"], 11)
        self.assertEqual(payload["creator_score"], 2)
        self.assertEqual(payload["opponent_score"], 1)

    def test_tie_has_no_winner_id(self):
        payload = pvp_card_outcome(
            "baccara",
            ["A♠", "8♣"],
            ["9♥", "K♦"],
            creator_id=11,
            opponent_id=22,
        )
        self.assertEqual(payload["kind"], "draw")
        self.assertNotIn("winner_id", payload)


class SiteCardDuelGateTests(unittest.TestCase):
    def test_active_web_baccarat_with_opponent_is_a_site_card_duel(self):
        self.assertTrue(
            is_site_card_duel(
                {
                    "game_id": "web-f31b85ae252f",
                    "game_type": "baccara",
                    "status": "active",
                    "opponent_id": 7869431717,
                    "counterparty_kind": "player",
                }
            )
        )

    def test_waiting_or_telegram_native_is_not_auto_resolved(self):
        self.assertFalse(
            is_site_card_duel(
                {
                    "game_id": "web-f31b85ae252f",
                    "game_type": "baccara",
                    "status": "waiting",
                    "opponent_id": None,
                }
            )
        )
        self.assertFalse(
            is_site_card_duel(
                {
                    "game_id": "baccara-1",
                    "game_type": "baccara",
                    "status": "active",
                    "opponent_id": 22,
                }
            )
        )


class UnfinishableCardDuelTests(unittest.TestCase):
    def test_demo_active_with_opponent_cannot_hmac_settle(self):
        self.assertTrue(
            card_duel_is_unfinishable(
                {
                    "game_id": "web-demo-baccara-waiting",
                    "game_type": "baccara",
                    "status": "active",
                    "opponent_id": 940002,
                    "creator_id": 11,
                    "counterparty_kind": "player",
                }
            )
        )

    def test_site_hex_without_commit_cannot_hmac_settle(self):
        self.assertTrue(
            card_duel_is_unfinishable(
                {
                    "game_id": "web-f31b85ae252f",
                    "game_type": "baccara",
                    "status": "active",
                    "opponent_id": 22,
                    "rng_commit": "",
                }
            )
        )

    def test_site_hex_without_commit_key_defers_to_resolve(self):
        self.assertFalse(
            card_duel_is_unfinishable(
                {
                    "game_id": "web-f31b85ae252f",
                    "game_type": "baccara",
                    "status": "active",
                    "opponent_id": 22,
                    "counterparty_kind": "player",
                }
            )
        )

    def test_telegram_native_stays_on_hit_stand(self):
        self.assertFalse(
            card_duel_is_unfinishable(
                {
                    "game_id": "baccara-1",
                    "game_type": "baccara",
                    "status": "active",
                    "opponent_id": 22,
                }
            )
        )

    def test_waiting_demo_join_is_blocked(self):
        with self.assertRaises(HTTPException) as err:
            assert_card_duel_joinable(
                {
                    "game_id": "web-demo-baccara-waiting",
                    "game_type": "baccara",
                    "status": "waiting",
                    "opponent_id": None,
                }
            )
        self.assertEqual(err.exception.status_code, 409)
        self.assertEqual(err.exception.detail, DEMO_JOIN_DETAIL)

    def test_live_web_hex_join_is_allowed(self):
        assert_card_duel_joinable(
            {
                "game_id": "web-f31b85ae252f",
                "game_type": "baccara",
                "status": "waiting",
                "opponent_id": None,
            }
        )


class AbortUnfinishableCardDuelTests(unittest.IsolatedAsyncioTestCase):
    async def test_aborts_demo_and_releases_opponent_hold(self):
        game = {
            "game_id": "web-demo-baccara-waiting",
            "game_type": "baccara",
            "status": "active",
            "creator_id": 11,
            "opponent_id": 940002,
            "bet_rub": 50,
            "counterparty_kind": "player",
            "rng_commit": None,
            "game_data": {},
        }
        hold = {
            "hold_id": "casino-web-demo-baccara-waiting-opponent",
            "telegram_id": 940002,
            "game_id": "web-demo-baccara-waiting",
            "amount_rub": 50,
            "ledger_order_ref": "ref-demo",
            "status": "active",
        }

        class _Conn:
            def __init__(self):
                self.game = dict(game)
                self.holds = [dict(hold)]
                self.released = False

            async def execute(self, query, *args):
                if "pg_advisory" in query:
                    return "SELECT"
                if "UPDATE casino_balance_holds" in query:
                    self.released = True
                    return "UPDATE 1"
                raise AssertionError(query)

            async def fetch(self, query, *args):
                if "FROM casino_balance_holds" in query:
                    return list(self.holds)
                raise AssertionError(query)

            async def fetchrow(self, query, *args):
                if "FROM casino_games" in query and "FOR UPDATE" in query:
                    return self.game
                if "UPDATE casino_games" in query:
                    self.game = {**self.game, "status": "cancelled", "game_data": {"release_reason": args[1]}}
                    return self.game
                raise AssertionError(query)

        conn = _Conn()
        with patch("casino_finance.release_unified_hold", new=AsyncMock()) as release:
            out = await abort_unfinishable_card_duel(conn, "web-demo-baccara-waiting", actor_id=940002)
        self.assertEqual(out["status"], "cancelled")
        self.assertEqual(out["game_data"]["release_reason"], "unfinishable_card_duel")
        self.assertTrue(conn.released)
        release.assert_awaited_once()
        self.assertEqual(release.await_args.kwargs["user_id"], 940002)

    async def test_outsider_cannot_abort(self):
        game = {
            "game_id": "web-demo-baccara-waiting",
            "game_type": "baccara",
            "status": "active",
            "creator_id": 11,
            "opponent_id": 940002,
            "bet_rub": 50,
            "counterparty_kind": "player",
        }

        class _Conn:
            async def execute(self, query, *args):
                return "SELECT"

            async def fetchrow(self, query, *args):
                return game

        with self.assertRaises(HTTPException) as err:
            await abort_unfinishable_card_duel(_Conn(), "web-demo-baccara-waiting", actor_id=1)
        self.assertEqual(err.exception.status_code, 403)


class CompleteSiteCardDuelTests(unittest.IsolatedAsyncioTestCase):
    async def test_room_poll_skips_non_site_ids(self):
        conn = AsyncMock()
        self.assertIsNone(await complete_site_card_duel_if_due(conn, "baccara-1"))
        conn.fetchrow.assert_not_awaited()

    async def test_join_leaves_telegram_native_card_games_alone(self):
        game = {
            "game_id": "baccara-1",
            "game_type": "baccara",
            "status": "active",
            "opponent_id": 22,
        }
        self.assertEqual(await complete_site_card_duel_after_join(AsyncMock(), game), game)

    async def test_join_resolves_web_baccarat_so_it_does_not_wait_for_dm(self):
        game = {
            "game_id": "web-f31b85ae252f",
            "game_type": "baccara",
            "status": "active",
            "creator_id": 940002,
            "opponent_id": 7869431717,
            "state_version": 6,
            "counterparty_kind": "player",
        }
        finished = {**game, "status": "finished"}
        with patch(
            "casino_pvp_cards.resolve_site_card_duel",
            new=AsyncMock(return_value=finished),
        ) as resolve:
            out = await complete_site_card_duel_after_join(AsyncMock(), game)
        resolve.assert_awaited_once()
        self.assertEqual(out["status"], "finished")

    async def test_join_aborts_stuck_demo_instead_of_waiting_for_dm(self):
        game = {
            "game_id": "web-demo-baccara-waiting",
            "game_type": "baccara",
            "status": "active",
            "creator_id": 11,
            "opponent_id": 940002,
            "counterparty_kind": "player",
        }
        cancelled = {**game, "status": "cancelled"}
        with patch(
            "casino_pvp_cards.abort_unfinishable_card_duel",
            new=AsyncMock(return_value=cancelled),
        ) as abort:
            out = await complete_site_card_duel_after_join(AsyncMock(), game)
        abort.assert_awaited_once()
        self.assertEqual(out["status"], "cancelled")
