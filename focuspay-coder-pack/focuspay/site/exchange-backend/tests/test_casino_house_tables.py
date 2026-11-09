"""House-multi dice: per-seat house settlement, no shared pot, bots debit 0 ₽."""
from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from casino_finance import calculate_equal_stake_settlement, calculate_house_settlement
from casino_house_tables import (
    CUB_HMAC_MESSAGE_TEMPLATE,
    GAME_TYPE,
    HOUSE_BOT_SEAT_BASE,
    HOUSE_MONEY_GAME,
    MAX_HUMANS,
    MIN_HUMANS,
    MIN_START_HUMANS,
    HouseSeatSpec,
    after_reroll_multiplier,
    as_seat,
    build_snapshot,
    canvas_dice,
    compare_dice,
    create_table,
    cub_hmac_outcome,
    expire_open_unjoined,
    expire_pending_choices,
    face_max_multiplier,
    house_bot_die_pips,
    house_bot_wallet_debit,
    human_seats,
    is_solo_table,
    leave,
    list_open_tables,
    next_human_seat_no,
    payout_for_multiplier,
    play_human_cub,
    player_die_pips,
    public_table_card,
    reroll_win_multiplier,
    resolve_round,
    seat_house_settlement,
    sit,
    snapshot,
    start_round,
    table_settlements,
    table_win_reserve,
    take_multiplier,
    uses_face_money,
    validate_house_bot_count,
    validate_max_seats,
    validate_roster_for_start,
    v2_equal_stake_payout,
)


class _RecordLike:
    """asyncpg.Record stand-in: has []/get but is not collections.abc.Mapping."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)


def _player(seat_no: int, uid: int, stake: str, **kwargs) -> HouseSeatSpec:
    return HouseSeatSpec(
        seat_no=seat_no,
        kind="player",
        telegram_id=uid,
        stake_rub=Decimal(stake),
        display_name=kwargs.get("display_name", f"P{uid}"),
        player_pips=kwargs.get("player_pips"),
        house_pips=kwargs.get("house_pips"),
        payout_rub=kwargs.get("payout_rub"),
        won=kwargs.get("won"),
    )


def _bot(seat_no: int = HOUSE_BOT_SEAT_BASE, **kwargs) -> HouseSeatSpec:
    return HouseSeatSpec(
        seat_no=seat_no,
        kind="house_robot",
        telegram_id=None,
        stake_rub=Decimal("0.00"),
        display_name=kwargs.get("display_name", "Казино"),
        profile_key=kwargs.get("profile_key", "house-dice"),
        house_pips=kwargs.get("house_pips"),
    )


class RosterTests(unittest.TestCase):
    def test_table_is_1_to_6_humans(self):
        self.assertEqual(validate_max_seats(1), 1)
        self.assertEqual(validate_max_seats(2), 2)
        self.assertEqual(validate_max_seats(6), 6)
        with self.assertRaises(HTTPException) as too_few:
            validate_max_seats(0)
        self.assertEqual(too_few.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            validate_max_seats(7)
        self.assertEqual(MIN_HUMANS, 1)
        self.assertEqual(MIN_START_HUMANS, 1)
        self.assertEqual(MAX_HUMANS, 6)

    def test_is_solo_table_accepts_int_dict_and_asyncpg_record_like(self):
        self.assertTrue(is_solo_table(1))
        self.assertFalse(is_solo_table(2))
        self.assertTrue(is_solo_table({"max_seats": 1}))
        self.assertFalse(is_solo_table({"max_seats": 4}))
        self.assertTrue(is_solo_table(_RecordLike({"max_seats": 1, "table_id": "ht-x"})))
        self.assertFalse(is_solo_table(_RecordLike({"max_seats": 3})))

    def test_start_accepts_one_human_and_rejects_zero_or_seven(self):
        seats = validate_roster_for_start([_player(1, 10, "100.00")])
        self.assertEqual(len(human_seats(seats)), 1)
        web = validate_roster_for_start([_player(1, -3, "100.00")])
        self.assertEqual(web[0].telegram_id, -3)
        with self.assertRaises(HTTPException) as missing:
            validate_roster_for_start(
                [
                    HouseSeatSpec(
                        seat_no=1,
                        kind="player",
                        telegram_id=None,
                        stake_rub=Decimal("100.00"),
                    )
                ]
            )
        self.assertEqual(missing.exception.status_code, 409)
        self.assertEqual(missing.exception.detail, "У игрока нет id")
        with self.assertRaises(HTTPException) as empty:
            validate_roster_for_start([_bot()])
        self.assertEqual(empty.exception.status_code, 409)
        seven = [_player(n, 100 + n, "50.00") for n in range(1, 8)]
        with self.assertRaises(HTTPException):
            validate_roster_for_start(seven)

    def test_start_accepts_two_humans_and_several_house_bots(self):
        seats = validate_roster_for_start(
            [
                _player(1, 11, "100.00"),
                _player(2, 12, "250.00"),
                _bot(11),
                _bot(12, display_name="Дом-2"),
            ]
        )
        self.assertEqual(len(human_seats(seats)), 2)
        self.assertEqual(house_bot_wallet_debit(seats[2]), Decimal("0.00"))
        self.assertEqual(house_bot_wallet_debit(seats[3]), Decimal("0.00"))

    def test_house_bot_cannot_carry_a_user_stake(self):
        with self.assertRaises(HTTPException) as err:
            validate_roster_for_start(
                [
                    _player(1, 1, "100.00"),
                    _player(2, 2, "100.00"),
                    HouseSeatSpec(
                        seat_no=11,
                        kind="house_robot",
                        telegram_id=None,
                        stake_rub=Decimal("50.00"),
                    ),
                ]
            )
        self.assertEqual(err.exception.status_code, 409)

    def test_next_free_human_seat(self):
        self.assertEqual(next_human_seat_no([], 4), 1)
        self.assertEqual(next_human_seat_no([1, 2], 4), 3)
        with self.assertRaises(HTTPException):
            next_human_seat_no([1, 2, 3, 4], 4)

    def test_bot_count_bounds(self):
        self.assertEqual(validate_house_bot_count(0), 0)
        self.assertEqual(validate_house_bot_count(3), 3)
        with self.assertRaises(HTTPException):
            validate_house_bot_count(7)


class HouseMoneyTests(unittest.TestCase):
    def test_win_100_at_5_percent_pays_195(self):
        won = seat_house_settlement(Decimal("100.00"), won=True, commission_rate=Decimal("5"))
        self.assertEqual(won.payout_rub, Decimal("195.00"))
        self.assertEqual(won.commission_rub, Decimal("5.00"))
        self.assertEqual(won.house_delta_rub, Decimal("-95.00"))
        self.assertEqual(won.stake_rub, Decimal("100.00"))
        cub = calculate_house_settlement(Decimal("100"), Decimal("2"), Decimal("5"))
        self.assertEqual(won.payout_rub, cub.payout)
        self.assertEqual(won.commission_rub, cub.commission)

    def test_loss_100_pays_0_house_keeps_100(self):
        lost = seat_house_settlement(Decimal("100.00"), won=False, commission_rate=Decimal("5"))
        self.assertEqual(lost.payout_rub, Decimal("0.00"))
        self.assertEqual(lost.commission_rub, Decimal("0.00"))
        self.assertEqual(lost.house_delta_rub, Decimal("100.00"))

    def test_win_100_at_15_percent_pays_185(self):
        won = seat_house_settlement(Decimal("100.00"), won=True, commission_rate=Decimal("15"))
        self.assertEqual(won.payout_rub, Decimal("185.00"))
        self.assertEqual(won.commission_rub, Decimal("15.00"))

    def test_win_250_at_5_percent_pays_487_50(self):
        won = seat_house_settlement(Decimal("250.00"), won=True, commission_rate=Decimal("5"))
        self.assertEqual(won.payout_rub, Decimal("487.50"))
        self.assertEqual(won.commission_rub, Decimal("12.50"))
        self.assertEqual(won.house_delta_rub, Decimal("-237.50"))

    def test_three_bots_win_100_at_x4_pays_385(self):
        won = seat_house_settlement(
            Decimal("100.00"),
            won=True,
            payout_multiplier=Decimal("4"),
            commission_rate=Decimal("5"),
        )
        self.assertEqual(won.payout_rub, Decimal("385.00"))
        self.assertEqual(won.commission_rub, Decimal("15.00"))
        cub = calculate_house_settlement(Decimal("100"), Decimal("4"), Decimal("5"))
        self.assertEqual(won.payout_rub, cub.payout)

    def test_two_humans_settle_separately_not_v2_pot(self):
        rows = table_settlements(
            [(Decimal("100.00"), True), (Decimal("100.00"), False)],
            commission_rate=Decimal("5"),
        )
        self.assertEqual(rows[0].payout_rub, Decimal("195.00"))
        self.assertEqual(rows[1].payout_rub, Decimal("0.00"))
        self.assertEqual(money_sum(rows), Decimal("195.00"))
        v2 = v2_equal_stake_payout(Decimal("100.00"), Decimal("5"))
        self.assertEqual(v2, Decimal("195.00"))
        both_win = table_settlements(
            [(Decimal("100.00"), True), (Decimal("100.00"), True)],
            commission_rate=Decimal("5"),
        )
        self.assertEqual(both_win[0].payout_rub, Decimal("195.00"))
        self.assertEqual(both_win[1].payout_rub, Decimal("195.00"))
        self.assertEqual(money_sum(both_win), Decimal("390.00"))
        self.assertNotEqual(money_sum(both_win), v2)
        v2_15 = calculate_equal_stake_settlement(Decimal("100"), Decimal("15"))
        mixed_15 = table_settlements(
            [(Decimal("100.00"), True), (Decimal("100.00"), False)],
            commission_rate=Decimal("15"),
        )
        self.assertEqual(mixed_15[0].payout_rub, Decimal("185.00"))
        self.assertEqual(mixed_15[1].payout_rub, Decimal("0.00"))
        self.assertEqual(v2_15.payout, Decimal("185.00"))
        self.assertEqual(v2_15.pot, Decimal("200.00"))
        self.assertNotEqual(mixed_15[0].payout_rub + mixed_15[1].payout_rub, v2_15.pot)

    def test_unequal_stakes_are_not_pooled(self):
        rows = table_settlements(
            [(Decimal("100.00"), True), (Decimal("250.00"), True)],
            commission_rate=Decimal("5"),
        )
        self.assertEqual(rows[0].payout_rub, Decimal("195.00"))
        self.assertEqual(rows[1].payout_rub, Decimal("487.50"))
        self.assertEqual(money_sum(rows), Decimal("682.50"))
        reserve = table_win_reserve(
            [Decimal("100.00"), Decimal("250.00")],
            commission_rate=Decimal("5"),
        )
        self.assertEqual(reserve, Decimal("682.50"))

    def test_house_bots_do_not_enter_reserve(self):
        humans = [Decimal("100.00"), Decimal("50.00")]
        reserve = table_win_reserve(humans, commission_rate=Decimal("5"))
        self.assertEqual(reserve, Decimal("292.50"))
        self.assertEqual(house_bot_wallet_debit(_bot()), Decimal("0.00"))

    def test_loss_multiplier_is_zero_same_as_cub(self):
        cub_loss = calculate_house_settlement(Decimal("80"), Decimal("0"), Decimal("5"))
        seat = seat_house_settlement(Decimal("80.00"), won=False, commission_rate=Decimal("5"))
        self.assertEqual(seat.payout_rub, Decimal("0.00"))
        self.assertEqual(seat.payout_rub, cub_loss.payout)
        self.assertEqual(cub_loss.house_delta, Decimal("80.00"))


class FaceCompareTests(unittest.TestCase):
    def test_six_beats_two_and_five_ties_six(self):
        got = compare_dice(6, [(11, 2), (12, 5), (13, 6)])
        self.assertEqual(got.wins, 2)
        self.assertEqual(got.ties, 1)
        self.assertEqual(got.losses, 0)
        self.assertEqual(got.kind, "choice")
        self.assertEqual(got.win_seats, (11, 12))
        self.assertEqual(got.tie_seats, (13,))

    def test_take_two_wins_pays_290(self):
        self.assertEqual(take_multiplier(2), Decimal("3"))
        take = payout_for_multiplier(Decimal("100"), take_multiplier(2))
        self.assertEqual(take.payout_rub, Decimal("290.00"))
        self.assertEqual(take.commission_rub, Decimal("10.00"))
        self.assertTrue(take.won)

    def test_reroll_win_two_locked_one_fresh_pays_765(self):
        self.assertEqual(reroll_win_multiplier(2, 1), Decimal("8"))
        won = payout_for_multiplier(Decimal("100"), reroll_win_multiplier(2, 1))
        self.assertEqual(won.payout_rub, Decimal("765.00"))
        self.assertEqual(won.commission_rub, Decimal("35.00"))

    def test_leftover_ties_after_reroll_pay_take_of_locked_plus_new(self):
        leftover = compare_dice(6, [(13, 6)])
        self.assertEqual(leftover.ties, 1)
        self.assertEqual(leftover.wins, 0)
        self.assertEqual(after_reroll_multiplier(2, leftover), Decimal("3"))
        paid = payout_for_multiplier(Decimal("100"), after_reroll_multiplier(2, leftover))
        self.assertEqual(paid.payout_rub, Decimal("290.00"))

    def test_lose_to_any_one_is_zero(self):
        lost = compare_dice(6, [(11, 2), (12, 5), (13, 6)])
        self.assertEqual(lost.kind, "choice")
        beaten = compare_dice(3, [(11, 2), (12, 5), (13, 6)])
        self.assertEqual(beaten.kind, "loss")
        self.assertEqual(after_reroll_multiplier(2, compare_dice(3, [(13, 6)])), Decimal("0"))
        paid = payout_for_multiplier(Decimal("100"), Decimal("0"))
        self.assertEqual(paid.payout_rub, Decimal("0.00"))
        self.assertFalse(paid.won)

    def test_all_ties_take_is_push_100(self):
        self.assertEqual(take_multiplier(0), Decimal("1"))
        push = payout_for_multiplier(Decimal("100"), Decimal("1"))
        self.assertEqual(push.payout_rub, Decimal("100.00"))
        self.assertEqual(push.commission_rub, Decimal("0.00"))
        self.assertFalse(push.won)

    def test_beat_all_three_is_x4_385(self):
        won = compare_dice(6, [(11, 1), (12, 2), (13, 4)])
        self.assertEqual(won.kind, "win")
        self.assertEqual(take_multiplier(3), Decimal("4"))
        paid = payout_for_multiplier(Decimal("100"), take_multiplier(3))
        self.assertEqual(paid.payout_rub, Decimal("385.00"))

    def test_face_money_only_solo_two_to_six_bots(self):
        self.assertTrue(uses_face_money({"max_seats": 1, "house_bot_count": 2}))
        self.assertTrue(uses_face_money({"max_seats": 1, "house_bot_count": 6}))
        self.assertFalse(uses_face_money({"max_seats": 1, "house_bot_count": 1}))
        self.assertFalse(uses_face_money({"max_seats": 4, "house_bot_count": 3}))
        self.assertEqual(face_max_multiplier(3), Decimal("8"))
        a = player_die_pips("seed", "ht-x", 1, 0)
        self.assertEqual(a, player_die_pips("seed", "ht-x", 1, 0))
        self.assertGreaterEqual(a, 1)
        self.assertLessEqual(a, 6)


def money_sum(rows) -> Decimal:
    total = Decimal("0.00")
    for row in rows:
        total += row.payout_rub
    return total


class HmacCubUnchangedTests(unittest.TestCase):
    def test_message_is_game_id_colon_nonce(self):
        self.assertEqual(CUB_HMAC_MESSAGE_TEMPLATE, "{game_id}:{nonce}")
        seed = "ab" * 32
        game_id = "cub-lock-1"
        nonce = 0
        got = cub_hmac_outcome(seed, game_id, nonce, Decimal("0.5"))
        message = f"{game_id}:{nonce}"
        digest = hmac.new(seed.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
        digest_value = int.from_bytes(digest.digest(), "big")
        threshold = int((Decimal("0.5") * Decimal(1 << 256)).to_integral_value())
        self.assertEqual(got["message"], message)
        self.assertEqual(got["digest_hex"], digest.hexdigest())
        self.assertEqual(got["digest_value"], digest_value)
        self.assertEqual(got["won"], digest_value < threshold)
        self.assertNotIn("client_seed", got["message"])

    def test_house_bot_die_is_one_to_six_and_stable(self):
        first = house_bot_die_pips("seed", "ht-aaa", 11, 0)
        second = house_bot_die_pips("seed", "ht-aaa", 11, 0)
        other = house_bot_die_pips("seed", "ht-aaa", 12, 0)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 1)
        self.assertLessEqual(first, 6)
        self.assertGreaterEqual(other, 1)
        self.assertLessEqual(other, 6)


class CanvasTests(unittest.TestCase):
    def test_n_player_dice_plus_house_dice(self):
        dice = canvas_dice(
            [
                _player(1, 11, "100.00", player_pips=6, house_pips=2, won=True),
                _player(2, 12, "50.00", player_pips=1, house_pips=5, won=False),
                _bot(11, house_pips=4),
                _bot(12, house_pips=3, display_name="Дом-2"),
            ]
        )
        self.assertEqual(len(dice["players"]), 2)
        self.assertEqual(len(dice["house"]), 2)
        self.assertEqual(dice["players"][0]["pips"], 6)
        self.assertEqual(dice["players"][1]["pips"], 1)
        self.assertEqual(dice["house"][0]["pips"], 4)
        self.assertEqual(dice["house"][1]["pips"], 3)
        self.assertEqual(dice["house"][0]["stake_rub"], 0.0)

    def test_missing_bots_still_show_one_house_die(self):
        dice = canvas_dice(
            [
                _player(1, 1, "10.00", player_pips=5, house_pips=2),
                _player(2, 2, "10.00", player_pips=3, house_pips=6),
            ]
        )
        self.assertEqual(len(dice["players"]), 2)
        self.assertEqual(len(dice["house"]), 1)
        self.assertEqual(dice["house"][0]["pips"], 2)
        self.assertEqual(dice["house"][0]["label"], "Казино")


class SnapshotCardTests(unittest.TestCase):
    def test_public_card_counts_humans_not_bots(self):
        table = {"table_id": "ht-1", "max_seats": 4, "status": "open", "state_version": 1}
        seats = [
            {"kind": "player", "seat_no": 1},
            {"kind": "player", "seat_no": 2},
            {"kind": "house_robot", "seat_no": 11},
        ]
        card = public_table_card(table, seats)
        self.assertEqual(card["human_count"], 2)
        self.assertEqual(card["house_bot_count"], 1)
        self.assertEqual(card["free_seats"], 2)
        self.assertEqual(card["game_type"], "pvp_dice")

    def test_snapshot_marks_viewer_and_keeps_bot_wallet_zero(self):
        table = {
            "table_id": "ht-snap",
            "max_seats": 3,
            "house_bot_count": 1,
            "status": "open",
            "state_version": 2,
            "game_data": {},
        }
        seats = [
            {
                "seat_no": 1,
                "kind": "player",
                "telegram_id": 7,
                "stake_rub": Decimal("100.00"),
                "payout_rub": Decimal("195.00"),
                "won": True,
                "player_pips": 6,
                "house_pips": 1,
                "status": "settled",
            },
            {
                "seat_no": 2,
                "kind": "player",
                "telegram_id": 8,
                "stake_rub": Decimal("40.00"),
                "payout_rub": Decimal("0.00"),
                "won": False,
                "player_pips": 2,
                "house_pips": 5,
                "status": "settled",
            },
            {
                "seat_no": 11,
                "kind": "house_robot",
                "telegram_id": None,
                "stake_rub": Decimal("0.00"),
                "house_pips": 3,
                "display_name": "Дом",
                "status": "settled",
            },
        ]
        snap = build_snapshot(table, seats, {7: {"display_name": "Аня", "user_id": 7, "initial": "А"}}, 7)
        self.assertTrue(snap["is_seated"])
        self.assertFalse(snap["solo"])
        self.assertEqual(snap["viewer_seat_no"], 1)
        self.assertEqual(snap["money"], "house")
        self.assertEqual(snap["dice"]["players"][0]["pips"], 6)
        self.assertEqual(len(snap["dice"]["house"]), 1)
        bot = next(row for row in snap["seats"] if row["kind"] == "house_robot")
        self.assertEqual(bot["stake_rub"], 0.0)
        self.assertIsNone(bot["telegram_id"])
        self.assertTrue(str((bot.get("actor") or {}).get("avatar_url") or "").startswith("/api/public/casino-idents/"))
        self.assertEqual(as_seat(seats[0]).payout_rub, Decimal("195.00"))


class _Mem:
    def __init__(self):
        self.tables: list[dict] = []
        self.seats: list[dict] = []
        self.profiles = [
            {"id": 1, "profile_key": "house-dice", "display_name": "Дом"},
            {"id": 2, "profile_key": "house-dice-2", "display_name": "Касса"},
        ]
        self.next_table = 1
        self.next_seat = 1


class FakeConn:
    def __init__(self, mem: _Mem | None = None):
        self.mem = mem or _Mem()

    async def fetchrow(self, query, *args):
        q = " ".join(query.split())
        if "INSERT INTO casino_house_tables" in q:
            table_id, game_type, creator_id, max_seats, bots, seed = args
            row = {
                "id": self.mem.next_table,
                "table_id": table_id,
                "game_type": game_type,
                "creator_id": creator_id,
                "max_seats": max_seats,
                "house_bot_count": bots,
                "status": "open",
                "state_version": 0,
                "rng_seed": seed,
                "game_data": {},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            self.mem.next_table += 1
            self.mem.tables.append(row)
            return row
        if "FROM casino_house_tables" in q and "table_id" in q:
            wanted = args[0]
            for row in self.mem.tables:
                if row["table_id"] == wanted:
                    # Match asyncpg.Record: not a Mapping, still supports [].
                    return _RecordLike(dict(row))
            return None
        if "FROM casino_chat_presence" in q or "FROM bot_users" in q or "FROM web_users" in q:
            return None
        if "FROM casino_player_cosmetics" in q:
            return None
        raise AssertionError(query)

    async def fetch(self, query, *args):
        q = " ".join(query.split())
        if "house:expire-choice" in query:
            cutoff, _limit = args
            out = []
            for table in self.mem.tables:
                raw = table.get("game_data") or {}
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        raw = {}
                updated = table.get("updated_at") or table.get("created_at") or datetime.now(timezone.utc)
                if (
                    table["status"] == "running"
                    and isinstance(raw, dict)
                    and "choice" in raw
                    and updated <= cutoff
                ):
                    out.append({"table_id": table["table_id"]})
            return out
        if "house:expire-unjoined" in query:
            max_solo, cutoff, _limit = args
            out = []
            for table in self.mem.tables:
                created = table.get("created_at") or datetime.now(timezone.utc)
                if (
                    table["status"] == "open"
                    and int(table["max_seats"]) > int(max_solo)
                    and created <= cutoff
                ):
                    out.append({"table_id": table["table_id"]})
            return out
        if "FROM casino_house_tables t" in q:
            out = []
            for table in self.mem.tables:
                if table["status"] != "open":
                    continue
                humans = sum(
                    1
                    for seat in self.mem.seats
                    if int(seat["table_pk"]) == int(table["id"]) and seat["kind"] == "player"
                )
                row = dict(table)
                row["human_count"] = humans
                out.append(row)
            return out
        if "casino_player_cosmetics" in q:
            return []
        if "FROM casino_robot_profiles" in q:
            return list(self.mem.profiles)
        if "FROM casino_house_table_seats" in q:
            table_pk = int(args[0])
            rows = [dict(s) for s in self.mem.seats if int(s["table_pk"]) == table_pk]
            rows.sort(key=lambda item: int(item["seat_no"]))
            return rows
        raise AssertionError(query)

    async def fetchval(self, query, *args):
        q = " ".join(query.split())
        if "s.telegram_id" in q:
            uid = int(args[0])
            skip = args[1] if len(args) > 1 else None
            for seat in self.mem.seats:
                if seat.get("telegram_id") != uid:
                    continue
                table = next(t for t in self.mem.tables if int(t["id"]) == int(seat["table_pk"]))
                if table["status"] not in ("open", "running"):
                    continue
                if skip is not None and table["table_id"] == skip:
                    continue
                return table["table_id"]
            return None
        raise AssertionError(query)

    async def execute(self, query, *args):
        q = " ".join(query.split())
        if "house:face-human" in query:
            table_pk, seat_no, player_pips, cub_id, status, payout, commission, won = args
            for seat in self.mem.seats:
                if int(seat["table_pk"]) == int(table_pk) and int(seat["seat_no"]) == int(seat_no):
                    seat["player_pips"] = player_pips
                    seat["cub_game_id"] = cub_id
                    seat["status"] = status
                    seat["payout_rub"] = payout
                    seat["commission_rub"] = commission
                    seat["won"] = won
            return "UPDATE 1"
        if "house:face-keep" in query:
            pk, payload = args
            parsed = json.loads(payload) if isinstance(payload, str) else payload
            for table in self.mem.tables:
                if int(table["id"]) == int(pk):
                    table["game_data"] = parsed
                    table["status"] = "running"
                    table["state_version"] = int(table["state_version"]) + 1
                    table["updated_at"] = datetime.now(timezone.utc)
            return "UPDATE 1"
        if "INSERT INTO casino_house_table_seats" in q and "house_robot" in q and "ON CONFLICT" in q:
            table_pk, seat_no, pips = args[0], args[1], args[2]
            existing = next(
                (s for s in self.mem.seats if int(s["table_pk"]) == int(table_pk) and int(s["seat_no"]) == int(seat_no)),
                None,
            )
            if existing:
                existing["house_pips"] = pips
            else:
                self.mem.seats.append(
                    self._seat(table_pk, seat_no, "house_robot", None, Decimal("0.00"), house_pips=pips)
                )
            return "INSERT"
        if "INSERT INTO casino_house_table_seats" in q and "house_robot" in q:
            table_pk, seat_no, profile_id, key, display = args
            self.mem.seats.append(
                self._seat(
                    table_pk,
                    seat_no,
                    "house_robot",
                    None,
                    Decimal("0.00"),
                    profile_id=profile_id,
                    profile_key=key,
                    display_name=display,
                )
            )
            return "INSERT 1"
        if "INSERT INTO casino_house_table_seats" in q:
            table_pk, seat_no, uid, stake = args
            self.mem.seats.append(self._seat(table_pk, seat_no, "player", uid, stake))
            return "INSERT 1"
        if "SET payout_rub" in q:
            table_pk, seat_no, payout, commission, won, player_pips, house_pips, cub_id = args
            for seat in self.mem.seats:
                if int(seat["table_pk"]) == int(table_pk) and int(seat["seat_no"]) == int(seat_no):
                    seat["payout_rub"] = payout
                    seat["commission_rub"] = commission
                    seat["won"] = won
                    seat["player_pips"] = player_pips
                    seat["house_pips"] = house_pips
                    seat["cub_game_id"] = cub_id
                    seat["status"] = "settled"
            return "UPDATE 1"
        if "SET house_pips" in q:
            table_pk, seat_no, pips = args
            for seat in self.mem.seats:
                if int(seat["table_pk"]) == int(table_pk) and int(seat["seat_no"]) == int(seat_no):
                    seat["house_pips"] = pips
                    seat["status"] = "settled"
            return "UPDATE 1"
        if "SET status = 'running'" in q:
            pk = int(args[0])
            for table in self.mem.tables:
                if int(table["id"]) == pk and table["status"] == "open":
                    table["status"] = "running"
                    table["state_version"] = int(table["state_version"]) + 1
                    table["updated_at"] = datetime.now(timezone.utc)
            return "UPDATE 1"
        if "SET status = 'open', game_data" in q:
            pk, payload = args
            parsed = json.loads(payload) if isinstance(payload, str) else payload
            for table in self.mem.tables:
                if int(table["id"]) == int(pk):
                    table["status"] = "open"
                    table["game_data"] = parsed
                    table["state_version"] = int(table["state_version"]) + 1
                    table["updated_at"] = datetime.now(timezone.utc)
            return "UPDATE 1"
        if "SET status = 'closed'" in q:
            pk = int(args[0])
            for table in self.mem.tables:
                if int(table["id"]) == pk:
                    table["status"] = "closed"
                    table["state_version"] = int(table["state_version"]) + 1
            return "UPDATE 1"
        if "SET state_version = state_version + 1" in q:
            pk = int(args[0])
            for table in self.mem.tables:
                if int(table["id"]) == pk:
                    table["state_version"] = int(table["state_version"]) + 1
            return "UPDATE 1"
        if "DELETE FROM casino_house_table_seats" in q:
            pk, uid = args
            self.mem.seats = [
                seat
                for seat in self.mem.seats
                if not (int(seat["table_pk"]) == int(pk) and seat.get("telegram_id") == uid)
            ]
            return "DELETE 1"
        if "INSERT INTO casino_web_inbox" in q:
            return "INSERT 0 1"
        raise AssertionError(query)

    def _seat(self, table_pk, seat_no, kind, uid, stake, **extra):
        row = {
            "id": self.mem.next_seat,
            "table_pk": int(table_pk),
            "seat_no": int(seat_no),
            "kind": kind,
            "telegram_id": uid,
            "profile_id": extra.get("profile_id"),
            "profile_key": extra.get("profile_key"),
            "display_name": extra.get("display_name") or ("Казино" if kind == "house_robot" else ""),
            "stake_rub": stake,
            "payout_rub": extra.get("payout_rub"),
            "commission_rub": extra.get("commission_rub"),
            "won": extra.get("won"),
            "player_pips": extra.get("player_pips"),
            "house_pips": extra.get("house_pips"),
            "cub_game_id": extra.get("cub_game_id"),
            "status": extra.get("status", "seated"),
        }
        self.mem.next_seat += 1
        return row


def _quote(stake="100"):
    return {
        "enabled": True,
        "min_bet_rub": 10.0,
        "max_bet_rub": 100000.0,
        "bound_error": None,
        "stake_rub": float(stake),
    }


class _Settings:
    enabled_games = {"cub": True, "pvp_dice": True}


class TableFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_sits_creator_and_house_bots_without_wallet_debit(self):
        conn = FakeConn()
        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote("100"))
        ), patch("casino_chat.public_actors", AsyncMock(return_value={1: {"display_name": "Аня", "user_id": 1, "initial": "А"}})):
            snap = await create_table(
                conn, creator_id=1, stake_rub=Decimal("100.00"), max_seats=4, house_bot_count=2
            )
        humans = [row for row in snap["seats"] if row["kind"] == "player"]
        bots = [row for row in snap["seats"] if row["kind"] == "house_robot"]
        self.assertEqual(len(humans), 1)
        self.assertEqual(humans[0]["stake_rub"], 100.0)
        self.assertEqual(len(bots), 2)
        self.assertEqual(bots[0]["stake_rub"], 0.0)
        self.assertEqual(bots[1]["stake_rub"], 0.0)
        self.assertTrue(str(snap["table_id"]).startswith("ht-"))
        self.assertTrue(snap["can_start"])
        self.assertTrue(snap["is_seated"])
        listed = await list_open_tables(conn)
        self.assertEqual(listed["tables"][0]["human_count"], 1)
        self.assertEqual(listed["tables"][0]["house_bot_count"], 2)
        self.assertEqual(listed["tables"][0]["free_seats"], 3)
        self.assertEqual(len(listed["tables"][0]["seats"]), 3)

    async def test_start_plays_cub_per_human_stake_and_skips_bots(self):
        conn = FakeConn()
        calls: list[tuple[int, Decimal]] = []

        async def fake_play(conn, *, telegram_id, stake_rub, house_bot_count=0):
            calls.append((int(telegram_id), Decimal(str(stake_rub))))
            if telegram_id == 10:
                return {
                    "game_id": "cub-a",
                    "outcome": {"kind": "win"},
                    "payout_rub": "195.00",
                    "commission_rub": "5.00",
                    "player_pips": 6,
                    "house_pips": 1,
                    "rng": {"won": True},
                }
            return {
                "game_id": "cub-b",
                "outcome": {"kind": "loss"},
                "payout_rub": "0.00",
                "commission_rub": "0.00",
                "player_pips": 2,
                "house_pips": 5,
                "rng": {"won": False},
            }

        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote())
        ), patch(
            "casino_chat.public_actors",
            AsyncMock(
                return_value={
                    10: {"display_name": "А", "user_id": 10, "initial": "А"},
                    20: {"display_name": "Б", "user_id": 20, "initial": "Б"},
                }
            ),
        ):
            created = await create_table(
                conn, creator_id=10, stake_rub=Decimal("100.00"), max_seats=3, house_bot_count=1
            )
            table_id = str(created["table_id"])
            await sit(conn, table_id=table_id, user_id=20, stake_rub=Decimal("250.00"))
            snap = await start_round(conn, table_id=table_id, user_id=10, play_seat=fake_play)
        self.assertEqual(calls, [(10, Decimal("100.00")), (20, Decimal("250.00"))])
        by_id = {row["telegram_id"]: row for row in snap["seats"] if row["kind"] == "player"}
        self.assertEqual(by_id[10]["payout_rub"], 195.0)
        self.assertEqual(by_id[20]["payout_rub"], 0.0)
        self.assertEqual(by_id[10]["won"], True)
        self.assertEqual(by_id[20]["won"], False)
        bot = next(row for row in snap["seats"] if row["kind"] == "house_robot")
        self.assertEqual(bot["stake_rub"], 0.0)
        self.assertIsNotNone(bot["house_pips"])
        self.assertGreaterEqual(int(bot["house_pips"]), 1)
        self.assertLessEqual(int(bot["house_pips"]), 6)
        self.assertEqual(len(snap["dice"]["players"]), 2)
        self.assertGreaterEqual(len(snap["dice"]["house"]), 1)
        last = snap["last_round"]
        self.assertEqual(last["money"], "house")
        self.assertFalse(last["shared_pot"])
        self.assertEqual(last["house_bot_count"], 1)
        self.assertEqual(last["seats"][0]["payout_rub"], 195.0)
        self.assertEqual(last["seats"][1]["payout_rub"], 0.0)

    async def test_leave_last_human_closes_table(self):
        conn = FakeConn()
        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote("40"))
        ), patch("casino_chat.public_actors", AsyncMock(return_value={3: {"display_name": "В", "user_id": 3, "initial": "В"}})):
            created = await create_table(
                conn, creator_id=3, stake_rub=Decimal("40.00"), max_seats=2, house_bot_count=0
            )
            snap = await leave(conn, table_id=str(created["table_id"]), user_id=3)
        self.assertEqual(snap["status"], "closed")

    async def test_expire_closes_stale_multi_not_fresh_or_solo(self):
        conn = FakeConn()
        old = NOW = datetime(2026, 8, 29, 19, 0, tzinfo=timezone.utc)
        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote("40"))
        ), patch("casino_chat.public_actors", AsyncMock(return_value={3: {"display_name": "В", "user_id": 3, "initial": "В"}})):
            stale = await create_table(
                conn, creator_id=3, stake_rub=Decimal("40.00"), max_seats=2, house_bot_count=0
            )
            fresh = await create_table(
                conn, creator_id=4, stake_rub=Decimal("40.00"), max_seats=2, house_bot_count=0
            )
        conn.mem.tables[0]["created_at"] = old - timedelta(minutes=11)
        conn.mem.tables[1]["created_at"] = old - timedelta(minutes=2)
        with patch("casino_chat.public_actors", AsyncMock(return_value={3: {"display_name": "В", "user_id": 3, "initial": "В"}})):
            n = await expire_open_unjoined(conn, now=old)
        self.assertEqual(n, 1)
        by_id = {row["table_id"]: row["status"] for row in conn.mem.tables}
        self.assertEqual(by_id[stale["table_id"]], "closed")
        self.assertEqual(by_id[fresh["table_id"]], "open")

    async def test_second_multi_create_points_at_other_table(self):
        conn = FakeConn()
        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote())
        ), patch("casino_chat.public_actors", AsyncMock(return_value={})):
            first = await create_table(
                conn, creator_id=1, stake_rub=Decimal("100.00"), max_seats=3, house_bot_count=1
            )
            with self.assertRaises(HTTPException) as err:
                await create_table(
                    conn, creator_id=1, stake_rub=Decimal("100.00"), max_seats=3, house_bot_count=1
                )
        self.assertEqual(err.exception.status_code, 409)
        detail = err.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail["table_id"], first["table_id"])
        self.assertIn(first["table_id"], detail["href"])

    async def test_start_allows_solo_human(self):
        conn = FakeConn()
        calls: list[tuple[int, object]] = []

        async def fake_play(conn, *, telegram_id, stake_rub, house_bot_count=0):
            calls.append((int(telegram_id), stake_rub))
            return {
                "game_id": "cub-solo",
                "outcome": {"kind": "win"},
                "payout_rub": "195.00",
                "commission_rub": "5.00",
                "player_pips": 6,
                "house_pips": 1,
                "rng": {"won": True},
            }

        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote())
        ), patch("casino_chat.public_actors", AsyncMock(return_value={1: {"display_name": "А", "user_id": 1, "initial": "А"}})):
            created = await create_table(
                conn, creator_id=1, stake_rub=Decimal("100.00"), max_seats=4, house_bot_count=1
            )
            snap = await start_round(conn, table_id=str(created["table_id"]), user_id=1, play_seat=fake_play)
        self.assertEqual(calls, [(1, Decimal("100.00"))])
        mine = next(row for row in snap["seats"] if row["kind"] == "player")
        self.assertEqual(mine["payout_rub"], 195.0)
        self.assertTrue(mine["won"])

    async def test_sit_rejects_when_full(self):
        conn = FakeConn()
        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote())
        ), patch("casino_chat.public_actors", AsyncMock(return_value={})):
            created = await create_table(
                conn, creator_id=1, stake_rub=Decimal("100.00"), max_seats=2, house_bot_count=0
            )
            table_id = str(created["table_id"])
            await sit(conn, table_id=table_id, user_id=2, stake_rub=Decimal("100.00"))
            with self.assertRaises(HTTPException) as err:
                await sit(conn, table_id=table_id, user_id=3, stake_rub=Decimal("100.00"))
        self.assertEqual(err.exception.status_code, 409)

    async def test_solo_create_starts_round_and_rejects_sit(self):
        conn = FakeConn()
        calls: list[tuple[int, object]] = []

        async def fake_play(conn, *, telegram_id, stake_rub, house_bot_count=0):
            calls.append((int(telegram_id), stake_rub, int(house_bot_count)))
            return {
                "game_id": "cub-solo-table",
                "outcome": {"kind": "win"},
                "payout_rub": "195.00",
                "commission_rub": "5.00",
                "player_pips": 6,
                "house_pips": 1,
                "rng": {"won": True},
            }

        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote())
        ), patch("casino_chat.public_actors", AsyncMock(return_value={9: {"display_name": "А", "user_id": 9, "initial": "А"}})):
            snap = await create_table(
                conn,
                creator_id=9,
                stake_rub=Decimal("100.00"),
                max_seats=1,
                house_bot_count=3,
                play_seat=fake_play,
            )
            table_id = str(snap["table_id"])
            listed = await list_open_tables(conn)
            with self.assertRaises(HTTPException) as err:
                await sit(conn, table_id=table_id, user_id=2, stake_rub=Decimal("100.00"))
        self.assertEqual(calls, [(9, Decimal("100.00"), 3)])
        self.assertEqual(snap["last_round"]["house_bot_count"], 3)
        self.assertTrue(snap["solo"])
        self.assertEqual(snap["max_seats"], 1)
        self.assertEqual(len([row for row in snap["seats"] if row["kind"] == "house_robot"]), 3)
        mine = next(row for row in snap["seats"] if row["kind"] == "player")
        self.assertEqual(mine["payout_rub"], 195.0)
        self.assertEqual(listed["tables"], [])
        self.assertEqual(err.exception.status_code, 409)
        self.assertIn("создателя", err.exception.detail)

    async def test_solo_create_replaces_previous_solo_table(self):
        conn = FakeConn()

        async def fake_play(conn, *, telegram_id, stake_rub, house_bot_count=0):
            return {
                "game_id": "cub-replace",
                "outcome": {"kind": "loss"},
                "payout_rub": "0.00",
                "commission_rub": "0.00",
                "player_pips": 1,
                "house_pips": 6,
                "rng": {"won": False},
            }

        with patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())), patch(
            "casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote())
        ), patch("casino_chat.public_actors", AsyncMock(return_value={4: {"display_name": "Г", "user_id": 4, "initial": "Г"}})):
            first = await create_table(
                conn, creator_id=4, stake_rub=Decimal("50.00"), max_seats=1, house_bot_count=2, play_seat=fake_play
            )
            second = await create_table(
                conn, creator_id=4, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=2, play_seat=fake_play
            )
        self.assertNotEqual(first["table_id"], second["table_id"])
        self.assertEqual(second["max_seats"], 1)


def _face_money_ref() -> dict:
    return {
        "game_id": "htcub-test",
        "game_pk": 9,
        "hold_id": "casino-htcub-test-player",
        "order_ref": "ord-htcub-test",
        "account_id": 1,
        "reserved_rub": "765.00",
        "pricing_snapshot": {
            "commission_rate": "5.00",
            "commission_cap_rub": "0.00",
            "commission_min_rub": "0.00",
            "creator_cut_percent": "0.00",
            "referral_l1_percent": "0.00",
            "referral_l2_percent": "0.00",
        },
        "commission_rate": "5.00",
    }


class FaceFlowTests(unittest.IsolatedAsyncioTestCase):
    def _face_ctx(self, *, reroll_bots: dict[int, int] | None = None, player_pips: int = 6):
        first_bots = {11: 2, 12: 5, 13: 6}
        later_bots = reroll_bots if reroll_bots is not None else first_bots

        async def fake_open(conn, **kwargs):
            return _face_money_ref()

        async def fake_close(conn, **kwargs):
            return payout_for_multiplier(Decimal("100"), kwargs["multiplier"])

        def fake_player(seed, table_id, seat_no, nonce=0):
            return int(player_pips)

        def fake_bot(seed, table_id, seat_no, nonce=0):
            table = later_bots if int(nonce) >= 2 else first_bots
            return int(table[int(seat_no)])

        return (
            patch("casino_house_tables.load_casino_settings", AsyncMock(return_value=_Settings())),
            patch("casino_house_tables.load_cub_play_quote", AsyncMock(return_value=_quote())),
            patch("casino_chat.public_actors", AsyncMock(return_value={9: {"display_name": "А", "user_id": 9, "initial": "А"}})),
            patch("casino_house_tables._open_face_hold", new=AsyncMock(side_effect=fake_open)),
            patch("casino_house_tables._close_face_hold", new=AsyncMock(side_effect=fake_close)),
            patch("casino_house_tables.player_die_pips", new=fake_player),
            patch("casino_house_tables.house_bot_die_pips", new=fake_bot),
        )

    async def test_choice_offers_take_290_not_a_win(self):
        conn = FakeConn()
        ctx = self._face_ctx()
        with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], ctx[5], ctx[6]:
            snap = await create_table(
                conn, creator_id=9, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=3
            )
        self.assertEqual(snap["status"], "running")
        choice = snap["choice"]
        self.assertIsNotNone(choice)
        self.assertNotIn("money", choice)
        self.assertEqual(choice["wins"], 2)
        self.assertEqual(choice["ties"], 1)
        self.assertEqual(choice["take_payout_rub"], 290.0)
        self.assertEqual(choice["reroll_payout_rub"], 765.0)
        self.assertTrue(choice["can_reroll"])
        mine = next(row for row in snap["seats"] if row["kind"] == "player")
        self.assertIsNone(mine["payout_rub"])
        self.assertIsNone(mine["won"])

    async def test_take_pays_290(self):
        conn = FakeConn()
        ctx = self._face_ctx()
        with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], ctx[5], ctx[6]:
            snap = await create_table(
                conn, creator_id=9, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=3
            )
            taken = await resolve_round(conn, table_id=str(snap["table_id"]), user_id=9, action="take")
        self.assertEqual(taken["status"], "open")
        self.assertIsNone(taken["choice"])
        mine = next(row for row in taken["seats"] if row["kind"] == "player")
        self.assertEqual(mine["payout_rub"], 290.0)
        self.assertTrue(mine["won"])
        self.assertEqual(taken["last_round"]["kind"], "win")
        self.assertEqual(taken["last_round"]["payout_multiplier"], 3.0)

    async def test_reroll_beat_tie_pays_765(self):
        conn = FakeConn()
        ctx = self._face_ctx(reroll_bots={11: 2, 12: 5, 13: 1})
        with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], ctx[5], ctx[6]:
            snap = await create_table(
                conn, creator_id=9, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=3
            )
            done = await resolve_round(conn, table_id=str(snap["table_id"]), user_id=9, action="reroll")
        mine = next(row for row in done["seats"] if row["kind"] == "player")
        self.assertEqual(mine["payout_rub"], 765.0)
        self.assertEqual(done["last_round"]["payout_multiplier"], 8.0)
        self.assertIsNone(done["choice"])

    async def test_reroll_leftover_tie_pays_290_no_second_reroll(self):
        conn = FakeConn()
        ctx = self._face_ctx(reroll_bots={11: 2, 12: 5, 13: 6})
        with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], ctx[5], ctx[6]:
            snap = await create_table(
                conn, creator_id=9, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=3
            )
            done = await resolve_round(conn, table_id=str(snap["table_id"]), user_id=9, action="reroll")
        mine = next(row for row in done["seats"] if row["kind"] == "player")
        self.assertEqual(mine["payout_rub"], 290.0)
        self.assertIsNone(done["choice"])

    async def test_reroll_loss_pays_zero(self):
        conn = FakeConn()

        def fake_player(seed, table_id, seat_no, nonce=0):
            return 6 if int(nonce) < 2 else 3

        ctx_list = list(self._face_ctx(reroll_bots={11: 2, 12: 5, 13: 6}))
        ctx_list[5] = patch("casino_house_tables.player_die_pips", new=fake_player)
        with ctx_list[0], ctx_list[1], ctx_list[2], ctx_list[3], ctx_list[4], ctx_list[5], ctx_list[6]:
            snap = await create_table(
                conn, creator_id=9, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=3
            )
            done = await resolve_round(conn, table_id=str(snap["table_id"]), user_id=9, action="reroll")
        mine = next(row for row in done["seats"] if row["kind"] == "player")
        self.assertEqual(mine["payout_rub"], 0.0)
        self.assertFalse(mine["won"])
        self.assertEqual(done["last_round"]["kind"], "loss")

    async def test_leave_blocked_while_choice_pending(self):
        conn = FakeConn()
        ctx = self._face_ctx()
        with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], ctx[5], ctx[6]:
            snap = await create_table(
                conn, creator_id=9, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=3
            )
            with self.assertRaises(HTTPException) as err:
                await leave(conn, table_id=str(snap["table_id"]), user_id=9)
        self.assertEqual(err.exception.status_code, 409)
        self.assertIn("заберите", err.exception.detail)

    async def test_expire_auto_takes(self):
        conn = FakeConn()
        ctx = self._face_ctx()
        with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], ctx[5], ctx[6]:
            snap = await create_table(
                conn, creator_id=9, stake_rub=Decimal("100.00"), max_seats=1, house_bot_count=3
            )
            table = conn.mem.tables[0]
            table["updated_at"] = datetime.now(timezone.utc) - timedelta(minutes=11)
            n = await expire_pending_choices(conn, now=datetime.now(timezone.utc))
            done = await snapshot(conn, table_id=str(snap["table_id"]), viewer_id=9)
        self.assertEqual(n, 1)
        mine = next(row for row in done["seats"] if row["kind"] == "player")
        self.assertEqual(mine["payout_rub"], 290.0)


class RouteImportTests(unittest.TestCase):
    def test_user_and_public_house_table_routes_exist(self):
        from routers import public_casino, user_casino

        public_paths = {getattr(route, "path", None) for route in public_casino.router.routes}
        user_paths = {getattr(route, "path", None) for route in user_casino.router.routes}
        self.assertIn("/casino/house-tables", public_paths)
        self.assertIn("/casino/house-tables/{table_id}", public_paths)
        self.assertIn("/casino/house-tables", user_paths)
        self.assertIn("/casino/house-tables/{table_id}", user_paths)
        self.assertIn("/casino/house-tables/{table_id}/sit", user_paths)
        self.assertIn("/casino/house-tables/{table_id}/leave", user_paths)
        self.assertIn("/casino/house-tables/{table_id}/start", user_paths)
        self.assertIn("/casino/house-tables/{table_id}/resolve", user_paths)
        self.assertIn("/casino/duels/{game_id}/join", user_paths)
        self.assertIn("/casino/duels/{game_id}/cancel", user_paths)
        self.assertIn("/casino/v2/tables/{table_id}/bots", user_paths)
        self.assertIn("/casino/players/me", user_paths)
        self.assertIn("/casino/players/me/avatar", user_paths)
        self.assertIn("/casino/inbox", user_paths)
        self.assertIn("/casino/inbox/read", user_paths)
        self.assertIn("/casino/play", user_paths)

    def test_play_human_cub_is_the_cub_entry(self):
        self.assertEqual(GAME_TYPE, "pvp_dice")
        self.assertEqual(HOUSE_MONEY_GAME, "cub")
        self.assertTrue(callable(play_human_cub))
        self.assertIn("house_bot_count", play_human_cub.__code__.co_varnames)


if __name__ == "__main__":
    unittest.main()
