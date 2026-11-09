"""Website inbox: join notices and live-session hrefs."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from casino_inbox import (
    EVENT_PLAYER_JOINED,
    EVENT_YOU_JOINED,
    game_href,
    inbox_snapshot,
    list_sessions,
    notify_player_joined,
    push_item,
)


class HrefTests(unittest.TestCase):
    def test_duel_v2_house_and_room_paths(self):
        self.assertEqual(game_href(kind="duel", game_id="abc"), "/casino/duels/abc")
        self.assertEqual(game_href(kind="v2", game_id="web-1"), "/casino/tables/web-1")
        self.assertEqual(game_href(kind="", game_id="web-1"), "/casino/tables/web-1")
        self.assertEqual(game_href(kind="duel", game_id="web-abc"), "/casino/duels/web-abc")
        self.assertIn("ht=ht-9", game_href(kind="house", game_id="ht-9"))
        self.assertEqual(game_href(kind="poker", game_id="p1"), "/casino/poker/p1")
        self.assertEqual(game_href(kind="room", game_id="r1"), "/casino/rooms/r1")
        self.assertEqual(game_href(kind="war", game_id="w1"), "/casino/wars/w1")

    def test_rewrite_stored_duels_href_for_v2(self):
        from casino_inbox import rewrite_stored_href

        self.assertEqual(
            rewrite_stored_href("/casino/duels/web-1", kind="v2", game_id="web-1", game_type="pvp_dice"),
            "/casino/tables/web-1",
        )
        self.assertEqual(
            rewrite_stored_href("/casino/duels/web-abc", kind="duel", game_id="web-abc", game_type="pvp_dice"),
            "/casino/duels/web-abc",
        )


class InboxConn:
    def __init__(self):
        self.inserted: list[tuple] = []
        self.rows: list[dict] = []
        self.fetch_calls: list[str] = []

    async def execute(self, query, *args):
        if "INSERT INTO casino_web_inbox" in query:
            self.inserted.append(args)
            return "INSERT 0 1"
        raise AssertionError(query)

    async def fetch(self, query, *args):
        self.fetch_calls.append(query)
        if "FROM casino_games" in query:
            return [
                {
                    "game_id": "g-duel",
                    "game_type": "pvp_dice",
                    "status": "active",
                    "bet_rub": Decimal("50.00"),
                    "creator_id": 10,
                    "opponent_id": 11,
                }
            ]
        if "casino_v2_tables" in query:
            return [
                {
                    "table_id": "web-table",
                    "game_type": "pvp_emoji",
                    "status": "running",
                    "stake_rub": Decimal("100.00"),
                    "creator_id": 10,
                }
            ]
        if "casino_house_tables" in query:
            return []
        if "casino_poker_tables" in query:
            return []
        if "casino_fixed_room" in query:
            return []
        if "casino_clan_wars" in query:
            return []
        if "casino_jackpot" in query:
            return []
        if "casino_roulette" in query:
            return []
        if "FROM casino_web_inbox" in query:
            return self.rows
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        return None


class NotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_join_writes_you_and_other_and_publishes(self):
        conn = InboxConn()
        with patch("casino_inbox.publish_user") as publish:
            await notify_player_joined(
                conn,
                joiner_id=20,
                other_ids=[10, 20, 0],
                kind="duel",
                game_id="g-duel",
                game_type="pvp_dice",
                stake_rub=Decimal("50"),
            )
        events = [row[1] for row in conn.inserted]
        self.assertEqual(events.count(EVENT_YOU_JOINED), 1)
        self.assertEqual(events.count(EVENT_PLAYER_JOINED), 1)
        self.assertEqual(conn.inserted[0][0], 20)
        self.assertEqual(conn.inserted[1][0], 10)
        self.assertEqual(conn.inserted[0][3], "/casino/duels/g-duel")
        self.assertEqual(conn.inserted[0][4], "Вы зашли в игру")
        self.assertEqual(conn.inserted[1][4], "В игру зашли")
        self.assertEqual(publish.call_count, 2)
        self.assertEqual(publish.call_args_list[0].args[0], 20)
        self.assertEqual(publish.call_args_list[0].args[1]["type"], "inbox")
        self.assertEqual(publish.call_args_list[0].args[1]["item"]["href"], "/casino/duels/g-duel")

    async def test_join_skips_joiner_inbox_when_asked(self):
        conn = InboxConn()
        with patch("casino_inbox.publish_user") as publish:
            await notify_player_joined(
                conn,
                joiner_id=20,
                other_ids=[10],
                kind="duel",
                game_id="g-duel",
                game_type="pvp_dice",
                stake_rub=Decimal("50"),
                notify_joiner=False,
            )
        events = [row[1] for row in conn.inserted]
        self.assertEqual(events.count(EVENT_YOU_JOINED), 0)
        self.assertEqual(events.count(EVENT_PLAYER_JOINED), 1)
        self.assertEqual(conn.inserted[0][0], 10)
        self.assertEqual(publish.call_count, 1)

    async def test_list_sessions_includes_duel_and_v2_with_href(self):
        sessions = await list_sessions(InboxConn(), 10)
        kinds = {row["kind"] for row in sessions}
        self.assertEqual(kinds, {"duel", "v2"})
        duel = next(row for row in sessions if row["kind"] == "duel")
        table = next(row for row in sessions if row["kind"] == "v2")
        self.assertEqual(duel["href"], "/casino/duels/g-duel")
        self.assertEqual(table["href"], "/casino/tables/web-table")
        self.assertEqual(table["game_type"], "pvp_dice")
        self.assertFalse(duel["can_cancel"])
        self.assertFalse(table["can_cancel"])

    async def test_waiting_duel_session_can_cancel(self):
        class WaitingConn(InboxConn):
            async def fetch(self, query, *args):
                if "FROM casino_games" in query:
                    return [
                        {
                            "game_id": "web-03e1",
                            "game_type": "baccara",
                            "status": "waiting",
                            "bet_rub": Decimal("100.00"),
                            "creator_id": 10,
                            "opponent_id": None,
                        }
                    ]
                return await super().fetch(query, *args)

        sessions = await list_sessions(WaitingConn(), 10)
        duel = next(row for row in sessions if row["kind"] == "duel")
        self.assertTrue(duel["can_cancel"])
        self.assertFalse(duel["can_leave"])

    async def test_stuck_demo_session_can_cancel(self):
        class DemoConn(InboxConn):
            async def fetch(self, query, *args):
                if "FROM casino_games" in query:
                    return [
                        {
                            "game_id": "web-demo-baccara-waiting",
                            "game_type": "baccara",
                            "status": "active",
                            "bet_rub": Decimal("50.00"),
                            "creator_id": 11,
                            "opponent_id": 10,
                            "rng_commit": None,
                            "counterparty_kind": "player",
                        }
                    ]
                return await super().fetch(query, *args)

        sessions = await list_sessions(DemoConn(), 10)
        duel = next(row for row in sessions if row["kind"] == "duel")
        self.assertTrue(duel["can_cancel"])
        self.assertEqual(duel["href"], "/casino/duels/web-demo-baccara-waiting")

    async def test_snapshot_renames_joiner_from_actor(self):
        conn = InboxConn()
        conn.rows = [
            {
                "id": 7,
                "event_type": EVENT_PLAYER_JOINED,
                "game_id": "g-duel",
                "href": "/casino/duels/g-duel",
                "title": "В игру зашли",
                "body": "Кубики · 50.00 ₽",
                "payload": {"actor_id": 20, "kind": "duel", "game_type": "pvp_dice"},
                "read_at": None,
                "created_at": datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
            }
        ]
        with patch(
            "casino_inbox.public_actors",
            new=AsyncMock(return_value={20: {"display_name": "Ира", "user_id": 20}}),
        ):
            snap = await inbox_snapshot(conn, 10)
        self.assertEqual(snap["unread"], 1)
        self.assertEqual(snap["items"][0]["title"], "Ира зашёл в игру")
        self.assertEqual(snap["items"][0]["href"], "/casino/duels/g-duel")
        self.assertTrue(any(row["kind"] == "duel" for row in snap["sessions"]))

    async def test_snapshot_rewrites_stale_v2_duels_href(self):
        conn = InboxConn()
        conn.rows = [
            {
                "id": 8,
                "event_type": EVENT_YOU_JOINED,
                "game_id": "web-stuck",
                "href": "/casino/duels/web-stuck",
                "title": "Вы зашли в игру",
                "body": "Кубики",
                "payload": {"actor_id": 10, "kind": "v2", "game_type": "pvp_dice"},
                "read_at": datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
                "created_at": datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
            }
        ]
        with patch("casino_inbox.public_actors", new=AsyncMock(return_value={})):
            snap = await inbox_snapshot(conn, 10)
        self.assertEqual(snap["items"][0]["href"], "/casino/tables/web-stuck")

    async def test_push_encodes_json_payload(self):
        conn = InboxConn()
        with patch("casino_inbox.publish_user"):
            await push_item(
                conn,
                recipient_id=1,
                event_type=EVENT_YOU_JOINED,
                game_id="x",
                href="/casino/duels/x",
                title="Вы зашли в игру",
                body="Кубики",
                payload={"actor_id": 1},
            )
        payload = json.loads(conn.inserted[0][6])
        self.assertEqual(payload["actor_id"], 1)


class RouteTests(unittest.TestCase):
    def test_inbox_href_helpers_are_wired(self):
        from casino_inbox import EVENT_YOU_JOINED, game_href

        self.assertEqual(EVENT_YOU_JOINED, "you_joined")
        self.assertTrue(game_href(kind="duel", game_id="x").startswith("/casino/duels/"))
        self.assertTrue(game_href(kind="v2", game_id="web-x").startswith("/casino/tables/"))


if __name__ == "__main__":
    unittest.main()
