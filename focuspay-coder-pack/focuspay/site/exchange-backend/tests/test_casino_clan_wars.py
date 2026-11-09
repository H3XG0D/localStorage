"""Clan wars: player-wallet stakes, HMAC clan winner, concrete ruble split."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import inspect
import json
import unittest

from fastapi import HTTPException

from casino_clan_wars import accept_war, create_war, join_war, war_message
from casino_clans import PLAYER_WAGER_SQL
from casino_finance import money
from casino_fixed_rooms import commit_seed, hmac_index, rake_split, split_even, verify_hmac_round
from casino_weekly_wager import CASHBACK_GAME_TYPES


class FakeWarConn:
    def __init__(self):
        self.settings = {
            "enabled_games": {"clan_war": True, "fixed_room": True},
            "min_bet_rub": {"amount": 10},
            "max_bet_rub": {"amount": 100000},
            "clan_war_rake_percent": {"percent": 5.0},
            "clan_war_max_fighters": {"value": 5},
            "clan_war_collect_seconds": {"value": 1800},
            "clans_enabled": {"enabled": True},
        }
        self.clans = [
            {"id": 1, "tag": "ACE", "name": "Aces", "disbanded_at": None},
            {"id": 2, "tag": "BOX", "name": "Boxers", "disbanded_at": None},
        ]
        self.members = [
            {"clan_id": 1, "user_id": 1, "role": "owner", "left_at": None},
            {"clan_id": 1, "user_id": 2, "role": "member", "left_at": None},
            {"clan_id": 2, "user_id": 3, "role": "owner", "left_at": None},
            {"clan_id": 2, "user_id": 4, "role": "member", "left_at": None},
        ]
        self.wars: list[dict] = []
        self.fighters: list[dict] = []
        self.ledger: list[dict] = []
        self.house = Decimal("0.00")
        self.wallets: dict[int, Decimal] = {}
        self.next_id = 10
        self.now = datetime.now(timezone.utc) - timedelta(seconds=1)

    def _op(self, query: str) -> str:
        text = query.lstrip()
        if text.startswith("/* war:"):
            return "war:" + text[len("/* war:") :].split("*/", 1)[0].strip()
        if text.startswith("/* clan:"):
            return "clan:" + text[len("/* clan:") :].split("*/", 1)[0].strip()
        return ""

    def _war(self, pk: int | None = None, war_id: str | None = None):
        for row in self.wars:
            if pk is not None and int(row["id"]) == int(pk):
                return row
            if war_id is not None and row["war_id"] == war_id:
                return row
        return None

    def _clan(self, clan_id: int):
        for row in self.clans:
            if int(row["id"]) == int(clan_id) and row["disbanded_at"] is None:
                return row
        return None

    async def fetch(self, query, *args):
        op = self._op(query)
        if "casino_player_cosmetics" in query:
            return []
        if op in {"war:settings"} or "FROM casino_settings" in query:
            return [{"key": key, "value": value} for key, value in self.settings.items()]
        if op == "war:fighters":
            return [dict(row) for row in self.fighters if int(row["war_pk"]) == int(args[0])]
        if op == "war:list-open":
            return [dict(row) for row in self.wars if row["status"] in {"open", "accepted"}][: int(args[0])]
        if op == "war:due":
            return [
                {"id": row["id"]}
                for row in self.wars
                if row["status"] in {"open", "accepted"} and row["closes_at"] <= self.now
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
        if op == "clan:active":
            uid = int(args[0])
            for member in self.members:
                if int(member["user_id"]) == uid and member["left_at"] is None:
                    clan = self._clan(int(member["clan_id"]))
                    if clan:
                        return {**member, **clan}
            return None
        if op == "war:clan":
            clan = self._clan(int(args[0]))
            return dict(clan) if clan else None
        if op == "war:get":
            row = self._war(war_id=args[0])
            return dict(row) if row else None
        if op in {"war:get-pk", "war:lock-pk"}:
            row = self._war(pk=args[0])
            return dict(row) if row else None
        if op == "war:lock":
            row = self._war(war_id=args[0])
            return dict(row) if row else None
        if op == "war:insert":
            pk = self.next_id
            self.next_id += 1
            row = {
                "id": pk,
                "war_id": args[0],
                "status": "open",
                "creator_id": int(args[1]),
                "challenger_clan_id": int(args[2]),
                "opponent_clan_id": None,
                "stake_rub": money(args[3]),
                "fighters_needed": int(args[4]),
                "commit_hash": args[5],
                "server_seed": args[6],
                "closes_at": args[7],
                "winner_clan_id": None,
                "winner_index": None,
                "pot_rub": money(args[3]),
                "rake_rub": money(0),
                "payout_per_winner_rub": money(0),
                "wager_json": {},
                "created_at": self.now,
                "accepted_at": None,
                "locked_at": None,
                "settled_at": None,
            }
            self.wars.append(row)
            return dict(row)
        if op == "war:live-fight":
            uid = int(args[0])
            for fighter in self.fighters:
                war = self._war(pk=int(fighter["war_pk"]))
                if war and int(fighter["user_id"]) == uid and war["status"] in {"open", "accepted", "locked"}:
                    return {"war_pk": war["id"], "war_id": war["war_id"]}
            return None
        if op in {"war:name", "war:bot-name"}:
            return None
        if op == "war:credit":
            user_id, amount, order_id, note = args
            if any(item["order_id"] == order_id for item in self.ledger):
                return None
            row = {
                "user_id": int(user_id),
                "amount_rub": money(amount),
                "order_id": order_id,
                "note": note,
            }
            self.ledger.append(row)
            self.wallets[int(user_id)] = money(self.wallets.get(int(user_id), 0) + money(amount))
            return {"user_id": int(user_id), "amount_rub": money(amount)}
        if op == "war:credit-get":
            for item in self.ledger:
                if item["order_id"] == args[0]:
                    return {"user_id": item["user_id"], "amount_rub": item["amount_rub"]}
            return None
        raise AssertionError(query)

    async def execute(self, query, *args):
        op = self._op(query)
        if op == "war:insert-fighter":
            self.fighters.append(
                {
                    "id": self.next_id,
                    "war_pk": int(args[0]),
                    "clan_id": int(args[1]),
                    "user_id": int(args[2]),
                    "hold_order_ref": args[3],
                    "created_at": self.now,
                }
            )
            self.next_id += 1
            return
        if op == "war:accept":
            war = self._war(pk=args[0])
            war["status"] = "accepted"
            war["opponent_clan_id"] = int(args[1])
            war["accepted_at"] = self.now
            war["pot_rub"] = money(war["pot_rub"] + money(args[2]))
            return
        if op == "war:set-pot":
            war = self._war(pk=args[0])
            war["pot_rub"] = money(war["pot_rub"] + money(args[1]))
            return
        if op == "war:lock-set":
            war = self._war(pk=args[0])
            war["status"] = "locked"
            war["locked_at"] = self.now
            war["winner_clan_id"] = int(args[1])
            war["winner_index"] = int(args[2])
            war["pot_rub"] = money(args[3])
            war["rake_rub"] = money(args[4])
            war["payout_per_winner_rub"] = money(args[5])
            war["wager_json"] = args[6] if isinstance(args[6], dict) else json.loads(args[6])
            return
        if op == "war:settle":
            war = self._war(pk=args[0])
            war["status"] = "settled"
            war["settled_at"] = self.now
            return
        if op == "war:refund":
            war = self._war(pk=args[0])
            war["status"] = "refunded"
            war["settled_at"] = self.now
            return
        if op == "war:house":
            self.house = money(self.house + money(args[0]))
            return
        if "casino_web_inbox" in query:
            return
        raise AssertionError(query)


class ClanWarMathTests(unittest.TestCase):
    def test_two_v_two_at_50_rake_10_each_winner_95(self):
        rake, payout = rake_split(Decimal("200"), Decimal("5"))
        self.assertEqual(rake, Decimal("10.00"))
        self.assertEqual(payout, Decimal("190.00"))
        shares = split_even(payout, 2)
        self.assertEqual(shares, [Decimal("95.00"), Decimal("95.00")])

    def test_hmac_picks_clan_zero_or_one(self):
        seed = "cd" * 32
        message = war_message("cw-1", 1, 2, [1, 2], [3, 4])
        index = hmac_index(seed, message, 2)
        self.assertIn(index, (0, 1))
        self.assertEqual(index, 0)
        ok = verify_hmac_round(
            seed=seed,
            commit=commit_seed(seed),
            message=message,
            modulus=2,
            expected_index=0,
        )
        self.assertTrue(ok["matches"])

    def test_weekly_wager_counts_clan_war_json(self):
        import casino_weekly_wager as weekly_mod

        src = inspect.getsource(weekly_mod)
        self.assertIn("clan_war", CASHBACK_GAME_TYPES)
        self.assertIn("casino_clan_wars", src)
        self.assertIn("casino_clan_wars", PLAYER_WAGER_SQL)
        self.assertIn("casino_fixed_room_rounds", PLAYER_WAGER_SQL)

    def test_no_clan_bank_in_module_source(self):
        import casino_clan_wars
        import casino_clans

        self.assertNotIn("clan_balance", inspect.getsource(casino_clan_wars))
        self.assertNotIn("treasury", inspect.getsource(casino_clan_wars))
        self.assertIn("No clan wallet", casino_clans.__doc__)


class ClanWarSettleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = FakeWarConn()
        for uid in (1, 2, 3, 4):
            self.conn.wallets[uid] = Decimal("1000.00")
        self.reserve = patch("casino_clan_wars.reserve_unified_funds", self._reserve)
        self.confirm = patch("casino_clan_wars.confirm_unified_hold", self._confirm)
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

    async def _confirm(self, conn, *, user_id, order_ref, amount_rub, note):
        return None

    async def test_two_v_two_settles_from_player_wallets(self):
        created = await create_war(self.conn, user_id=1, stake_rub=Decimal("50"), fighters_needed=2)
        self.assertEqual(created["status"], "open")
        self.assertIsNone(created["opponent"])
        await join_war(self.conn, user_id=2, war_id=created["war_id"])
        await accept_war(self.conn, user_id=3, war_id=created["war_id"])
        settled = await join_war(self.conn, user_id=4, war_id=created["war_id"])
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(settled["pot_rub"], 200.0)
        self.assertEqual(settled["rake_rub"], 10.0)
        self.assertEqual(settled["payout_per_winner_rub"], 95.0)
        self.assertEqual(self.conn.house, Decimal("10.00"))
        winner_clan = int(settled["winner_clan_id"])
        winners = (1, 2) if winner_clan == 1 else (3, 4)
        losers = (3, 4) if winner_clan == 1 else (1, 2)
        for uid in winners:
            self.assertEqual(self.conn.wallets[uid], Decimal("1045.00"))
        for uid in losers:
            self.assertEqual(self.conn.wallets[uid], Decimal("950.00"))
        self.assertEqual(sum(self.conn.wallets.values()) + self.conn.house, Decimal("4000.00"))
        wager = self.conn.wars[0]["wager_json"]
        self.assertEqual(wager["1"], "50.00")
        self.assertEqual(wager["4"], "50.00")
        check = verify_hmac_round(
            seed=settled["server_seed"],
            commit=settled["commit_hash"],
            message=settled["hmac_message"],
            modulus=2,
            expected_index=settled["winner_index"],
        )
        self.assertTrue(check["matches"])

    async def test_cannot_accept_own_clan(self):
        created = await create_war(self.conn, user_id=1, stake_rub=Decimal("50"), fighters_needed=1)
        with self.assertRaises(HTTPException) as raised:
            await accept_war(self.conn, user_id=2, war_id=created["war_id"])
        self.assertEqual(raised.exception.status_code, 409)

    async def test_outsider_cannot_join(self):
        self.conn.members.append({"clan_id": 99, "user_id": 9, "role": "owner", "left_at": None})
        self.conn.clans.append({"id": 99, "tag": "ZZZ", "name": "Out", "disbanded_at": None})
        self.conn.wallets[9] = Decimal("1000.00")
        created = await create_war(self.conn, user_id=1, stake_rub=Decimal("50"), fighters_needed=1)
        await accept_war(self.conn, user_id=3, war_id=created["war_id"])
        # 1v1 already settles on accept if both sides have 1 fighter
        self.assertEqual(self.conn.wars[0]["status"], "settled")
        created2 = await create_war(self.conn, user_id=2, stake_rub=Decimal("50"), fighters_needed=2)
        with self.assertRaises(HTTPException) as raised:
            await join_war(self.conn, user_id=9, war_id=created2["war_id"])
        self.assertEqual(raised.exception.status_code, 409)

    async def test_clan_create_still_requires_membership_not_bank(self):
        self.conn.members = [row for row in self.conn.members if int(row["user_id"]) != 1]
        with self.assertRaises(HTTPException) as raised:
            await create_war(self.conn, user_id=1, stake_rub=Decimal("50"), fighters_needed=1)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("команде", raised.exception.detail)
