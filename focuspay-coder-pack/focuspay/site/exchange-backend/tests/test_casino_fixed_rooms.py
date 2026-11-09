"""Fixed-stake rooms: HMAC winner, equal bet, concrete ruble settlement."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import inspect
import unittest

from fastapi import HTTPException

from casino_finance import money
from casino_fixed_rooms import (
    HMAC_ALGORITHM,
    RoomConfig,
    add_bot,
    bot_reel_id,
    cancel_room,
    commit_seed,
    create_room,
    fairness_message,
    hmac_index,
    join_room,
    make_server_seed,
    maybe_close_due,
    rake_split,
    snapshot,
    split_even,
    verify_hmac_round,
    _public_room,
    _seat_user,
)
from casino_weekly_wager import CASHBACK_GAME_TYPES


class UniqueViolationError(Exception):
    pass


class FakeRoomConn:
    def __init__(self):
        self.settings = {
            "enabled_games": {"fixed_room": True, "pvp_dice": True},
            "min_bet_rub": {"amount": 10},
            "max_bet_rub": {"amount": 100000},
            "fixed_room_rake_percent": {"percent": 5.0},
            "fixed_room_max_seats": {"value": 10},
            "fixed_room_collect_seconds": {"value": 600},
            "max_concurrent_games_per_player": {"value": 10},
        }
        self.rooms: list[dict] = []
        self.seats: list[dict] = []
        self.ledger: list[dict] = []
        self.house = Decimal("0.00")
        self.house_reserved = Decimal("0.00")
        self.house_ledger: list[dict] = []
        self.robots = [
            {
                "id": 1,
                "account_id": 1,
                "display_name": "Room Bot",
                "profile_key": "room-bot",
            }
        ]
        self.wallets: dict[int, Decimal] = {}
        self.holds: dict[str, tuple[int, Decimal]] = {}
        self.next_id = 1
        self.now = datetime.now(timezone.utc) - timedelta(seconds=1)

    def _op(self, query: str) -> str:
        text = query.lstrip()
        if text.startswith("/* room:"):
            return text[len("/* room:") :].split("*/", 1)[0].strip()
        if text.startswith("/* live:"):
            return "live:" + text[len("/* live:") :].split("*/", 1)[0].strip()
        return ""

    def _room(self, pk: int | None = None, room_id: str | None = None):
        for row in self.rooms:
            if pk is not None and int(row["id"]) == int(pk):
                return row
            if room_id is not None and row["room_id"] == room_id:
                return row
        return None

    async def fetch(self, query, *args):
        op = self._op(query)
        if "casino_player_cosmetics" in query:
            return []
        if op == "settings" or "FROM casino_settings" in query:
            return [{"key": key, "value": value} for key, value in self.settings.items()]
        if op == "seats":
            out = []
            for row in self.seats:
                if int(row["room_pk"]) != int(args[0]):
                    continue
                item = dict(row)
                item.setdefault("participant_kind", "player")
                robot_id = item.get("robot_profile_id")
                bot = next((r for r in self.robots if robot_id and int(r["id"]) == int(robot_id)), None)
                item["bot_name"] = bot["display_name"] if bot else None
                item["bot_key"] = bot["profile_key"] if bot else None
                out.append(item)
            return out
        if op == "list-open":
            return [
                dict(row)
                for row in self.rooms
                if row["status"] in {"open", "countdown", "locked"}
                or (row["status"] == "settled" and row.get("settled_at"))
            ][: int(args[0])]
        if op == "due":
            return [
                {"id": row["id"]}
                for row in self.rooms
                if row["status"] == "open" and row["closes_at"] <= self.now
            ]
        if op == "due-countdown":
            return [
                {"id": row["id"]}
                for row in self.rooms
                if row["status"] == "countdown"
                and row.get("countdown_ends_at") is not None
                and row["countdown_ends_at"] <= self.now
            ]
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        if (
            "casino_chat_presence" in query
            or "FROM bot_users" in query
            or "FROM web_users" in query
        ):
            return None
        op = self._op(query)
        if op in {"get"}:
            row = self._room(room_id=args[0])
            return dict(row) if row else None
        if op in {"get-pk", "lock-pk"}:
            row = self._room(pk=args[0])
            return dict(row) if row else None
        if op == "lock":
            row = self._room(room_id=args[0])
            return dict(row) if row else None
        if op == "insert":
            pk = self.next_id
            self.next_id += 1
            row = {
                "id": pk,
                "room_id": args[0],
                "status": "open",
                "creator_id": int(args[1]),
                "stake_rub": money(args[2]),
                "seat_count": int(args[3]),
                "commit_hash": args[4],
                "server_seed": args[5],
                "closes_at": args[6],
                "winner_id": None,
                "winner_index": None,
                "pot_rub": money(args[2]),
                "rake_rub": money(0),
                "payout_rub": money(0),
                "wager_json": {},
                "created_at": self.now,
                "locked_at": None,
                "settled_at": None,
                "countdown_ends_at": None,
            }
            self.rooms.append(row)
            return dict(row)
        if op == "live-seat":
            uid = int(args[0])
            for seat in self.seats:
                room = self._room(pk=int(seat["room_pk"]))
                seat_uid = seat.get("user_id")
                if seat_uid is None:
                    continue
                if room and int(seat_uid) == uid and room["status"] in {"open", "countdown", "locked"}:
                    return {"room_pk": room["id"], "room_id": room["room_id"]}
            return None
        if op == "house-ledger-get":
            for item in self.house_ledger:
                if item.get("entry_key") == args[0]:
                    return {"amount_rub": item["amount_rub"]}
            return None
        if op == "house":
            delta = money(args[0])
            nxt = money(self.house + delta)
            if nxt < 0:
                return None
            self.house = nxt
            return {"id": 1, "balance_rub": self.house}
        if op == "house-account":
            return {"id": 1, "balance_rub": self.house}
        if op == "house-ledger":
            if len(args) >= 5:
                entry_key, amount = args[1], args[2]
            else:
                entry_key, amount = args[0], args[1]
            self.house_ledger.append({"entry_key": entry_key, "amount_rub": money(amount)})
            return {"id": len(self.house_ledger)}
        if op == "bot-profile":
            return dict(self.robots[0]) if self.robots else None
        if op == "house-reserve":
            amount = money(args[0])
            if money(self.house) - money(self.house_reserved) < amount:
                return None
            self.house_reserved = money(self.house_reserved + amount)
            return {"id": 1}
        if op == "name" or op == "bot-name":
            return None
        if op == "credit":
            user_id, amount, order_id, note = args
            if any(item["order_id"] == order_id for item in self.ledger):
                return None
            row = {
                "user_id": int(user_id),
                "amount_rub": money(amount),
                "order_id": order_id,
                "note": note,
                "type": "accrual",
            }
            self.ledger.append(row)
            self.wallets[int(user_id)] = money(self.wallets.get(int(user_id), 0) + money(amount))
            return {"user_id": int(user_id), "amount_rub": money(amount)}
        if op == "credit-get":
            for item in self.ledger:
                if item["order_id"] == args[0]:
                    return {"user_id": item["user_id"], "amount_rub": item["amount_rub"]}
            return None
        if op == "live:concurrent-setting":
            return {"value": self.settings.get("max_concurrent_games_per_player", {"value": 10})}
        if op == "live:count-rooms":
            uid = int(args[0])
            n = 0
            for seat in self.seats:
                room = self._room(pk=int(seat["room_pk"]))
                if seat.get("user_id") is None or not room:
                    continue
                if int(seat["user_id"]) == uid and room["status"] in {"open", "countdown", "locked"}:
                    n += 1
            return {"n": n}
        if op in {"live:count-v2", "live:count-jackpot", "live:count-roulette"}:
            return {"n": 0}
        if "FROM casino_settings" in query:
            return None
        raise AssertionError(query)

    async def fetchval(self, query, *args):
        row = await self.fetchrow(query, *args)
        if row is None:
            return None
        if isinstance(row, dict):
            if "n" in row:
                return row["n"]
            if "value" in row:
                return row["value"]
            return next(iter(row.values()))
        return row

    async def execute(self, query, *args):
        if "pg_advisory_xact_lock" in query:
            return
        op = self._op(query)
        if op == "countdown":
            room = self._room(pk=args[0])
            room["status"] = "countdown"
            room["countdown_ends_at"] = args[1]
            return
        if op == "insert-seat":
            user_raw = args[1] if len(args) > 1 else None
            user_id = int(user_raw) if user_raw is not None else None
            seat_no = int(args[2]) if len(args) >= 3 else 0
            hold = args[3] if len(args) >= 4 else args[2]
            kind = str(args[4]) if len(args) > 4 else "player"
            robot_id = int(args[5]) if len(args) > 5 and args[5] is not None else None
            self.seats.append(
                {
                    "id": self.next_id,
                    "room_pk": int(args[0]),
                    "user_id": user_id,
                    "seat_no": seat_no,
                    "hold_order_ref": hold,
                    "participant_kind": kind,
                    "robot_profile_id": robot_id,
                }
            )
            self.next_id += 1
            return
        if op == "delete-seat":
            room_pk, seat_no = int(args[0]), int(args[1])
            self.seats = [
                row for row in self.seats if not (int(row["room_pk"]) == room_pk and int(row["seat_no"]) == seat_no)
            ]
            return
        if op == "set-pot":
            room = self._room(pk=args[0])
            room["pot_rub"] = money(args[1])
            return
        if op == "lock-set":
            room = self._room(pk=args[0])
            room["status"] = "locked"
            room["locked_at"] = self.now
            room["winner_id"] = int(args[1])
            room["winner_index"] = int(args[2])
            room["pot_rub"] = money(args[3])
            room["rake_rub"] = money(args[4])
            room["payout_rub"] = money(args[5])
            room["wager_json"] = args[6] if isinstance(args[6], dict) else __import__("json").loads(args[6])
            return
        if op == "settle":
            room = self._room(pk=args[0])
            room["status"] = "settled"
            room["settled_at"] = self.now
            return
        if op == "refund":
            room = self._room(pk=args[0])
            room["status"] = "refunded"
            room["settled_at"] = self.now
            return
        if op == "house":
            self.house = money(self.house + money(args[0]))
            return
        if op == "house-release":
            self.house_reserved = money(max(Decimal("0"), self.house_reserved - money(args[0])))
            return
        if op == "house-release-consume":
            amount = money(args[0])
            self.house_reserved = money(max(Decimal("0"), self.house_reserved - amount))
            self.house = money(self.house - amount)
            return
        if "casino_web_inbox" in query:
            return
        raise AssertionError(query)


class FixedRoomMathTests(unittest.TestCase):
    def test_four_players_100_rubles_rake_five_winner_gets_380(self):
        rake, payout = rake_split(Decimal("400"), Decimal("5"))
        self.assertEqual(rake, Decimal("20.00"))
        self.assertEqual(payout, Decimal("380.00"))

    def test_four_players_250_rake_five_winner_gets_950(self):
        rake, payout = rake_split(Decimal("1000"), Decimal("5"))
        self.assertEqual(rake, Decimal("50.00"))
        self.assertEqual(payout, Decimal("950.00"))

    def test_three_winners_split_570_is_190_each(self):
        parts = split_even(Decimal("570"), 3)
        self.assertEqual(parts, [Decimal("190.00"), Decimal("190.00"), Decimal("190.00")])
        self.assertEqual(sum(parts), Decimal("570.00"))

    def test_split_keeps_kopecks_on_first_share(self):
        parts = split_even(Decimal("100"), 3)
        self.assertEqual(sum(parts), Decimal("100.00"))
        self.assertEqual(parts[0], Decimal("33.34"))
        self.assertEqual(parts[1], Decimal("33.33"))
        self.assertEqual(parts[2], Decimal("33.33"))

    def test_hmac_commit_reveal_is_deterministic_and_tamper_fails(self):
        seed = "ab" * 32
        commit = commit_seed(seed)
        message = fairness_message("fr-abc", [11, 22, 33, 44])
        index = hmac_index(seed, message, 4)
        self.assertEqual(index, 1)
        ok = verify_hmac_round(seed=seed, commit=commit, message=message, modulus=4, expected_index=1)
        self.assertTrue(ok["matches"])
        self.assertEqual(ok["algorithm"], HMAC_ALGORITHM)
        bad = verify_hmac_round(seed="00" * 32, commit=commit, message=message, modulus=4)
        self.assertFalse(bad["commit_matches"])
        self.assertFalse(bad["matches"])

    def test_seed_is_64_hex_and_commit_is_sha256(self):
        seed = make_server_seed()
        self.assertEqual(len(seed), 64)
        self.assertEqual(len(commit_seed(seed)), 64)

    def test_weekly_wager_sql_includes_fixed_rooms(self):
        import casino_weekly_wager as weekly_mod

        src = inspect.getsource(weekly_mod)
        self.assertIn("fixed_room", CASHBACK_GAME_TYPES)
        self.assertIn("casino_fixed_room_rounds", src)
        self.assertIn("'fixed_room'", src)


class FixedRoomSettleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = FakeRoomConn()
        for uid in (1, 2, 3, 4):
            self.conn.wallets[uid] = Decimal("1000.00")
        self.reserve = patch("casino_fixed_rooms.reserve_unified_funds", self._reserve)
        self.confirm = patch("casino_fixed_rooms.confirm_unified_hold", self._confirm)
        self.bonus = patch("casino_level_bonus.maybe_grant_reached_level_bonuses", AsyncMock())
        self.reserve.start()
        self.confirm.start()
        self.bonus.start()

    async def asyncTearDown(self):
        self.reserve.stop()
        self.confirm.stop()
        self.bonus.stop()

    async def _reserve(self, conn, *, user_id, order_ref, amount_rub):
        amount = money(amount_rub)
        if conn.wallets.get(int(user_id), 0) < amount:
            raise ValueError("insufficient")
        conn.wallets[int(user_id)] = money(conn.wallets[int(user_id)] - amount)
        conn.holds[order_ref] = (int(user_id), amount)

    async def _confirm(self, conn, *, user_id, order_ref, amount_rub, note):
        return None

    async def test_full_room_credits_winner_380_and_house_20(self):
        created = await create_room(self.conn, user_id=1, stake_rub=Decimal("100"), seat_count=4)
        self.assertEqual(created["stake_rub"], 100.0)
        self.assertEqual(created["filled"], 1)
        self.assertIsNone(created["server_seed"])
        await join_room(self.conn, user_id=2, room_id=created["room_id"])
        await join_room(self.conn, user_id=3, room_id=created["room_id"])
        counting = await join_room(self.conn, user_id=4, room_id=created["room_id"])
        self.assertEqual(counting["status"], "countdown")
        self.assertIsNotNone(counting.get("countdown_ends_at"))
        self.conn.now = datetime.now(timezone.utc) + timedelta(seconds=30)
        await maybe_close_due(self.conn)
        settled = await snapshot(self.conn, created["room_id"], viewer_id=4)
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(settled["pot_rub"], 400.0)
        self.assertEqual(settled["rake_rub"], 20.0)
        self.assertEqual(settled["payout_rub"], 380.0)
        self.assertEqual(self.conn.house, Decimal("20.00"))
        self.assertTrue(any(item["entry_key"].startswith("room-rake-") for item in self.conn.house_ledger))
        winner = int(settled["winner_id"])
        self.assertEqual(self.conn.wallets[winner], Decimal("1280.00"))
        for uid in (1, 2, 3, 4):
            if uid != winner:
                self.assertEqual(self.conn.wallets[uid], Decimal("900.00"))
        self.assertEqual(sum(self.conn.wallets.values()) + self.conn.house, Decimal("4000.00"))
        wager = self.conn.rooms[0]["wager_json"]
        self.assertEqual(wager["1"], "100.00")
        self.assertEqual(wager["4"], "100.00")
        check = verify_hmac_round(
            seed=settled["server_seed"],
            commit=settled["commit_hash"],
            message=settled["hmac_message"],
            modulus=4,
            expected_index=settled["winner_index"],
        )
        self.assertTrue(check["matches"])

    async def test_join_rejects_wrong_when_disabled(self):
        self.conn.settings["enabled_games"] = {"fixed_room": False}
        with self.assertRaises(HTTPException) as raised:
            await create_room(self.conn, user_id=1, stake_rub=Decimal("100"), seat_count=2)
        self.assertEqual(raised.exception.status_code, 409)

    async def test_same_player_cannot_sit_twice(self):
        created = await create_room(self.conn, user_id=1, stake_rub=Decimal("50"), seat_count=3)
        again = await join_room(self.conn, user_id=1, room_id=created["room_id"])
        self.assertEqual(again["filled"], 1)
        self.assertEqual(self.conn.wallets[1], Decimal("950.00"))

    async def test_full_room_250_credits_winner_950_and_house_50(self):
        created = await create_room(self.conn, user_id=1, stake_rub=Decimal("250"), seat_count=4)
        await join_room(self.conn, user_id=2, room_id=created["room_id"])
        await join_room(self.conn, user_id=3, room_id=created["room_id"])
        counting = await join_room(self.conn, user_id=4, room_id=created["room_id"])
        self.assertEqual(counting["status"], "countdown")
        self.conn.now = datetime.now(timezone.utc) + timedelta(seconds=30)
        await maybe_close_due(self.conn)
        settled = await snapshot(self.conn, created["room_id"], viewer_id=4)
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(settled["pot_rub"], 1000.0)
        self.assertEqual(settled["rake_rub"], 50.0)
        self.assertEqual(settled["payout_rub"], 950.0)
        self.assertEqual(self.conn.house, Decimal("50.00"))
        winner = int(settled["winner_id"])
        self.assertEqual(self.conn.wallets[winner], Decimal("1700.00"))
        for uid in (1, 2, 3, 4):
            if uid != winner:
                self.assertEqual(self.conn.wallets[uid], Decimal("750.00"))
        self.assertEqual(sum(self.conn.wallets.values()) + self.conn.house, Decimal("4000.00"))
        check = verify_hmac_round(
            seed=settled["server_seed"],
            commit=settled["commit_hash"],
            message=settled["hmac_message"],
            modulus=4,
            expected_index=settled["winner_index"],
        )
        self.assertTrue(check["matches"])

    async def test_bots_fill_room_and_bot_winner_pays_house(self):
        self.conn.house = Decimal("10000.00")
        created = await create_room(self.conn, user_id=1, stake_rub=Decimal("250"), seat_count=2)
        counting = await add_bot(self.conn, user_id=1, room_id=created["room_id"])
        self.assertEqual(counting["status"], "countdown")
        self.conn.now = datetime.now(timezone.utc) + timedelta(seconds=30)
        await maybe_close_due(self.conn)
        settled = await snapshot(self.conn, created["room_id"], viewer_id=1)
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(settled["pot_rub"], 500.0)
        self.assertEqual(settled["payout_rub"], 475.0)
        self.assertEqual(settled["rake_rub"], 25.0)
        self.assertEqual(self.conn.house_reserved, Decimal("0.00"))
        winner = int(settled["winner_id"])
        if winner == 1:
            self.assertEqual(self.conn.wallets[1], Decimal("1225.00"))
            self.assertEqual(self.conn.house, Decimal("9775.00"))
        else:
            self.assertEqual(winner, bot_reel_id(1))
            self.assertEqual(self.conn.wallets[1], Decimal("750.00"))
            self.assertEqual(self.conn.house, Decimal("10250.00"))
        check = verify_hmac_round(
            seed=settled["server_seed"],
            commit=settled["commit_hash"],
            message=settled["hmac_message"],
            modulus=2,
            expected_index=settled["winner_index"],
        )
        self.assertTrue(check["matches"])

    async def test_second_bot_in_room_is_rejected(self):
        """Tournament rule: at most one bot per table, the rest must be live players."""
        self.conn.house = Decimal("10000.00")
        created = await create_room(self.conn, user_id=1, stake_rub=Decimal("250"), seat_count=4)
        await add_bot(self.conn, user_id=1, room_id=created["room_id"])
        with self.assertRaises(HTTPException) as ctx:
            await add_bot(self.conn, user_id=1, room_id=created["room_id"])
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_cancel_with_bots_releases_house_reserve(self):
        self.conn.house = Decimal("10000.00")
        created = await create_room(self.conn, user_id=1, stake_rub=Decimal("250"), seat_count=4)
        await add_bot(self.conn, user_id=1, room_id=created["room_id"])
        self.assertEqual(self.conn.house_reserved, Decimal("250.00"))
        cancelled = await cancel_room(self.conn, user_id=1, room_id=created["room_id"])
        self.assertEqual(cancelled["status"], "refunded")
        self.assertEqual(self.conn.wallets[1], Decimal("1000.00"))
        self.assertEqual(self.conn.house_reserved, Decimal("0.00"))
        self.assertEqual(self.conn.house, Decimal("10000.00"))

    async def test_player_can_sit_ten_rooms_eleventh_rejected(self):
        self.conn.wallets[1] = Decimal("10000.00")
        rooms = []
        for _ in range(10):
            rooms.append(await create_room(self.conn, user_id=1, stake_rub=Decimal("50"), seat_count=2))
        self.assertEqual(len(rooms), 10)
        with self.assertRaises(HTTPException) as raised:
            await create_room(self.conn, user_id=1, stake_rub=Decimal("50"), seat_count=2)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("10", str(raised.exception.detail))

    async def test_countdown_blocks_leave_until_settle(self):
        created = await create_room(self.conn, user_id=1, stake_rub=Decimal("100"), seat_count=2)
        counting = await join_room(self.conn, user_id=2, room_id=created["room_id"])
        self.assertEqual(counting["status"], "countdown")
        from casino_fixed_rooms import leave_room

        with self.assertRaises(HTTPException) as raised:
            await leave_room(self.conn, user_id=2, room_id=created["room_id"])
        self.assertEqual(raised.exception.status_code, 409)
        self.conn.now = datetime.now(timezone.utc) + timedelta(seconds=30)
        await maybe_close_due(self.conn)
        settled = await snapshot(self.conn, created["room_id"], viewer_id=1)
        self.assertEqual(settled["status"], "settled")


class WebClientRoomSeatTests(unittest.TestCase):
    def test_seat_user_keeps_negative_web_id(self):
        self.assertEqual(_seat_user({"user_id": -1, "participant_kind": "player"}), -1)
        self.assertIsNone(_seat_user({"user_id": -1, "seat_no": 0, "participant_kind": "bot"}))
        self.assertIsNone(_seat_user({"user_id": 0, "participant_kind": "player"}))
        self.assertEqual(_seat_user({"user_id": 42, "participant_kind": "player"}), 42)

    def test_public_room_shows_web_client_name_and_avatar(self):
        cfg = RoomConfig(
            enabled=True,
            max_seats=10,
            collect_seconds=600,
            rake_percent=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
        )
        row = {
            "room_id": "fr-web",
            "status": "open",
            "creator_id": -1,
            "commit_hash": "ab",
            "server_seed": "seed",
            "closes_at": None,
            "countdown_ends_at": None,
            "stake_rub": Decimal("250"),
            "seat_count": 3,
            "pot_rub": Decimal("250"),
            "rake_rub": None,
            "payout_rub": None,
            "winner_id": None,
            "winner_index": None,
        }
        seats = [{"user_id": -1, "seat_no": 0, "participant_kind": "player"}]
        actors = {
            -1: {
                "user_id": -1,
                "display_name": "Player 2",
                "initial": "P",
                "avatar_url": "/api/public/casino-idents/n1?v=3",
            }
        }
        snap = _public_room(row, seats, cfg, actors=actors, viewer_id=-1)
        player = snap["players"][0]
        self.assertEqual(player["user_id"], -1)
        self.assertEqual(player["display_name"], "Player 2")
        self.assertEqual(player["avatar_url"], "/api/public/casino-idents/n1?v=3")
        self.assertEqual(snap["my_seat"], 0)
        self.assertNotEqual(player["display_name"], "0")
