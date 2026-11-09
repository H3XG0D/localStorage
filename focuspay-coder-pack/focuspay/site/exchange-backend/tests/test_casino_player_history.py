from datetime import datetime, timezone
from decimal import Decimal
import inspect
import unittest

from fastapi import HTTPException

from casino_player_history import (
    card_fairness,
    classify_result,
    clamp_grouped_per,
    clamp_limit,
    jackpot_fairness,
    load_player_history,
    load_player_history_grouped,
    normalize_history_game_type,
    parse_before,
    play_href,
    share_percent,
    _from_game,
    _from_jackpot,
    _from_poker,
)
from casino_weekly_wager import lifetime_wager_rub


def _ts(hour=12):
    return datetime(2026, 8, 30, hour, 0, tzinfo=timezone.utc)


def _cub_row(game_id, hour=10):
    return {
        "game_id": game_id,
        "game_type": "cub",
        "creator_id": 9,
        "opponent_id": None,
        "bet_rub": Decimal("10"),
        "payout_rub": Decimal("0"),
        "winner_id": None,
        "finished_at": _ts(hour),
        "counterparty_kind": "house_robot",
        "game_data": {},
        "rng_commit": None,
        "rng_seed_reveal": None,
        "rng_nonce": None,
        "status": "finished",
    }


def _jackpot_row():
    return {
        "round_id": "jp-new",
        "status": "settled",
        "commit_hash": "aa" * 32,
        "roll": "0.2",
        "winning_ticket": 1,
        "winner_id": 9,
        "pot_rub": Decimal("200"),
        "payout_rub": Decimal("190"),
        "settled_at": _ts(15),
        "amount_rub": Decimal("40"),
        "ticket_from": 0,
        "ticket_to": 3999,
        "total_tickets": 20000,
    }


class _HistoryConn:
    def __init__(self, *, exists=True, by_tag=None):
        self.exists = exists
        self.by_tag = by_tag or {}

    async def fetchrow(self, query, *args):
        if "SELECT 1 AS ok" in query:
            return {"ok": 1} if self.exists else None
        raise AssertionError(query)

    async def fetch(self, query, *args):
        if "casino_jackpot" in query:
            rows = self.by_tag.get("jackpot", [])
        elif "casino_roulette_rounds" in query:
            rows = self.by_tag.get("roulette", [])
        elif "casino_v2_tables" in query:
            rows = self.by_tag.get("v2", [])
        elif "casino_poker_hands" in query:
            rows = self.by_tag.get("poker", [])
        elif "casino_fixed_room" in query:
            rows = self.by_tag.get("room", [])
        elif "casino_clan_war" in query:
            rows = self.by_tag.get("war", [])
        elif "raffle_participants" in query:
            rows = self.by_tag.get("raffle", [])
        elif "FROM casino_games" in query:
            rows = self.by_tag.get("games", [])
        else:
            rows = []
        before = args[1] if len(args) > 1 else None
        limit = int(args[2]) if len(args) > 2 else len(rows)
        types = args[3] if len(args) > 3 else None
        if types:
            wanted = set(types)
            rows = [row for row in rows if str(row.get("game_type") or "") in wanted]
        if before is not None:
            rows = [
                row
                for row in rows
                if (row.get("settled_at") or row.get("finished_at") or row.get("draw_at")) is not None
                and (row.get("settled_at") or row.get("finished_at") or row.get("draw_at")) < before
            ]
        return rows[:limit]


class ShareAndResultTests(unittest.TestCase):
    def test_jackpot_share_is_two_decimals(self):
        self.assertEqual(share_percent(Decimal("183"), Decimal("1000")), "18.30")

    def test_house_game_has_no_share_and_loss_when_payout_zero(self):
        row = _from_game(
            {
                "game_id": "cub-1",
                "game_type": "cub",
                "creator_id": 9,
                "opponent_id": None,
                "bet_rub": Decimal("100"),
                "payout_rub": Decimal("0"),
                "winner_id": None,
                "finished_at": _ts(),
                "counterparty_kind": "house_robot",
                "game_data": {},
                "rng_commit": None,
                "rng_seed_reveal": None,
                "rng_nonce": None,
                "status": "finished",
            },
            9,
        )
        self.assertIsNone(row["share_percent"])
        self.assertEqual(row["result"], "loss")
        self.assertEqual(row["result_label"], "Проигрыш")
        self.assertEqual(row["game_type"], "pvp_dice")
        self.assertEqual(row["href"], "/casino/play/pvp_dice?mode=house")
        self.assertIsNone(row["fairness"])

    def test_pvp_equal_stake_is_fifty_percent_win(self):
        row = _from_game(
            {
                "game_id": "dice-1",
                "game_type": "pvp_dice",
                "creator_id": 9,
                "opponent_id": 8,
                "bet_rub": Decimal("50"),
                "payout_rub": Decimal("95"),
                "winner_id": 9,
                "finished_at": _ts(),
                "counterparty_kind": "player",
                "game_data": {},
                "rng_commit": None,
                "rng_seed_reveal": None,
                "rng_nonce": None,
                "status": "finished",
            },
            9,
        )
        self.assertEqual(row["share_percent"], "50.00")
        self.assertEqual(row["result"], "win")
        self.assertEqual(row["href"], "/casino/duels/dice-1")

    def test_house_push_when_payout_equals_stake(self):
        self.assertEqual(
            classify_result(player_id=1, winner_id=1, stake=100, payout=100, house=True),
            "push",
        )

    def test_jackpot_row_win_fairness_and_share(self):
        row = _from_jackpot(
            {
                "round_id": "jp-1",
                "status": "settled",
                "commit_hash": "aa" * 32,
                "roll": "0.183",
                "winning_ticket": 183,
                "winner_id": 9,
                "pot_rub": Decimal("1000"),
                "payout_rub": Decimal("950"),
                "settled_at": _ts(),
                "amount_rub": Decimal("183"),
                "ticket_from": 0,
                "ticket_to": 18299,
                "total_tickets": 100000,
            },
            9,
        )
        self.assertEqual(row["share_percent"], "18.30")
        self.assertEqual(row["result"], "win")
        self.assertEqual(row["result_label"], "Победа")
        self.assertEqual(row["href"], "/casino/play/jackpot")
        self.assertEqual(row["fairness"]["game_type"], "jackpot")
        self.assertEqual(row["fairness"]["total_tickets"], 100000)
        self.assertEqual(row["fairness"]["expected_ticket"], 183)
        self.assertEqual(row["fairness"]["server_seed"], "0.183")

    def test_jackpot_loser_has_no_seed_until_settled_uses_loss(self):
        row = _from_jackpot(
            {
                "round_id": "jp-2",
                "status": "settled",
                "commit_hash": "bb" * 32,
                "roll": "0.9",
                "winning_ticket": 9,
                "winner_id": 2,
                "pot_rub": Decimal("1000"),
                "payout_rub": Decimal("950"),
                "settled_at": _ts(),
                "amount_rub": Decimal("183"),
                "ticket_from": 0,
                "ticket_to": 18299,
                "total_tickets": 100000,
            },
            9,
        )
        self.assertEqual(row["result"], "loss")
        self.assertIsNotNone(row["fairness"])

    def test_card_fairness_needs_seed_and_commit(self):
        ok = card_fairness(
            game_id="bj-1",
            game_type="blackjack",
            game_data={
                "card_rng": {
                    "server_seed": "ab" * 32,
                    "commit": "cd" * 32,
                    "client_seed": "focuspay",
                    "nonce": 3,
                    "creator_cards": ["A♠", "10♥"],
                }
            },
        )
        self.assertEqual(ok["side"], "creator")
        self.assertEqual(ok["expected_cards"], "A♠ 10♥")
        self.assertIsNone(card_fairness(game_id="bj-1", game_type="blackjack", game_data={}))

    def test_play_href_and_limit(self):
        self.assertEqual(play_href("jackpot"), "/casino/play/jackpot")
        self.assertEqual(play_href("cub"), "/casino/play/pvp_dice?mode=house")
        self.assertEqual(clamp_limit(999), 50)
        self.assertEqual(clamp_grouped_per(99), 20)
        self.assertEqual(clamp_grouped_per(None), 5)
        self.assertEqual(normalize_history_game_type("cub"), "pvp_dice")
        with self.assertRaises(HTTPException) as raised:
            normalize_history_game_type("slots")
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(parse_before("2026-08-30T12:00:00Z").year, 2026)
        with self.assertRaises(HTTPException):
            parse_before("nope")

    def test_poker_fold_hides_seed_and_showdown_publishes_only_the_board(self):
        import json

        folded = _from_poker(
            {
                "hand_key": "hand-fold",
                "table_id": "table-1",
                "settled_at": _ts(),
                "wager_json": {"9": "20.00"},
                "status": "complete",
                "seed_revealed_at": _ts(),
                "server_seed": "ab" * 32,
                "commit_hash": "cd" * 32,
                "client_seed": "focuspay",
                "nonce": 1,
                "game_state": {
                    "street": "complete",
                    "cards_shown": False,
                    "winners": [{"seat_no": 2, "reason": "fold", "amount": "20.00"}],
                    "board_full": ["A♠", "K♠", "Q♠", "J♠", "10♠"],
                    "seats": {"1": {"hole": ["2♣", "3♦"], "user_id": 9}},
                },
            },
            9,
        )
        self.assertIsNone(folded["fairness"])
        folded_blob = json.dumps(folded, ensure_ascii=False, default=str)
        for card in ("2♣", "3♦", "A♠", "10♠"):
            self.assertNotIn(card, folded_blob)

        shown = _from_poker(
            {
                "hand_key": "hand-show",
                "table_id": "table-1",
                "settled_at": _ts(),
                "wager_json": {"9": "20.00"},
                "status": "complete",
                "seed_revealed_at": _ts(),
                "server_seed": "ab" * 32,
                "commit_hash": "cd" * 32,
                "client_seed": "focuspay",
                "nonce": 2,
                "game_state": {
                    "street": "complete",
                    "cards_shown": True,
                    "winners": [{"seat_no": 1, "reason": "showdown", "amount": "40.00"}],
                    "board_full": ["A♠", "K♥", "Q♦", "J♣", "10♠"],
                    "seats": {
                        "1": {"hole": ["9♣", "8♦"], "user_id": 9},
                        "2": {"hole": ["2♣", "3♦"], "folded": True},
                    },
                },
            },
            9,
        )
        fairness = shown["fairness"]
        self.assertIsInstance(fairness, dict)
        self.assertEqual(fairness["server_seed"], "ab" * 32)
        self.assertEqual(fairness["expected_cards"], "A♠ K♥ Q♦ J♣ 10♠")
        shown_blob = json.dumps(shown, ensure_ascii=False, default=str)
        self.assertNotIn("2♣", shown_blob)
        self.assertNotIn("3♦", shown_blob)

    def test_jackpot_fairness_rejects_empty_tickets(self):
        self.assertIsNone(jackpot_fairness(round_id="x", commit="aa", roll="0.1", total_tickets=0, winning_ticket=1))


class PlayerHistoryLoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_player_is_not_found(self):
        with self.assertRaises(HTTPException) as raised:
            await load_player_history(_HistoryConn(exists=False), 99, viewer_id=1)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_merges_sources_newest_first_and_paginates(self):
        jackpot = {
            "round_id": "jp-new",
            "status": "settled",
            "commit_hash": "aa" * 32,
            "roll": "0.2",
            "winning_ticket": 1,
            "winner_id": 9,
            "pot_rub": Decimal("200"),
            "payout_rub": Decimal("190"),
            "settled_at": _ts(15),
            "amount_rub": Decimal("40"),
            "ticket_from": 0,
            "ticket_to": 3999,
            "total_tickets": 20000,
        }
        older_game = {
            "game_id": "cub-old",
            "game_type": "cub",
            "creator_id": 9,
            "opponent_id": None,
            "bet_rub": Decimal("10"),
            "payout_rub": Decimal("0"),
            "winner_id": None,
            "finished_at": _ts(10),
            "counterparty_kind": "house_robot",
            "game_data": {},
            "rng_commit": None,
            "rng_seed_reveal": None,
            "rng_nonce": None,
            "status": "finished",
        }
        conn = _HistoryConn(by_tag={"jackpot": [jackpot], "games": [older_game]})
        first = await load_player_history(conn, 9, viewer_id=1, limit=1)
        self.assertEqual(first["items"][0]["game_type"], "jackpot")
        self.assertEqual(first["items"][0]["round_id"], "jp-new")
        self.assertEqual(first["next_before"], first["items"][0]["settled_at"])
        second = await load_player_history(conn, 9, viewer_id=1, limit=1, before=first["next_before"])
        self.assertEqual(second["items"][0]["round_id"], "cub-old")
        self.assertIsNone(second["next_before"])

    async def test_own_viewer_skips_exists_check(self):
        payload = await load_player_history(_HistoryConn(exists=False), 9, viewer_id=9)
        self.assertEqual(payload["items"], [])
        self.assertTrue(payload["success"])

    async def test_jackpot_filter_does_not_mix_dice(self):
        conn = _HistoryConn(by_tag={"jackpot": [_jackpot_row()], "games": [_cub_row("cub-old", 10)]})
        payload = await load_player_history(conn, 9, viewer_id=1, game_type="jackpot")
        self.assertEqual([item["game_type"] for item in payload["items"]], ["jackpot"])
        self.assertEqual(payload["items"][0]["round_id"], "jp-new")

    async def test_pvp_dice_filter_includes_cub(self):
        conn = _HistoryConn(by_tag={"jackpot": [_jackpot_row()], "games": [_cub_row("cub-old", 10)]})
        payload = await load_player_history(conn, 9, viewer_id=1, game_type="pvp_dice")
        self.assertEqual([item["round_id"] for item in payload["items"]], ["cub-old"])
        self.assertEqual(payload["items"][0]["game_type"], "pvp_dice")

    async def test_grouped_caps_at_five_and_omits_empty(self):
        games = [_cub_row(f"cub-{hour}", hour) for hour in range(10, 16)]
        conn = _HistoryConn(by_tag={"games": games, "jackpot": [_jackpot_row()]})
        payload = await load_player_history_grouped(conn, 9, viewer_id=1, per=5)
        types = [section["game_type"] for section in payload["sections"]]
        self.assertEqual(types, ["pvp_dice", "jackpot"])
        dice = payload["sections"][0]
        self.assertEqual(len(dice["items"]), 5)
        self.assertEqual(dice["items"][0]["round_id"], "cub-15")
        self.assertIsNotNone(dice["next_before"])
        self.assertEqual(payload["sections"][1]["game_type"], "jackpot")
        self.assertIsNone(payload["sections"][1]["next_before"])

    async def test_unknown_game_type_is_bad_request(self):
        with self.assertRaises(HTTPException) as raised:
            await load_player_history(_HistoryConn(), 9, viewer_id=9, game_type="slots")
        self.assertEqual(raised.exception.status_code, 400)


class WagerUnionTests(unittest.IsolatedAsyncioTestCase):
    def test_lifetime_and_weekly_sql_include_v2_tables(self):
        import casino_weekly_wager as weekly_mod

        src = inspect.getsource(weekly_mod)
        self.assertIn("casino_v2_tables", src)
        self.assertIn("def lifetime_wager_rub", src)
        self.assertIn("roulette", src)

    async def test_lifetime_query_uses_sum_without_week_cte(self):
        seen = {}

        class _Conn:
            async def fetchrow(self, query, *args):
                seen["query"] = query
                seen["args"] = args
                return {"wager_rub": Decimal("12.50")}

        amount = await lifetime_wager_rub(_Conn(), 7)
        self.assertEqual(amount, Decimal("12.50"))
        self.assertNotIn("WITH week AS", seen["query"])
        self.assertIn("casino_v2_tables", seen["query"])
        self.assertEqual(seen["args"][0], 7)


class HistoryRouteTests(unittest.TestCase):
    def test_user_history_routes_exist(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath("routers/user_casino.py").read_text(encoding="utf-8")
        self.assertIn('/casino/players/me/history', src)
        self.assertIn("/casino/players/{player_id}/history", src)
        self.assertIn("/casino/players/me/history/grouped", src)
        self.assertIn("/casino/players/{player_id}/history/grouped", src)
        self.assertIn("game_type", src)
