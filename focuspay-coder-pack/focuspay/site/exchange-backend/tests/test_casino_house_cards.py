"""House baccarat/blackjack: HMAC shoe decides hands; 100 ₽ ×2 @ 5% still nets 195."""
from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

async def _dependency_stub(*args, **kwargs):
    raise AssertionError("Database dependency must be patched in unit tests")


sys.modules.setdefault("db", types.SimpleNamespace(get_pool=_dependency_stub))
import routers.internal_casino as internal_casino  # noqa: E402
if isinstance(sys.modules.get("db"), types.SimpleNamespace):
    sys.modules.pop("db", None)

from casino_cards import STANDARD_DECK, baccarat_hand_score, blackjack_hand_score, dealt_cards
from casino_finance import calculate_house_settlement, canonical_casino_settings
from casino_house_cards import (
    BACCARAT_THIRD_AT_OR_BELOW,
    BLACKJACK_HIT_UNTIL,
    act_house_blackjack_with_conn,
    compare_house_cards,
    deal_blackjack_initial,
    deal_house_side_cards,
    hit_blackjack_hand,
    payout_multiplier_for_result,
    play_house_cards_with_conn,
    public_house_cards,
    resolve_house_card_round,
    sequential_blackjack_result,
)
from casino_play import build_play_quote


SEED = "ab" * 32
GAME_ID = "house-baccara-1"


def _settings():
    return canonical_casino_settings(
        [
            {"key": "enabled_games", "value": {"cub": True, "baccara": True, "blackjack": True}},
            {"key": "min_bet_rub", "value": {"amount": 10}},
            {"key": "max_bet_rub", "value": {"amount": 100000}},
            {"key": "commission_rate_wagering_complete", "value": {"percent": 5}},
        ]
    )


class HouseCardRulesTests(unittest.TestCase):
    def test_baccarat_third_card_when_score_is_five_or_less(self):
        two = dealt_cards(SEED, GAME_ID, "creator", 2, client_seed="alice", nonce=3)
        dealt = deal_house_side_cards(
            "baccara", SEED, GAME_ID, "creator", client_seed="alice", nonce=3
        )
        if baccarat_hand_score(two) <= BACCARAT_THIRD_AT_OR_BELOW:
            self.assertEqual(dealt, dealt_cards(SEED, GAME_ID, "creator", 3, client_seed="alice", nonce=3))
            self.assertEqual(len(dealt), 3)
        else:
            self.assertEqual(dealt, two)
            self.assertEqual(len(dealt), 2)
        self.assertNotEqual(dealt, list(STANDARD_DECK[: len(dealt)]))

    def test_blackjack_hits_until_seventeen_from_same_shoe(self):
        cards = deal_house_side_cards(
            "blackjack", SEED, GAME_ID, "opponent", client_seed="alice", nonce=3
        )
        self.assertGreaterEqual(blackjack_hand_score(cards), BLACKJACK_HIT_UNTIL)
        self.assertEqual(
            cards,
            dealt_cards(SEED, GAME_ID, "opponent", len(cards), client_seed="alice", nonce=3),
        )
        self.assertEqual(cards[:2], dealt_cards(SEED, GAME_ID, "opponent", 2, client_seed="alice", nonce=3))

    def test_player_and_house_shoes_differ(self):
        player = deal_house_side_cards("baccara", SEED, GAME_ID, "creator")
        house = deal_house_side_cards("baccara", SEED, GAME_ID, "opponent")
        self.assertNotEqual(player, house)

    def test_blackjack_both_bust_is_tie_and_natural_beats_20(self):
        self.assertEqual(compare_house_cards("blackjack", ["A♠", "K♥"], ["9♦", "8♣"]), "player")
        self.assertEqual(compare_house_cards("blackjack", ["K♥", "Q♦"], ["A♠", "10♣"]), "house")
        self.assertEqual(compare_house_cards("blackjack", ["K♥", "Q♦", "5♣"], ["K♠", "Q♥", "5♦"]), "tie")

    def test_sequential_player_bust_loses_even_if_dealer_would_bust(self):
        player = ["K♥", "Q♦", "5♣"]
        house = ["K♠", "Q♥", "5♦"]
        self.assertGreater(blackjack_hand_score(player), 21)
        self.assertGreater(blackjack_hand_score(house), 21)
        self.assertEqual(sequential_blackjack_result(player, house, player_busted=True), "house")
        self.assertEqual(sequential_blackjack_result(["A♠", "K♥"], ["9♦", "8♣"], player_busted=False), "player")

    def test_blackjack_initial_is_two_cards_and_hides_hole(self):
        player, house = deal_blackjack_initial(SEED, GAME_ID, client_seed="alice", nonce=3)
        self.assertEqual(len(player), 2)
        self.assertEqual(len(house), 2)
        self.assertEqual(player, dealt_cards(SEED, GAME_ID, "creator", 2, client_seed="alice", nonce=3))
        self.assertEqual(house, dealt_cards(SEED, GAME_ID, "opponent", 2, client_seed="alice", nonce=3))
        self.assertEqual(public_house_cards(house, revealed=False), [house[0]])
        self.assertEqual(public_house_cards(house, revealed=True), house)

    def test_hit_continues_the_same_creator_shoe(self):
        two = dealt_cards(SEED, GAME_ID, "creator", 2, client_seed="alice", nonce=3)
        three = hit_blackjack_hand(SEED, GAME_ID, "creator", two, client_seed="alice", nonce=3)
        self.assertEqual(three[:2], two)
        self.assertEqual(three, dealt_cards(SEED, GAME_ID, "creator", 3, client_seed="alice", nonce=3))

    def test_baccarat_higher_mod10_wins(self):
        self.assertEqual(compare_house_cards("baccara", ["A♠", "9♦"], ["K♥", "2♣"]), "house")
        self.assertEqual(compare_house_cards("baccara", ["9♠", "K♦"], ["A♥", "2♣"]), "player")
        self.assertEqual(compare_house_cards("baccara", ["9♠", "K♦"], ["9♥", "10♣"]), "tie")


class HouseCardSettlementTests(unittest.TestCase):
    def test_win_100_times_2_at_5_percent_is_195(self):
        settlement = calculate_house_settlement(Decimal("100"), Decimal("2"), Decimal("5"))
        self.assertEqual(settlement.payout, Decimal("195.00"))
        self.assertEqual(settlement.commission, Decimal("5.00"))
        self.assertEqual(payout_multiplier_for_result("player", win_multiplier=Decimal("2")), Decimal("2"))
        quote = build_play_quote(
            _settings(),
            stake_rub=Decimal("100"),
            payout_multiplier=Decimal("2"),
            commission_rate=Decimal("5"),
            min_bet=Decimal("10"),
            max_bet=Decimal("100000"),
            enabled=True,
            game_type="baccara",
        )
        self.assertEqual(quote["game_type"], "baccara")
        self.assertEqual(quote["win_on_win_rub"], 195.0)
        self.assertIsNone(quote["win_probability"])

    def test_tie_pushes_stake_and_loss_pays_zero(self):
        tie_mult = payout_multiplier_for_result("tie", win_multiplier=Decimal("2"))
        loss_mult = payout_multiplier_for_result("house", win_multiplier=Decimal("2"))
        tie = calculate_house_settlement(Decimal("100"), tie_mult, Decimal("5"))
        loss = calculate_house_settlement(Decimal("100"), loss_mult, Decimal("5"))
        self.assertEqual(tie_mult, Decimal("1"))
        self.assertEqual(tie.payout, Decimal("100.00"))
        self.assertEqual(tie.commission, Decimal("0.00"))
        self.assertEqual(loss.payout, Decimal("0.00"))
        self.assertEqual(loss.house_delta, Decimal("100.00"))

    def test_resolved_round_uses_hmac_shoe_and_house_settlement(self):
        resolved = resolve_house_card_round(
            game_type="baccara",
            seed=SEED,
            game_id=GAME_ID,
            client_seed="alice",
            nonce=3,
            stake_rub=Decimal("100"),
            win_multiplier=Decimal("2"),
            commission_rate=Decimal("5"),
        )
        expected_player = deal_house_side_cards(
            "baccara", SEED, GAME_ID, "creator", client_seed="alice", nonce=3
        )
        expected_house = deal_house_side_cards(
            "baccara", SEED, GAME_ID, "opponent", client_seed="alice", nonce=3
        )
        self.assertEqual(resolved["player_cards"], expected_player)
        self.assertEqual(resolved["house_cards"], expected_house)
        self.assertEqual(
            resolved["result"],
            compare_house_cards("baccara", expected_player, expected_house),
        )
        if resolved["result"] == "player":
            self.assertEqual(resolved["settlement"].payout, Decimal("195.00"))
        elif resolved["result"] == "tie":
            self.assertEqual(resolved["settlement"].payout, Decimal("100.00"))
        else:
            self.assertEqual(resolved["settlement"].payout, Decimal("0.00"))
        source = Path(__file__).resolve().parents[1].joinpath("casino_house_cards.py").read_text()
        self.assertNotIn("digest_value", source)
        self.assertNotIn("cub_presentation_pips", source)


class HouseCardPlayConn:
    def __init__(self):
        self.policy = {
            "id": 9,
            "payout_multiplier": Decimal("2"),
            "win_probability": Decimal("0.5"),
            "terms": {},
        }
        self.profile = {
            "id": 2,
            "account_id": 8,
            "min_bet_rub": Decimal("10"),
            "max_bet_rub": Decimal("100000"),
            "max_exposure_rub": Decimal("0"),
            "account_key": "main",
            "balance_rub": Decimal("50000"),
            "reserved_rub": Decimal("0"),
            "account_active": True,
        }
        self.inserted = None
        self.finished = None
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _execute(self, query, *args):
        if "UPDATE casino_house_rng_commits" in query and "consumed" in query:
            return "UPDATE 1"
        return "UPDATE 1"

    async def _fetchrow(self, query, *args):
        if "FROM casino_games" in query and "FOR UPDATE" in query:
            return None
        if "FROM casino_house_policies" in query:
            return self.policy
        if "FROM casino_robot_profiles" in query:
            return self.profile
        if "INSERT INTO casino_games" in query:
            self.inserted = args
            return {"id": 77}
        if "UPDATE casino_house_accounts" in query and "reserved_rub = reserved_rub + $2" in query:
            return {"balance_rub": Decimal("50000"), "reserved_rub": args[1]}
        if "UPDATE casino_house_accounts" in query and "balance_rub = balance_rub + $2" in query:
            return {"balance_rub": Decimal("49905"), "reserved_rub": Decimal("0")}
        raise AssertionError(query)


class HouseCardPlayTests(unittest.IsolatedAsyncioTestCase):
    async def test_play_inserts_house_robot_and_pays_hmac_result(self):
        conn = HouseCardPlayConn()
        rng = {
            "server_seed": SEED,
            "rng_commit": "aa" * 32,
            "client_seed": "alice",
            "nonce": 3,
            "pair_commit": "bb" * 32,
        }
        expected = resolve_house_card_round(
            game_type="baccara",
            seed=SEED,
            game_id=GAME_ID,
            client_seed="alice",
            nonce=3,
            stake_rub=Decimal("100"),
            win_multiplier=Decimal("2"),
            commission_rate=Decimal("5"),
        )
        settings = _settings()
        with patch("casino_house_cards.lock_casino_game", new=AsyncMock()), patch(
            "casino_house_cards.lock_casino_users", new=AsyncMock()
        ), patch(
            "casino_house_cards.load_casino_settings", new=AsyncMock(return_value=settings)
        ), patch(
            "casino_house_cards.commission_rate_for_player", new=AsyncMock(return_value=Decimal("5"))
        ), patch(
            "casino_house_cards.commission_profile_for_player",
            new=AsyncMock(return_value=("wagering_complete", Decimal("5"))),
        ), patch(
            "casino_house_cards.reserve_unified_funds", new=AsyncMock()
        ), patch(
            "casino_house_cards.confirm_unified_hold", new=AsyncMock()
        ), patch(
            "casino_house_cards.uuid4", return_value=GAME_ID
        ), patch.object(
            internal_casino, "_load_or_create_card_commit", new=AsyncMock(return_value=rng)
        ), patch.object(
            internal_casino, "_assert_stake_within_limits"
        ), patch.object(
            internal_casino, "_credit_winner", new=AsyncMock()
        ), patch.object(
            internal_casino, "_resolve_active_creator_account", new=AsyncMock(return_value=None)
        ), patch.object(
            internal_casino, "_resolve_loser_referrals", new=AsyncMock(return_value=(None, None))
        ), patch.object(
            internal_casino, "_record_commissions", new=AsyncMock()
        ), patch.object(
            internal_casino, "_text_money", side_effect=lambda value: format(Decimal(str(value)), ".2f")
        ), patch.object(
            internal_casino,
            "_pricing_snapshot_payload",
            return_value={
                "commission_rate": "5.00",
                "creator_cut_percent": "1.00",
                "referral_l1_percent": "0.50",
                "referral_l2_percent": "0.50",
                "commission_cap_rub": "0.00",
                "commission_min_rub": "0.00",
            },
        ), patch.object(
            internal_casino, "_snapshot_amount", return_value=Decimal("0")
        ), patch(
            "casino_level_bonus.maybe_grant_reached_level_bonuses", new=AsyncMock()
        ):
            payload = await play_house_cards_with_conn(
                conn, game_type="baccara", telegram_id=11, stake_rub=Decimal("100")
            )
        self.assertEqual(conn.inserted[1], "baccara")
        self.assertEqual(conn.inserted[2], 11)
        self.assertEqual(payload["game_type"], "baccara")
        self.assertEqual(payload["player_cards"], expected["player_cards"])
        self.assertEqual(payload["house_cards"], expected["house_cards"])
        self.assertEqual(payload["stake_rub"], "100.00")
        if expected["result"] == "player":
            self.assertEqual(payload["payout_rub"], "195.00")
            self.assertEqual(payload["outcome"]["kind"], "win")
        elif expected["result"] == "tie":
            self.assertEqual(payload["payout_rub"], "100.00")
            self.assertEqual(payload["outcome"]["kind"], "tie")
        else:
            self.assertEqual(payload["payout_rub"], "0.00")
            self.assertEqual(payload["outcome"]["kind"], "loss")
        self.assertEqual(payload["rng"]["algorithm"], "HMAC-SHA256-fisher-yates-v2")
        self.assertNotIn("threshold", payload["rng"])
        game_data = json.loads(conn.inserted[-1])
        self.assertEqual(game_data["card_rng"]["creator_cards"], payload["player_cards"])
        self.assertEqual(game_data["house_policy_snapshot"]["source_game_type"], "baccara")

    async def test_disabled_game_does_not_play(self):
        conn = HouseCardPlayConn()
        settings = canonical_casino_settings(
            [{"key": "enabled_games", "value": {"baccara": False, "cub": True}}]
        )
        with patch("casino_house_cards.lock_casino_game", new=AsyncMock()), patch(
            "casino_house_cards.lock_casino_users", new=AsyncMock()
        ), patch(
            "casino_house_cards.load_casino_settings", new=AsyncMock(return_value=settings)
        ), patch(
            "casino_house_cards.commission_rate_for_player", new=AsyncMock(return_value=Decimal("5"))
        ), patch(
            "casino_house_cards.commission_profile_for_player",
            new=AsyncMock(return_value=("wagering_complete", Decimal("5"))),
        ):
            with self.assertRaises(HTTPException) as raised:
                await play_house_cards_with_conn(
                    conn, game_type="baccara", telegram_id=11, stake_rub=Decimal("100")
                )
        self.assertEqual(raised.exception.status_code, 409)


def _shoe_without_natural(prefix: str):
    for index in range(400):
        game_id = f"{prefix}-{index}"
        player, house = deal_blackjack_initial(SEED, game_id, client_seed="alice", nonce=3)
        if blackjack_hand_score(player) < 21:
            return game_id, player, house
    raise AssertionError("no blackjack shoe under 21")


def _shoe_bust_on_hit(prefix: str):
    for index in range(2000):
        game_id = f"{prefix}-{index}"
        player, house = deal_blackjack_initial(SEED, game_id, client_seed="alice", nonce=3)
        if blackjack_hand_score(player) >= 21:
            continue
        nxt = dealt_cards(SEED, game_id, "creator", 3, client_seed="alice", nonce=3)
        if blackjack_hand_score(nxt) > 21:
            return game_id, player, house, nxt
    raise AssertionError("no first-hit bust shoe")


def _shoe_natural(prefix: str):
    for index in range(2000):
        game_id = f"{prefix}-{index}"
        player, house = deal_blackjack_initial(SEED, game_id, client_seed="alice", nonce=3)
        if blackjack_hand_score(player) == 21:
            return game_id, player, house
    raise AssertionError("no natural 21 shoe")


class BlackjackHouseConn:
    def __init__(self):
        self.policy = {
            "id": 9,
            "payout_multiplier": Decimal("2"),
            "win_probability": Decimal("0.5"),
            "terms": {},
        }
        self.profile = {
            "id": 2,
            "account_id": 8,
            "min_bet_rub": Decimal("10"),
            "max_bet_rub": Decimal("100000"),
            "max_exposure_rub": Decimal("0"),
            "account_key": "main",
            "balance_rub": Decimal("50000"),
            "reserved_rub": Decimal("0"),
            "account_active": True,
        }
        self.game = None
        self.inserted = None
        self.finished = None
        self.hold_expires = datetime.now(timezone.utc) + timedelta(hours=2)
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _execute(self, query, *args):
        if "SET game_data" in query and "status = 'active'" in query:
            if self.game:
                self.game["game_data"] = json.loads(args[1])
            return "UPDATE 1"
        if "SET status = 'finished'" in query:
            self.finished = args
            if self.game:
                self.game["status"] = "finished"
                self.game["game_data"] = json.loads(args[-1])
            return "UPDATE 1"
        if "UPDATE casino_house_rng_commits" in query and "consumed" in query:
            return "UPDATE 1"
        return "UPDATE 1"

    async def _fetchrow(self, query, *args):
        if "creator_id = $1 AND game_type = 'blackjack'" in query:
            if self.game and self.game.get("status") == "active":
                return self.game
            return None
        if "game_id = $1 AND game_type = 'blackjack'" in query:
            if self.game and self.game.get("status") == "active" and self.game["game_id"] == args[0]:
                return self.game
            return None
        if "FROM casino_house_policies" in query:
            return self.policy
        if "FROM casino_robot_profiles" in query:
            return self.profile
        if "INSERT INTO casino_games" in query:
            self.inserted = args
            self.game = {
                "id": 77,
                "game_id": args[0],
                "creator_id": args[1],
                "bet_rub": args[2],
                "creator_hold_id": args[4],
                "status": "active",
                "house_account_id": args[5],
                "game_data": json.loads(args[-1]),
            }
            return {"id": 77}
        if "UPDATE casino_house_accounts" in query and "reserved_rub = reserved_rub + $2" in query:
            return {"balance_rub": Decimal("50000"), "reserved_rub": args[1]}
        if "UPDATE casino_house_accounts" in query and "balance_rub = balance_rub + $2" in query:
            return {"balance_rub": Decimal("49905"), "reserved_rub": Decimal("0")}
        if "FROM casino_balance_holds" in query:
            return {"expires_at": self.hold_expires}
        raise AssertionError(query)


def _blackjack_patches(conn, rng, settings, game_id):
    return (
        patch("casino_house_cards.lock_casino_game", new=AsyncMock()),
        patch("casino_house_cards.lock_casino_users", new=AsyncMock()),
        patch("casino_house_cards.load_casino_settings", new=AsyncMock(return_value=settings)),
        patch("casino_house_cards.commission_rate_for_player", new=AsyncMock(return_value=Decimal("5"))),
        patch(
            "casino_house_cards.commission_profile_for_player",
            new=AsyncMock(return_value=("wagering_complete", Decimal("5"))),
        ),
        patch("casino_house_cards.reserve_unified_funds", new=AsyncMock()),
        patch("casino_house_cards.confirm_unified_hold", new=AsyncMock()),
        patch("casino_house_cards.uuid4", return_value=game_id),
        patch.object(internal_casino, "_load_or_create_card_commit", new=AsyncMock(return_value=rng)),
        patch.object(internal_casino, "_assert_stake_within_limits"),
        patch.object(internal_casino, "_credit_winner", new=AsyncMock()),
        patch.object(internal_casino, "_resolve_active_creator_account", new=AsyncMock(return_value=None)),
        patch.object(internal_casino, "_resolve_loser_referrals", new=AsyncMock(return_value=(None, None))),
        patch.object(internal_casino, "_record_commissions", new=AsyncMock()),
        patch.object(
            internal_casino, "_text_money", side_effect=lambda value: format(Decimal(str(value)), ".2f")
        ),
        patch.object(
            internal_casino,
            "_pricing_snapshot_payload",
            return_value={
                "commission_rate": "5.00",
                "creator_cut_percent": "1.00",
                "referral_l1_percent": "0.50",
                "referral_l2_percent": "0.50",
                "commission_cap_rub": "0.00",
                "commission_min_rub": "0.00",
            },
        ),
        patch.object(internal_casino, "_snapshot_amount", return_value=Decimal("0")),
        patch("casino_level_bonus.maybe_grant_reached_level_bonuses", new=AsyncMock()),
    )


class HouseBlackjackPlayTests(unittest.IsolatedAsyncioTestCase):
    async def test_deal_hides_hole_and_does_not_reveal_seed(self):
        game_id, player, house = _shoe_without_natural("open")
        conn = BlackjackHouseConn()
        rng = {
            "server_seed": SEED,
            "rng_commit": "aa" * 32,
            "client_seed": "alice",
            "nonce": 3,
            "pair_commit": "bb" * 32,
        }
        with _nested(_blackjack_patches(conn, rng, _settings(), game_id)):
            payload = await play_house_cards_with_conn(
                conn, game_type="blackjack", telegram_id=11, stake_rub=Decimal("100")
            )
            replay = await play_house_cards_with_conn(
                conn, game_type="blackjack", telegram_id=11, stake_rub=Decimal("50")
            )
        self.assertEqual(payload["phase"], "player_turn")
        self.assertEqual(payload["actions"], ["hit", "stand"])
        self.assertEqual(payload["player_cards"], player)
        self.assertEqual(payload["house_cards"], [house[0]])
        self.assertEqual(payload["house_up"], house[0])
        self.assertEqual(payload["house_hidden"], 1)
        self.assertNotIn("seed", payload["rng"])
        self.assertNotEqual(payload["rng"]["house_cards"], house)
        stored = conn.game["game_data"]["card_rng"]["opponent_cards"]
        self.assertEqual(stored, house)
        self.assertEqual(payload["payout_rub"], "0.00")
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["game_id"], game_id)
        self.assertEqual(replay["house_cards"], [house[0]])

    async def test_hit_keeps_shoe_prefix_and_bust_settles_loss_without_dealer_hits(self):
        game_id, player, house, busted = _shoe_bust_on_hit("bust")
        conn = BlackjackHouseConn()
        rng = {
            "server_seed": SEED,
            "rng_commit": "aa" * 32,
            "client_seed": "alice",
            "nonce": 3,
            "pair_commit": "bb" * 32,
        }
        with _nested(_blackjack_patches(conn, rng, _settings(), game_id)):
            dealt = await play_house_cards_with_conn(
                conn, game_type="blackjack", telegram_id=11, stake_rub=Decimal("100")
            )
            self.assertEqual(dealt["phase"], "player_turn")
            payload = await act_house_blackjack_with_conn(
                conn, telegram_id=11, game_id=game_id, action="hit"
            )
        self.assertEqual(payload["phase"], "finished")
        self.assertEqual(payload["outcome"]["kind"], "loss")
        self.assertEqual(payload["payout_rub"], "0.00")
        self.assertEqual(payload["player_cards"], busted)
        self.assertEqual(payload["house_cards"], house)
        self.assertEqual(len(payload["house_cards"]), 2)

    async def test_stand_lets_dealer_draw_to_seventeen(self):
        game_id, player, house = _shoe_without_natural("stand")
        conn = BlackjackHouseConn()
        rng = {
            "server_seed": SEED,
            "rng_commit": "aa" * 32,
            "client_seed": "alice",
            "nonce": 3,
            "pair_commit": "bb" * 32,
        }
        expected_house = deal_house_side_cards(
            "blackjack", SEED, game_id, "opponent", client_seed="alice", nonce=3
        )
        with _nested(_blackjack_patches(conn, rng, _settings(), game_id)):
            await play_house_cards_with_conn(
                conn, game_type="blackjack", telegram_id=11, stake_rub=Decimal("100")
            )
            payload = await act_house_blackjack_with_conn(
                conn, telegram_id=11, game_id=game_id, action="stand"
            )
        self.assertEqual(payload["phase"], "finished")
        self.assertEqual(payload["house_hidden"], 0)
        self.assertEqual(payload["house_cards"], expected_house)
        self.assertGreaterEqual(blackjack_hand_score(payload["house_cards"]), BLACKJACK_HIT_UNTIL)
        self.assertEqual(payload["player_cards"], player)
        self.assertIn(payload["outcome"]["kind"], {"win", "tie", "loss"})
        if payload["outcome"]["kind"] == "win":
            self.assertEqual(payload["payout_rub"], "195.00")
        elif payload["outcome"]["kind"] == "tie":
            self.assertEqual(payload["payout_rub"], "100.00")
        else:
            self.assertEqual(payload["payout_rub"], "0.00")
        self.assertEqual(payload["rng"]["seed"], SEED)

    async def test_natural_twenty_one_skips_buttons_and_plays_dealer(self):
        game_id, player, house = _shoe_natural("nat")
        conn = BlackjackHouseConn()
        rng = {
            "server_seed": SEED,
            "rng_commit": "aa" * 32,
            "client_seed": "alice",
            "nonce": 3,
            "pair_commit": "bb" * 32,
        }
        expected_house = deal_house_side_cards(
            "blackjack", SEED, game_id, "opponent", client_seed="alice", nonce=3
        )
        with _nested(_blackjack_patches(conn, rng, _settings(), game_id)):
            payload = await play_house_cards_with_conn(
                conn, game_type="blackjack", telegram_id=11, stake_rub=Decimal("100")
            )
        self.assertEqual(blackjack_hand_score(player), 21)
        self.assertEqual(payload["phase"], "finished")
        self.assertEqual(payload["actions"], [])
        self.assertEqual(payload["house_cards"], expected_house)
        self.assertEqual(payload["house_hidden"], 0)
        if blackjack_hand_score(expected_house) == 21:
            self.assertEqual(payload["outcome"]["kind"], "tie")
            self.assertEqual(payload["payout_rub"], "100.00")
        else:
            self.assertEqual(payload["outcome"]["kind"], "win")
            self.assertEqual(payload["payout_rub"], "195.00")


def _nested(patches):
    from contextlib import ExitStack

    stack = ExitStack()
    for item in patches:
        stack.enter_context(item)
    return stack


if __name__ == "__main__":
    unittest.main()
