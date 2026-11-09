"""Jackpot Telegram notify: outbox on settle/refund, notify_chat_id on stakes."""
from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from casino_jackpot import (
    JackpotConfig,
    _lock_and_settle,
    _notify_chat,
    place_bet,
    settle_chat_html,
)
import casino_jackpot as jackpot_mod


def _cfg() -> JackpotConfig:
    return JackpotConfig(
        enabled=True,
        collect_seconds=300,
        max_players=30,
        rake_percent=Decimal("5"),
        min_bet=Decimal("10"),
        max_bet=Decimal("100000"),
    )


def _round_row(*, status="open", pot="200.00", roll="0"):
    return {
        "id": 1,
        "round_id": "jp-notify1",
        "status": status,
        "commit_hash": "ab" * 32,
        "roll": roll,
        "closes_at": None,
        "winning_ticket": 0 if status in {"locked", "settled"} else None,
        "winner_id": 11 if status in {"locked", "settled"} else None,
        "pot_rub": Decimal(pot),
        "rake_rub": Decimal("10.00") if status in {"locked", "settled"} else Decimal("0"),
        "payout_rub": Decimal("190.00") if status == "settled" else Decimal("0"),
        "wager_json": {},
        "created_at": None,
        "locked_at": None,
        "settled_at": None,
    }


def _bet(user_id, amount, notify_chat_id=None):
    tickets = int(Decimal(amount) * 100)
    return {
        "user_id": user_id,
        "amount_rub": Decimal(amount),
        "ticket_from": 0,
        "ticket_to": tickets - 1,
        "hold_order_ref": f"hold-{user_id}",
        "notify_chat_id": notify_chat_id,
    }


def _view(*, refund=False, winner_id=11):
    return {
        "round_id": "jp-notify1",
        "status": "refunded" if refund else "settled",
        "pot_rub": 100.0 if refund else 200.0,
        "rake_percent": 5.0,
        "rake_rub": None if refund else 10.0,
        "payout_rub": None if refund else 190.0,
        "winner_id": None if refund else winner_id,
        "total_tickets": 10000 if refund else 20000,
        "players": [
            {
                "user_id": 11,
                "display_name": "Alice",
                "amount_rub": 100.0,
                "chance_pct": 50.0 if not refund else 100.0,
            },
            *([] if refund else [
                {
                    "user_id": 22,
                    "display_name": "Bob",
                    "amount_rub": 100.0,
                    "chance_pct": 50.0,
                }
            ]),
        ],
    }


class JackpotSettleHtmlTests(unittest.TestCase):
    def test_settle_html_names_winner_and_chances(self):
        text = settle_chat_html(_view(), refund=False)
        self.assertIn("Джекпот", text)
        self.assertIn("Банк: <b>200 ₽</b>", text)
        self.assertIn("рейк 5% (10 ₽)", text)
        self.assertIn("Выплата: <b>190 ₽</b>", text)
        self.assertIn("tg://user?id=11", text)
        self.assertIn("Alice", text)
        self.assertIn("50%", text)
        self.assertIn("Bob", text)

    def test_refund_html_does_not_name_a_winner(self):
        text = settle_chat_html(_view(refund=True), refund=True)
        self.assertIn("ставка возвращена", text)
        self.assertNotIn("Победитель", text)
        self.assertIn("100 ₽", text)

    def test_zero_notify_chat_is_ignored(self):
        self.assertIsNone(_notify_chat(0))
        self.assertIsNone(_notify_chat(None))
        self.assertEqual(_notify_chat(-1001), -1001)


class JackpotConn:
    def __init__(self, bets, *, status="open"):
        self.bets = bets
        self.round = _round_row(status=status)
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _execute(self, query, *args):
        q = " ".join(query.split())
        if "status = 'refunded'" in q:
            self.round["status"] = "refunded"
        elif "status = 'locked'" in q:
            self.round["status"] = "locked"
            self.round["winning_ticket"] = args[1]
            self.round["winner_id"] = args[2]
            self.round["rake_rub"] = args[3]
            self.round["payout_rub"] = args[4]
        elif "status = 'settled'" in q:
            self.round["status"] = "settled"
        return "UPDATE 1"

    async def _fetchrow(self, query, *_args):
        if "FROM casino_jackpot_rounds" in query:
            return dict(self.round)
        raise AssertionError(query)


class JackpotTelegramSettleTests(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_settle_enqueues_one_outbox_per_chat(self):
        conn = JackpotConn(
            [
                _bet(11, "100", notify_chat_id=-1001),
                _bet(22, "100", notify_chat_id=22),
            ]
        )
        view = _view()
        with (
            patch.object(jackpot_mod, "_bets", new=AsyncMock(return_value=conn.bets)),
            patch.object(jackpot_mod, "_named_public", new=AsyncMock(return_value=view)),
            patch.object(jackpot_mod, "_lock_open", new=AsyncMock(return_value=_round_row())),
            patch.object(jackpot_mod, "_credit", new=AsyncMock()),
            patch.object(jackpot_mod, "_credit_house", new=AsyncMock()),
            patch.object(jackpot_mod, "publish"),
            patch("casino_level_bonus.maybe_grant_reached_level_bonuses", new=AsyncMock()),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        outbox = [
            call
            for call in conn.execute.await_args_list
            if "INSERT INTO casino_notification_outbox" in call.args[0]
        ]
        self.assertEqual(len(outbox), 2)
        types = {call.args[2] for call in outbox}
        self.assertEqual(types, {"jackpot_settled"})
        payloads = {call.args[5] for call in outbox}
        self.assertTrue(any("-1001" in str(payload) for payload in payloads))
        self.assertTrue(any('"chat_id": 22' in str(payload) or '"chat_id":22' in str(payload) for payload in payloads))
        self.assertTrue(any("Победитель" in str(payload) for payload in payloads))

    async def test_site_only_settle_skips_outbox(self):
        conn = JackpotConn([_bet(11, "100"), _bet(22, "100")])
        with (
            patch.object(jackpot_mod, "_bets", new=AsyncMock(return_value=conn.bets)),
            patch.object(jackpot_mod, "_named_public", new=AsyncMock(return_value=_view())),
            patch.object(jackpot_mod, "_lock_open", new=AsyncMock(return_value=_round_row())),
            patch.object(jackpot_mod, "_credit", new=AsyncMock()),
            patch.object(jackpot_mod, "_credit_house", new=AsyncMock()),
            patch.object(jackpot_mod, "publish"),
            patch("casino_level_bonus.maybe_grant_reached_level_bonuses", new=AsyncMock()),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        outbox = [
            call
            for call in conn.execute.await_args_list
            if "INSERT INTO casino_notification_outbox" in call.args[0]
        ]
        self.assertEqual(outbox, [])

    async def test_solo_refund_enqueues_jackpot_refunded(self):
        conn = JackpotConn([_bet(11, "100", notify_chat_id=11)])
        with (
            patch.object(jackpot_mod, "_bets", new=AsyncMock(return_value=conn.bets)),
            patch.object(jackpot_mod, "_named_public", new=AsyncMock(return_value=_view(refund=True))),
            patch.object(jackpot_mod, "_lock_open", new=AsyncMock(return_value=_round_row())),
            patch.object(jackpot_mod, "_credit", new=AsyncMock()),
            patch.object(jackpot_mod, "publish"),
        ):
            await _lock_and_settle(conn, round_pk=1, cfg=_cfg())
        outbox = [
            call
            for call in conn.execute.await_args_list
            if "INSERT INTO casino_notification_outbox" in call.args[0]
        ]
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0].args[2], "jackpot_refunded")
        self.assertIn("возвращена", outbox[0].args[5])


class JackpotPlaceNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_place_bet_writes_notify_chat_id(self):
        conn = JackpotConn([])
        conn.fetch = AsyncMock(return_value=[])
        named = {
            "round_id": "jp-notify1",
            "status": "open",
            "player_count": 1,
            "players": [],
            "my_amount_rub": 100,
            "my_chance_pct": 100,
        }
        with (
            patch("casino_jackpot.load_jackpot_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_jackpot.maybe_close_due", new=AsyncMock()),
            patch("casino_jackpot._lock_open", new=AsyncMock(return_value=_round_row())),
            patch("casino_jackpot._bets", new=AsyncMock(return_value=[])),
            patch("casino_jackpot.reserve_unified_funds", new=AsyncMock()),
            patch("casino_jackpot.confirm_unified_hold", new=AsyncMock()),
            patch("casino_jackpot._named_public", new=AsyncMock(return_value=named)),
            patch("casino_jackpot.publish"),
        ):
            await place_bet(conn, user_id=11, amount_rub=Decimal("100"), notify_chat_id=-1001)
        inserted = [
            call for call in conn.execute.await_args_list if "INSERT INTO casino_jackpot_bets" in call.args[0]
        ]
        self.assertTrue(inserted)
        self.assertEqual(inserted[0].args[5], -1001)

    async def test_top_up_keeps_first_notify_chat(self):
        existing = _bet(11, "50", notify_chat_id=-1001)
        conn = JackpotConn([existing])
        named = {
            "round_id": "jp-notify1",
            "status": "open",
            "player_count": 1,
            "players": [],
            "my_amount_rub": 100,
            "my_chance_pct": 100,
        }
        with (
            patch("casino_jackpot.load_jackpot_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_jackpot.maybe_close_due", new=AsyncMock()),
            patch("casino_jackpot._lock_open", new=AsyncMock(return_value=_round_row())),
            patch(
                "casino_jackpot._bets",
                new=AsyncMock(side_effect=[[existing], [{**existing, "amount_rub": Decimal("100")}]]),
            ),
            patch("casino_jackpot.reserve_unified_funds", new=AsyncMock()),
            patch("casino_jackpot.confirm_unified_hold", new=AsyncMock()),
            patch("casino_jackpot._named_public", new=AsyncMock(return_value=named)),
            patch("casino_jackpot.publish"),
        ):
            await place_bet(conn, user_id=11, amount_rub=Decimal("50"), notify_chat_id=11)
        updated = [
            call for call in conn.execute.await_args_list if "UPDATE casino_jackpot_bets" in call.args[0]
            and "notify_chat_id = COALESCE" in call.args[0]
        ]
        self.assertTrue(updated)
        self.assertEqual(updated[0].args[3], Decimal("100.00"))
        self.assertEqual(updated[0].args[5], -1001)

    async def test_web_bet_stores_null_notify_chat(self):
        conn = JackpotConn([])
        named = {
            "round_id": "jp-notify1",
            "status": "open",
            "player_count": 1,
            "players": [],
            "my_amount_rub": 50,
            "my_chance_pct": 100,
        }
        with (
            patch("casino_jackpot.load_jackpot_config", new=AsyncMock(return_value=_cfg())),
            patch("casino_jackpot.maybe_close_due", new=AsyncMock()),
            patch("casino_jackpot._lock_open", new=AsyncMock(return_value=_round_row())),
            patch("casino_jackpot._bets", new=AsyncMock(return_value=[])),
            patch("casino_jackpot.reserve_unified_funds", new=AsyncMock()),
            patch("casino_jackpot.confirm_unified_hold", new=AsyncMock()),
            patch("casino_jackpot._named_public", new=AsyncMock(return_value=named)),
            patch("casino_jackpot.publish"),
        ):
            await place_bet(conn, user_id=11, amount_rub=Decimal("50"))
        inserted = [
            call for call in conn.execute.await_args_list if "INSERT INTO casino_jackpot_bets" in call.args[0]
        ]
        self.assertTrue(inserted)
        self.assertIsNone(inserted[0].args[5])


if __name__ == "__main__":
    unittest.main()
