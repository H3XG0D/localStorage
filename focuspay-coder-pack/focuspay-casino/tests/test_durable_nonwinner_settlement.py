import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from tests.telebot_stub import TelebotModules


with TelebotModules("games.baccara", "games.blackjack", "games.pvp", "games.table_wizard", "games.v2_tables", "games.v2_runtime"):
    import games.baccara as baccara
    import games.blackjack as blackjack
    import games.pvp as pvp


class BotStub:
    async def send_message(self, *args, **kwargs):
        return None


class LifecycleClientStub:
    def __init__(self):
        self.calls = []
        self.version = 1

    def _response(self, *, status="active"):
        self.version += 1
        return {"game": {"state_version": self.version, "status": status}}

    async def persist_game_state(self, **kwargs):
        self.calls.append(("persist", kwargs))
        return self._response()

    async def commit_game_outcome(self, **kwargs):
        self.calls.append(("commit", kwargs))
        return self._response(status="outcome_committed")

    async def settle_committed_outcome(self, **kwargs):
        self.calls.append(("settle", kwargs))
        return self._response(status="finished")

    async def release_game(self, **kwargs):
        raise AssertionError("games must settle committed outcomes instead of releasing directly")


class DurableNonwinnerSettlementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for module in (pvp, blackjack, baccara):
            module.active_games.clear()
            module._game_locks.clear()

    def tearDown(self):
        for module in (pvp, blackjack, baccara):
            module.active_games.clear()
            module._game_locks.clear()

    async def test_pvp_draw_commits_before_backend_release_and_drops_terminal_cache(self):
        game_id = "pvp-draw"
        pvp.active_games[game_id] = {
            "game_id": game_id,
            "game_type": "cub",
            "creator_id": 1,
            "creator_name": "Creator",
            "opponent_id": 2,
            "opponent_name": "Opponent",
            "bet": Decimal("100.00"),
            "chat_id": 1,
            "state_version": 1,
            "status": "finalizing",
            "creator_rolls": [4],
            "opponent_rolls": [4],
        }
        client = LifecycleClientStub()

        original_sleep = pvp.asyncio.sleep

        async def _no_wait(*_args, **_kwargs):
            return None

        pvp.asyncio.sleep = _no_wait
        try:
            await pvp.resolve_game_results(BotStub(), client, game_id)
        finally:
            pvp.asyncio.sleep = original_sleep

        self.assertEqual([name for name, _ in client.calls][-2:], ["commit", "settle"])
        self.assertEqual(client.calls[-2][1]["outcome"]["kind"], "draw")
        self.assertNotIn(game_id, pvp.active_games)

    async def test_blackjack_waiting_timeout_commits_before_settlement(self):
        gid = 10
        blackjack.active_games[gid] = {
            "settlement_game_id": "blackjack-timeout",
            "state_version": 1,
            "status": "waiting",
            "created_at": datetime.utcnow() - timedelta(hours=25),
            "creator_id": 1,
            "opponent_id": None,
        }
        client = LifecycleClientStub()

        await blackjack.process_blackjack_timeouts(BotStub(), client)

        self.assertEqual([name for name, _ in client.calls][-2:], ["commit", "settle"])
        self.assertEqual(client.calls[-2][1]["outcome"]["kind"], "timeout")
        self.assertNotIn(gid, blackjack.active_games)

    async def test_baccara_waiting_timeout_commits_before_settlement(self):
        gid = 20
        baccara.active_games[gid] = {
            "settlement_game_id": "baccara-timeout",
            "state_version": 1,
            "status": "waiting",
            "created_at": datetime.utcnow() - timedelta(hours=25),
            "creator_id": 1,
            "opponent_id": None,
        }
        client = LifecycleClientStub()

        await baccara.process_baccara_timeouts(BotStub(), client)

        self.assertEqual([name for name, _ in client.calls][-2:], ["commit", "settle"])
        self.assertEqual(client.calls[-2][1]["outcome"]["kind"], "timeout")
        self.assertNotIn(gid, baccara.active_games)


if __name__ == "__main__":
    unittest.main()
