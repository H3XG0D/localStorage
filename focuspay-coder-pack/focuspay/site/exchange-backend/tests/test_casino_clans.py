"""Player clans: validation, cooldown, membership turnover, create/join/leave."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from fastapi import HTTPException

from casino_clans import (
    JOIN_COOLDOWN,
    aggregate_clan_wagers,
    create_clan,
    disband_clan,
    format_clan_display_name,
    join_clan,
    kick_member,
    leave_clan,
    list_top,
    my_clan,
    parse_invite_code,
    parse_name,
    parse_tag,
    rotate_invite,
    transfer_owner,
    utcnow,
    wager_belongs,
)
from casino_weekly_wager import CASHBACK_GAME_TYPES


def _dt(hours: float = 0) -> datetime:
    return datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc) + timedelta(hours=hours)


class ClanPureTests(unittest.TestCase):
    def test_tag_must_be_short_alnum(self):
        self.assertEqual(parse_tag("abc"), "ABC")
        with self.assertRaises(HTTPException) as short:
            parse_tag("ab")
        self.assertEqual(short.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            parse_tag("TOOLONG99")
        with self.assertRaises(HTTPException):
            parse_tag("ab_c")

    def test_name_strips_and_bounds(self):
        self.assertEqual(parse_name("  Focus  Pay  "), "Focus Pay")
        with self.assertRaises(HTTPException):
            parse_name("ab")

    def test_invite_code_strips_junk(self):
        self.assertEqual(parse_invite_code("ab-cd-ef"), "ABCDEF")
        with self.assertRaises(HTTPException):
            parse_invite_code("abc")

    def test_display_name_prefix_is_idempotent(self):
        self.assertEqual(format_clan_display_name("Иван", "ACE"), "[ACE] Иван")
        self.assertEqual(format_clan_display_name("[ACE] Иван", "ACE"), "[ACE] Иван")
        self.assertEqual(format_clan_display_name("Иван", None), "Иван")

    def test_wager_counts_only_while_member(self):
        joined = _dt(0)
        left = _dt(2)
        self.assertTrue(wager_belongs(settled_at=_dt(1), joined_at=joined, left_at=left))
        self.assertFalse(wager_belongs(settled_at=_dt(-0.1), joined_at=joined, left_at=left))
        self.assertFalse(wager_belongs(settled_at=left, joined_at=joined, left_at=left))
        self.assertTrue(wager_belongs(settled_at=_dt(3), joined_at=joined, left_at=None))

    def test_leave_does_not_erase_attributed_week_wager(self):
        wagers = [(7, Decimal("100"), _dt(1))]
        memberships = [(1, 7, _dt(0), _dt(2))]
        totals = aggregate_clan_wagers(wagers, memberships)
        self.assertEqual(totals[1], Decimal("100.00"))
        after_leave = aggregate_clan_wagers(wagers, memberships)
        self.assertEqual(after_leave[1], Decimal("100.00"))

    def test_join_after_settle_does_not_bring_old_wager(self):
        wagers = [(7, Decimal("500"), _dt(1))]
        memberships = [(2, 7, _dt(2), None)]
        self.assertEqual(aggregate_clan_wagers(wagers, memberships), {})

    def test_cashback_game_types_cover_jackpot_and_cards(self):
        self.assertIn("jackpot", CASHBACK_GAME_TYPES)
        self.assertIn("fixed_room", CASHBACK_GAME_TYPES)
        self.assertIn("clan_war", CASHBACK_GAME_TYPES)
        self.assertIn("pvp_dice", CASHBACK_GAME_TYPES)
        self.assertIn("holdem", CASHBACK_GAME_TYPES)


class MemoryClanConn:
    def __init__(self, *, enabled: bool = True, max_members: int = 20):
        self.enabled = enabled
        self.max_members = max_members
        self.clans: list[dict] = []
        self.members: list[dict] = []
        self.wagers: list[tuple[int, Decimal, datetime]] = []
        self.identities: dict[int, tuple[str | None, str | None]] = {}
        self.next_id = 1

    def _op(self, query: str) -> str:
        text = query.lstrip()
        if text.startswith("/* clan:"):
            return text[len("/* clan:") :].split("*/", 1)[0].strip()
        return ""

    async def fetch(self, query, *args):
        op = self._op(query)
        if op == "settings":
            return [
                {"key": "clans_enabled", "value": {"enabled": self.enabled}},
                {"key": "clan_max_members", "value": {"value": self.max_members}},
            ]
        if op == "identities":
            ids = list(args[0])
            rows = []
            for uid in ids:
                username, first = self.identities.get(int(uid), (None, None))
                rows.append({"user_id": int(uid), "username": username, "first_name": first})
            return rows
        if op == "members":
            clan_id = int(args[0])
            return [
                dict(row)
                for row in self.members
                if int(row["clan_id"]) == clan_id and row["left_at"] is None
            ]
        if op == "top":
            return self._top_rows(int(args[2]))
        if op == "member-wagers":
            clan_id = int(args[2])
            return self._member_wager_rows(clan_id)
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        op = self._op(query)
        if op == "active":
            uid = int(args[0])
            for member in self.members:
                if int(member["user_id"]) == uid and member["left_at"] is None:
                    clan = self._clan(int(member["clan_id"]))
                    if clan and clan["disbanded_at"] is None:
                        return {**member, **{k: clan[k] for k in ("tag", "name", "owner_id", "invite_code", "disbanded_at", "created_at")}}
            return None
        if op == "live-tag":
            row = await self.fetchrow("/* clan:active */ SELECT", args[0])
            return {"tag": row["tag"]} if row else None
        if op == "last-leave":
            uid = int(args[0])
            left = [m for m in self.members if int(m["user_id"]) == uid and m["left_at"] is not None]
            if not left:
                return None
            left.sort(key=lambda row: row["left_at"], reverse=True)
            return {"left_at": left[0]["left_at"]}
        if op == "get-tag":
            return next((dict(c) for c in self.clans if c["tag"] == args[0]), None)
        if op == "get-code":
            return next((dict(c) for c in self.clans if c["invite_code"] == args[0]), None)
        if op == "get-id":
            return self._clan(int(args[0]))
        if op == "count-live":
            clan_id = int(args[0])
            n = sum(1 for m in self.members if int(m["clan_id"]) == clan_id and m["left_at"] is None)
            return {"n": n}
        if op == "insert-clan":
            tag, name, owner_id, code = args
            if any(c["tag"] == tag for c in self.clans):
                raise UniqueViolationError()
            if any(c["invite_code"] == code for c in self.clans):
                raise UniqueViolationError()
            row = {
                "id": self.next_id,
                "tag": tag,
                "name": name,
                "owner_id": int(owner_id),
                "invite_code": code,
                "created_at": utcnow(),
                "disbanded_at": None,
            }
            self.next_id += 1
            self.clans.append(row)
            return dict(row)
        if op == "member-one":
            clan_id, uid = int(args[0]), int(args[1])
            for member in self.members:
                if int(member["clan_id"]) == clan_id and int(member["user_id"]) == uid and member["left_at"] is None:
                    return dict(member)
            return None
        raise AssertionError(query)

    async def execute(self, query, *args):
        op = self._op(query)
        if op == "insert-member":
            clan_id, uid, role_or_joined = args[0], args[1], args[2]
            if "role" in query and "'owner'" in query:
                role = "owner"
                joined = args[2]
            elif len(args) >= 3:
                # VALUES ($1, $2, 'owner'| 'member', $3)
                role = "owner" if "'owner'" in query else "member"
                joined = args[2]
            else:
                role = "member"
                joined = role_or_joined
            if any(m["user_id"] == int(uid) and m["left_at"] is None for m in self.members):
                raise UniqueViolationError()
            self.members.append(
                {
                    "clan_id": int(clan_id),
                    "user_id": int(uid),
                    "role": role,
                    "joined_at": joined,
                    "left_at": None,
                }
            )
            return "INSERT 1"
        if op == "close-member":
            clan_id, uid, left_at = int(args[0]), int(args[1]), args[2]
            for member in self.members:
                if int(member["clan_id"]) == clan_id and int(member["user_id"]) == uid and member["left_at"] is None:
                    member["left_at"] = left_at
            return "UPDATE"
        if op == "set-code":
            clan_id, code = int(args[0]), args[1]
            if any(c["invite_code"] == code and int(c["id"]) != clan_id for c in self.clans):
                raise UniqueViolationError()
            clan = self._clan(clan_id)
            if clan:
                clan["invite_code"] = code
            return "UPDATE"
        if op == "set-owner":
            clan = self._clan(int(args[0]))
            if clan:
                clan["owner_id"] = int(args[1])
            return "UPDATE"
        if op == "set-role":
            clan_id, uid = int(args[0]), int(args[1])
            role = "owner" if "'owner'" in query else "member"
            for member in self.members:
                if int(member["clan_id"]) == clan_id and int(member["user_id"]) == uid and member["left_at"] is None:
                    member["role"] = role
            return "UPDATE"
        if op == "disband-clan":
            clan = self._clan(int(args[0]))
            if clan and clan["disbanded_at"] is None:
                clan["disbanded_at"] = args[1]
            return "UPDATE"
        if op == "close-all":
            clan_id, left_at = int(args[0]), args[1]
            for member in self.members:
                if int(member["clan_id"]) == clan_id and member["left_at"] is None:
                    member["left_at"] = left_at
            return "UPDATE"
        raise AssertionError(query)

    def _clan(self, clan_id: int):
        for clan in self.clans:
            if int(clan["id"]) == int(clan_id):
                return clan
        return None

    def _top_rows(self, limit: int):
        memberships = [
            (int(m["clan_id"]), int(m["user_id"]), m["joined_at"], m["left_at"]) for m in self.members
        ]
        totals = aggregate_clan_wagers(self.wagers, memberships)
        rows = []
        for clan in self.clans:
            if clan["disbanded_at"] is not None:
                continue
            live = sum(1 for m in self.members if int(m["clan_id"]) == int(clan["id"]) and m["left_at"] is None)
            rows.append(
                {
                    "id": int(clan["id"]),
                    "tag": clan["tag"],
                    "name": clan["name"],
                    "owner_id": int(clan["owner_id"]),
                    "member_count": live,
                    "wager_rub": totals.get(int(clan["id"]), Decimal("0.00")),
                }
            )
        rows.sort(key=lambda row: (-float(row["wager_rub"]), row["tag"]))
        return rows[:limit]

    def _member_wager_rows(self, clan_id: int):
        memberships = [
            (int(m["clan_id"]), int(m["user_id"]), m["joined_at"], m["left_at"])
            for m in self.members
            if int(m["clan_id"]) == clan_id
        ]
        totals = aggregate_clan_wagers(self.wagers, memberships)
        by_user: dict[int, Decimal] = {}
        for _, user_id, joined_at, left_at in memberships:
            amount = Decimal("0.00")
            for wager_user, wager_amount, settled in self.wagers:
                if wager_user == user_id and wager_belongs(settled_at=settled, joined_at=joined_at, left_at=left_at):
                    amount += wager_amount
            by_user[user_id] = by_user.get(user_id, Decimal("0.00")) + amount
        _ = totals
        return [{"user_id": uid, "wager_rub": amount} for uid, amount in by_user.items()]


class UniqueViolationError(Exception):
    pass


class ClanFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_join_one_clan_and_cooldown(self):
        conn = MemoryClanConn()
        created = await create_clan(conn, user_id=1, tag="ace", name="Aces")
        self.assertEqual(created["tag"], "ACE")
        self.assertEqual(created["invite_code"], conn.clans[0]["invite_code"])
        joined = await join_clan(conn, user_id=2, code=created["invite_code"])
        self.assertEqual(joined["member_count"], 2)
        with self.assertRaises(HTTPException) as already:
            await create_clan(conn, user_id=2, tag="TWO", name="Twos")
        self.assertEqual(already.exception.status_code, 409)
        await leave_clan(conn, user_id=2)
        with self.assertRaises(HTTPException) as cool:
            await join_clan(conn, user_id=2, code=created["invite_code"])
        self.assertEqual(cool.exception.status_code, 409)
        self.assertIn("подождите", cool.exception.detail.lower())

    async def test_owner_cannot_leave_without_transfer_or_disband(self):
        conn = MemoryClanConn()
        await create_clan(conn, user_id=1, tag="ACE", name="Aces")
        with self.assertRaises(HTTPException) as owner:
            await leave_clan(conn, user_id=1)
        self.assertEqual(owner.exception.status_code, 409)
        code = conn.clans[0]["invite_code"]
        await join_clan(conn, user_id=2, code=code)
        transferred = await transfer_owner(conn, owner_id=1, target_id=2)
        self.assertEqual(transferred["owner_id"], 2)
        await leave_clan(conn, user_id=1)
        mine = await my_clan(conn, 1)
        self.assertIsNone(mine["clan"])

    async def test_kick_and_full_roster(self):
        conn = MemoryClanConn(max_members=2)
        created = await create_clan(conn, user_id=1, tag="ACE", name="Aces")
        await join_clan(conn, user_id=2, code=created["invite_code"])
        with self.assertRaises(HTTPException) as full:
            await join_clan(conn, user_id=3, code=created["invite_code"])
        self.assertEqual(full.exception.status_code, 409)
        kicked = await kick_member(conn, owner_id=1, target_id=2)
        self.assertEqual(kicked["member_count"], 1)

    async def test_disabled_flag_blocks_create_and_join(self):
        conn = MemoryClanConn(enabled=False)
        with self.assertRaises(HTTPException) as off:
            await create_clan(conn, user_id=1, tag="ACE", name="Aces")
        self.assertEqual(off.exception.status_code, 409)

    async def test_turnover_stays_after_leave(self):
        conn = MemoryClanConn()
        created = await create_clan(conn, user_id=1, tag="ACE", name="Aces")
        await join_clan(conn, user_id=2, code=created["invite_code"])
        joined_at = conn.members[1]["joined_at"]
        conn.wagers.append((2, Decimal("250.00"), joined_at))
        top = await list_top(conn)
        self.assertEqual(top["clans"][0]["wager_rub"], 250.0)
        await leave_clan(conn, user_id=2)
        top_after = await list_top(conn)
        self.assertEqual(top_after["clans"][0]["wager_rub"], 250.0)

    async def test_rotate_invite_and_disband(self):
        conn = MemoryClanConn()
        created = await create_clan(conn, user_id=1, tag="ACE", name="Aces")
        old = created["invite_code"]
        rotated = await rotate_invite(conn, owner_id=1)
        self.assertNotEqual(rotated["invite_code"], old)
        with self.assertRaises(HTTPException):
            await join_clan(conn, user_id=9, code=old)
        gone = await disband_clan(conn, actor_id=1)
        self.assertEqual(gone["disbanded_tag"], "ACE")
        mine = await my_clan(conn, 1)
        self.assertIsNone(mine["clan"])

    async def test_cooldown_constant_is_a_day(self):
        self.assertEqual(JOIN_COOLDOWN, timedelta(hours=24))


if __name__ == "__main__":
    unittest.main()
