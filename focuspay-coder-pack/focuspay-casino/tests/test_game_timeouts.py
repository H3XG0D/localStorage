import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from tests.telebot_stub import TelebotModules


with TelebotModules("games.baccara", "games.blackjack", "games.table_wizard", "games.v2_tables", "games.v2_runtime"):
    import games.baccara as baccara
    import games.blackjack as blackjack


class BotStub:
    def __init__(self):
        self.messages = []

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))
        return None


class ClientStub:
    def __init__(self):
        self.version = 1
        self.events = []
        self.persisted = []
        self.commits = []
        self.settlements = []
        self.releases = []

    def _response(self, *, status="active", financial_state=None, payout_rub=None):
        self.version += 1
        response = {
            "success": True,
            "game": {
                "state_version": self.version,
                "status": status,
                "financial_state": financial_state or {},
            },
        }
        if payout_rub is not None:
            response["payout_rub"] = payout_rub
        return response

    async def persist_game_state(self, game_id, *, expected_state_version, game_state):
        self.events.append("persist")
        self.persisted.append((game_id, expected_state_version, game_state))
        return self._response()

    async def commit_game_outcome(self, game_id, winner_id, *, expected_state_version, outcome):
        self.events.append("commit")
        self.commits.append((game_id, winner_id, expected_state_version, outcome))
        return self._response(status="outcome_committed")

    async def settle_committed_outcome(self, game_id):
        self.events.append("settle")
        self.settlements.append(game_id)
        return self._response(status="finished", payout_rub="185.00")

    async def release_game(self, game_id, *, reason=None):
        self.events.append("release")
        self.releases.append((game_id, reason))
        return self._response(status="released")


class TimeoutLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        blackjack.active_games.clear()
        blackjack._game_locks.clear()
        baccara.active_games.clear()
        baccara._game_locks.clear()

    def tearDown(self):
        blackjack.active_games.clear()
        blackjack._game_locks.clear()
        baccara.active_games.clear()
        baccara._game_locks.clear()

    async def test_blackjack_no_move_timeout_commits_outcome_before_settlement(self):
        game_id = 101
        now = datetime.now(timezone.utc)
        blackjack.active_games[game_id] = {
            "status": "playing", "state_version": 1,
            "started_at": now - timedelta(hours=3),
            "bet": Decimal("100.00"), "creator_id": 1, "creator_name": "Creator",
            "opponent_id": 2, "opponent_name": "Opponent",
            "settlement_game_id": "blackjack-timeout-101",
            "cards_creator": ["10♠"], "cards_opponent": ["9♠"],
            "ace_values_creator": [], "ace_values_opponent": [],
            "status_creator": None, "status_opponent": None,
        }
        client = ClientStub()

        await asyncio.wait_for(blackjack.process_blackjack_timeouts(BotStub(), client, now=now), timeout=0.2)

        self.assertEqual(len(client.commits), 1)
        self.assertEqual(client.commits[0][1], None)
        self.assertEqual(
            client.commits[0][3],
            {"kind": "timeout", "reason": "no_moves_timeout", "phase": "playing", "statuses": {"creator": None, "opponent": None}},
        )
        self.assertLess(client.events.index("commit"), client.events.index("settle"))
        self.assertEqual(client.settlements, ["blackjack-timeout-101"])
        self.assertEqual(client.releases, [])
        self.assertNotIn(game_id, blackjack.active_games)
        self.assertFalse(blackjack.get_game_lock(game_id).locked())

    async def test_baccara_no_move_timeout_commits_outcome_before_settlement(self):
        game_id = 202
        now = datetime.now(timezone.utc)
        baccara.active_games[game_id] = {
            "status": "playing", "state_version": 1,
            "started_at": now - timedelta(hours=3),
            "bet": Decimal("100.00"), "creator_id": 1, "creator_name": "Creator",
            "opponent_id": 2, "opponent_name": "Opponent",
            "settlement_game_id": "baccara-timeout-202",
            "cards_creator": ["9♠"], "cards_opponent": ["8♠"],
            "decision_creator": None, "decision_opponent": None,
        }
        client = ClientStub()

        await asyncio.wait_for(baccara.process_baccara_timeouts(BotStub(), client, now=now), timeout=0.2)

        self.assertEqual(len(client.commits), 1)
        self.assertEqual(client.commits[0][1], None)
        self.assertEqual(
            client.commits[0][3],
            {"kind": "timeout", "reason": "no_moves_timeout", "phase": "playing", "decisions": {"creator": None, "opponent": None}},
        )
        self.assertLess(client.events.index("commit"), client.events.index("settle"))
        self.assertEqual(client.settlements, ["baccara-timeout-202"])
        self.assertEqual(client.releases, [])
        self.assertNotIn(game_id, baccara.active_games)
        self.assertFalse(baccara.get_game_lock(game_id).locked())


if __name__ == "__main__":
    unittest.main()
