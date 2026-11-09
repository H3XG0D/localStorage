"""European roulette: 37 pockets, HMAC draw, red/black 1:1 and zero 35:1.

Money checks are exact numbers on purpose: 10 ₽ on red at 0% pays 20 ₽ (profit 10),
10 ₽ on zero pays 360 ₽ (profit 350), a loss pays 0.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("Database dependency must be patched in unit tests")


sys.modules.setdefault("db", types.SimpleNamespace(get_pool=_dependency_stub))
import routers.internal_casino as internal_casino  # noqa: E402
if isinstance(sys.modules.get("db"), types.SimpleNamespace):
    sys.modules.pop("db", None)

from casino_finance import KNOWN_GAME_TYPES, calculate_house_settlement, canonical_casino_settings  # noqa: E402
from casino_play import (  # noqa: E402
    HOUSE_PLAY_GAME_TYPES,
    build_tape_row,
    load_roulette_play_quote,
    tape_row_result,
)
from casino_roulette import (  # noqa: E402
    BLACK_POCKETS,
    DEFAULT_ROULETTE_BET,
    MAX_COVER,
    POCKET_COUNT,
    RED_POCKETS,
    ROULETTE_ALGORITHM,
    ROULETTE_BET_KEY_MAX_LENGTH,
    ROULETTE_BET_KEYS,
    ROULETTE_BETS,
    ROULETTE_GAME_TYPE,
    STRAIGHT_RETURN,
    WHEEL_ORDER,
    apply_roulette_stake_window,
    bet_spec,
    bet_wins,
    canonical_roulette_bet_key,
    clamp_held_roulette_payout,
    payout_multiplier_for_bet,
    load_roulette_house_seat,
    play_roulette_with_conn,
    pocket_color,
    pocket_message,
    public_bet_table,
    resolve_roulette_round,
    roulette_pocket,
    verify_roulette_round,
    wheel_position,
)
from casino_settings_registry import GAME_KEYS  # noqa: E402
from casino_weekly_wager import CASHBACK_GAME_TYPES  # noqa: E402

SEED = "cd" * 32
GAME_ID = "roulette-round-1"
CLIENT_SEED = "alice"
NONCE = 7

#: Physical single-zero wheel, taken from a real European table, not from code.
CANONICAL_WHEEL = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
)
CANONICAL_RED = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)
CANONICAL_BLACK = frozenset(
    {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
)


def _settings(*, enabled: bool = True, commission_percent: int = 5):
    return canonical_casino_settings(
        [
            {"key": "enabled_games", "value": {"cub": True, "roulette": enabled}},
            {"key": "min_bet_rub", "value": {"amount": 10}},
            {"key": "max_bet_rub", "value": {"amount": 100000}},
            {"key": "commission_rate_wagering_complete", "value": {"percent": commission_percent}},
        ]
    )


def _game_id_for_color(prefix: str, color: str) -> str:
    for index in range(4000):
        game_id = f"{prefix}-{index}"
        pocket = roulette_pocket(SEED, game_id, client_seed=CLIENT_SEED, nonce=NONCE)
        if pocket_color(pocket) == color:
            return game_id
    raise AssertionError(f"no {color} pocket in the sampled range")


def _game_id_for_pocket(prefix: str, pocket: int) -> str:
    for index in range(8000):
        game_id = f"{prefix}-{index}"
        drawn = roulette_pocket(SEED, game_id, client_seed=CLIENT_SEED, nonce=NONCE)
        if drawn == pocket:
            return game_id
    raise AssertionError(f"no pocket {pocket} in the sampled range")


class RouletteWheelTests(unittest.TestCase):
    def test_wheel_is_single_zero_european_order(self):
        self.assertEqual(WHEEL_ORDER, CANONICAL_WHEEL)
        self.assertEqual(len(WHEEL_ORDER), 37)
        self.assertEqual(len(set(WHEEL_ORDER)), 37)
        self.assertEqual(set(WHEEL_ORDER), set(range(37)))
        self.assertEqual(WHEEL_ORDER[0], 0)
        self.assertNotEqual(WHEEL_ORDER, tuple(range(37)))

    def test_no_american_double_zero(self):
        self.assertEqual(POCKET_COUNT, 37)
        self.assertEqual(max(WHEEL_ORDER), 36)
        self.assertEqual(len([pocket for pocket in WHEEL_ORDER if pocket == 0]), 1)
        self.assertEqual(
            len([pocket for pocket in WHEEL_ORDER if pocket_color(pocket) == "green"]), 1
        )

    def test_colours_are_eighteen_each_plus_one_green(self):
        self.assertEqual(RED_POCKETS, CANONICAL_RED)
        self.assertEqual(BLACK_POCKETS, CANONICAL_BLACK)
        self.assertEqual(len(RED_POCKETS), 18)
        self.assertEqual(len(BLACK_POCKETS), 18)
        self.assertEqual(RED_POCKETS & BLACK_POCKETS, frozenset())
        self.assertEqual(RED_POCKETS | BLACK_POCKETS, frozenset(range(1, 37)))
        self.assertNotIn(0, RED_POCKETS | BLACK_POCKETS)

    def test_every_pocket_has_one_colour_and_one_wheel_seat(self):
        seats = set()
        greens = []
        reds = []
        blacks = []
        for pocket in range(POCKET_COUNT):
            colour = pocket_color(pocket)
            self.assertIn(colour, {"green", "red", "black"})
            {"green": greens, "red": reds, "black": blacks}[colour].append(pocket)
            seat = wheel_position(pocket)
            self.assertEqual(WHEEL_ORDER[seat], pocket)
            seats.add(seat)
        self.assertEqual(greens, [0])
        self.assertEqual(len(reds), 18)
        self.assertEqual(len(blacks), 18)
        self.assertEqual(seats, set(range(POCKET_COUNT)))

    def test_known_pockets_keep_their_table_colour(self):
        self.assertEqual(pocket_color(0), "green")
        for pocket in (1, 3, 12, 19, 32, 36):
            self.assertEqual(pocket_color(pocket), "red", pocket)
        for pocket in (2, 4, 15, 26, 33, 35):
            self.assertEqual(pocket_color(pocket), "black", pocket)

    def test_pocket_outside_the_wheel_is_rejected(self):
        for bad in (-1, 37, 38, 100):
            with self.assertRaises(ValueError):
                pocket_color(bad)
            with self.assertRaises(ValueError):
                wheel_position(bad)


class RoulettePayoutTests(unittest.TestCase):
    def test_odds_are_one_to_one_and_thirty_five_to_one(self):
        self.assertEqual(ROULETTE_BET_KEYS[0:3], ("red", "black", "zero"))
        self.assertIn("dozen1", ROULETTE_BET_KEYS)
        self.assertIn("even", ROULETTE_BET_KEYS)
        self.assertEqual(ROULETTE_BETS["red"].payout_multiplier, Decimal("2"))
        self.assertEqual(ROULETTE_BETS["black"].payout_multiplier, Decimal("2"))
        self.assertEqual(ROULETTE_BETS["zero"].payout_multiplier, Decimal("36"))
        self.assertEqual(ROULETTE_BETS["red"].profit_ratio, Decimal("1"))
        self.assertEqual(ROULETTE_BETS["black"].profit_ratio, Decimal("1"))
        self.assertEqual(ROULETTE_BETS["zero"].profit_ratio, Decimal("35"))
        self.assertEqual(ROULETTE_BETS["red"].odds_ru, "1:1")
        self.assertEqual(ROULETTE_BETS["zero"].odds_ru, "35:1")

    def test_win_chances_are_18_37_and_1_37(self):
        self.assertEqual(ROULETTE_BETS["red"].win_probability, Decimal(18) / Decimal(37))
        self.assertEqual(ROULETTE_BETS["black"].win_probability, Decimal(18) / Decimal(37))
        self.assertEqual(ROULETTE_BETS["zero"].win_probability, Decimal(1) / Decimal(37))

    def test_every_pocket_against_every_bet(self):
        for pocket in range(POCKET_COUNT):
            colour = pocket_color(pocket)
            self.assertEqual(bet_wins("red", pocket), colour == "red", pocket)
            self.assertEqual(bet_wins("black", pocket), colour == "black", pocket)
            self.assertEqual(bet_wins("zero", pocket), pocket == 0, pocket)
            self.assertEqual(
                payout_multiplier_for_bet("red", pocket),
                Decimal("2") if colour == "red" else Decimal("0"),
                pocket,
            )
            self.assertEqual(
                payout_multiplier_for_bet("black", pocket),
                Decimal("2") if colour == "black" else Decimal("0"),
                pocket,
            )
            self.assertEqual(
                payout_multiplier_for_bet("zero", pocket),
                Decimal("36") if pocket == 0 else Decimal("0"),
                pocket,
            )

    def test_zero_loses_red_and_black(self):
        self.assertFalse(bet_wins("red", 0))
        self.assertFalse(bet_wins("black", 0))
        self.assertTrue(bet_wins("zero", 0))

    def test_unknown_bet_is_rejected(self):
        for bad in ("", "green", "REDD", "split", None, "37", "-1", "1.5", "dozen"):
            with self.assertRaises(HTTPException) as raised:
                bet_spec(bad)
            self.assertEqual(raised.exception.status_code, 400)

    def test_named_outside_bets_and_aliases(self):
        self.assertEqual(bet_spec("1rd").key, "dozen1")
        self.assertEqual(bet_spec("1-12").key, "dozen1")
        self.assertEqual(bet_spec("красное").key, "red")
        self.assertEqual(bet_spec("чёрное").key, "black")
        self.assertEqual(bet_spec("even").key, "even")
        self.assertEqual(bet_spec("чёт").key, "even")
        self.assertEqual(bet_spec("нечет").key, "odd")
        self.assertEqual(bet_spec("low").pockets, frozenset(range(1, 19)))
        self.assertEqual(bet_spec("1col").key, "col1")
        self.assertEqual(bet_spec("dozen1").payout_multiplier, Decimal("3"))
        self.assertEqual(bet_spec("dozen1").odds_ru, "2:1")
        self.assertTrue(bet_wins("dozen1", 12))
        self.assertFalse(bet_wins("dozen1", 13))
        self.assertFalse(bet_wins("even", 0))
        self.assertTrue(bet_wins("even", 2))
        self.assertEqual(len(bet_spec("col1").pockets), 12)

    def test_bet_keys_are_case_insensitive_but_exact(self):
        self.assertEqual(bet_spec("RED").key, "red")
        self.assertEqual(bet_spec(" black ").key, "black")
        self.assertEqual(DEFAULT_ROULETTE_BET, "red")

    def test_straight_up_numbers_pay_the_same_as_zero(self):
        zero = bet_spec("zero")
        alias = bet_spec("0")
        self.assertEqual(alias.key, "zero")
        self.assertEqual(alias.payout_multiplier, Decimal("36"))
        self.assertEqual(alias.pockets, frozenset({0}))
        for pocket in range(1, POCKET_COUNT):
            spec = bet_spec(str(pocket))
            self.assertEqual(spec.key, str(pocket))
            self.assertEqual(spec.payout_multiplier, Decimal("36"))
            self.assertEqual(spec.profit_ratio, Decimal("35"))
            self.assertEqual(spec.odds_ru, "35:1")
            self.assertEqual(spec.pockets, frozenset({pocket}))
            self.assertTrue(bet_wins(str(pocket), pocket))
            self.assertFalse(bet_wins(str(pocket), (pocket + 1) % POCKET_COUNT))
            self.assertEqual(
                payout_multiplier_for_bet(str(pocket), pocket),
                Decimal("36"),
            )
            self.assertEqual(
                payout_multiplier_for_bet(str(pocket), (pocket + 1) % POCKET_COUNT),
                Decimal("0"),
            )
        self.assertEqual(zero.payout_multiplier, Decimal("36"))

    def test_cover_ten_numbers_pays_three_point_six_not_thirty_six(self):
        pockets = tuple(range(1, 11))
        key = ",".join(str(pocket) for pocket in pockets)
        spec = bet_spec(key)
        self.assertEqual(spec.key, "1,2,3,4,5,6,7,8,9,10")
        self.assertEqual(spec.payout_multiplier, Decimal("3.6"))
        self.assertEqual(spec.payout_multiplier, STRAIGHT_RETURN / Decimal(10))
        self.assertEqual(spec.profit_ratio, Decimal("2.6"))
        self.assertEqual(spec.odds_ru, "2.6:1")
        self.assertEqual(spec.win_probability, Decimal(10) / Decimal(37))
        self.assertEqual(spec.pockets, frozenset(pockets))
        self.assertTrue(bet_wins(key, 7))
        self.assertFalse(bet_wins(key, 0))
        self.assertFalse(bet_wins(key, 36))
        self.assertEqual(payout_multiplier_for_bet(key, 10), Decimal("3.6"))
        self.assertEqual(payout_multiplier_for_bet(key, 11), Decimal("0"))

    def test_cover_canonicalizes_order_and_duplicates(self):
        spec = bet_spec("10, 1,1, 2")
        self.assertEqual(spec.key, "1,2,10")
        self.assertEqual(spec.payout_multiplier, Decimal("12"))
        self.assertEqual(spec.odds_ru, "11:1")
        self.assertEqual(canonical_roulette_bet_key((10, 1, 2)), "1,2,10")

    def test_cover_two_is_a_split(self):
        spec = bet_spec("17,20")
        self.assertEqual(spec.payout_multiplier, Decimal("18"))
        self.assertEqual(spec.odds_ru, "17:1")
        self.assertEqual(spec.profit_ratio, Decimal("17"))

    def test_cover_including_zero_is_not_the_zero_straight(self):
        spec = bet_spec("0,1")
        self.assertEqual(spec.key, "0,1")
        self.assertNotEqual(spec.key, "zero")
        self.assertEqual(spec.payout_multiplier, Decimal("18"))
        self.assertTrue(bet_wins("0,1", 0))
        self.assertTrue(bet_wins("0,1", 1))
        self.assertFalse(bet_wins("0,1", 2))

    def test_cover_rejects_the_whole_wheel(self):
        whole = ",".join(str(pocket) for pocket in range(POCKET_COUNT))
        with self.assertRaises(HTTPException) as raised:
            bet_spec(whole)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertGreater(len(whole), 16)
        self.assertLessEqual(len(whole), ROULETTE_BET_KEY_MAX_LENGTH)
        self.assertEqual(MAX_COVER, 36)

    def test_classic_inside_returns_match_the_felt(self):
        self.assertEqual(bet_spec("8,9,11,12").payout_multiplier, Decimal("9"))
        self.assertEqual(bet_spec("8,9,11,12").odds_ru, "8:1")
        self.assertEqual(bet_spec("1,2,3,4,5,6").payout_multiplier, Decimal("6"))
        self.assertEqual(bet_spec("1,2,3,4,5,6").odds_ru, "5:1")

    def test_public_bet_table_matches_the_specs(self):
        table = public_bet_table()
        self.assertEqual([item["key"] for item in table], list(ROULETTE_BET_KEYS))
        zero = next(item for item in table if item["key"] == "zero")
        self.assertEqual(zero["payout_multiplier"], 36.0)
        self.assertEqual(zero["profit_ratio"], 35.0)
        self.assertEqual(zero["pockets"], [0])
        red = next(item for item in table if item["key"] == "red")
        self.assertEqual(red["pockets"], sorted(CANONICAL_RED))


class RouletteSettlementTests(unittest.TestCase):
    def _resolve(self, *, game_id: str, bet: str, stake: str, commission: str):
        return resolve_roulette_round(
            seed=SEED,
            game_id=game_id,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            stake_rub=Decimal(stake),
            bet=bet,
            commission_rate=Decimal(commission),
        )

    def test_red_win_without_commission_returns_stake_plus_equal_profit(self):
        game_id = _game_id_for_color("settle-red", "red")
        resolved = self._resolve(game_id=game_id, bet="red", stake="10", commission="0")
        settlement = resolved["settlement"]
        self.assertTrue(resolved["won"])
        self.assertEqual(resolved["color"], "red")
        self.assertEqual(settlement.stake, Decimal("10.00"))
        self.assertEqual(settlement.payout, Decimal("20.00"))
        self.assertEqual(settlement.commission, Decimal("0.00"))
        self.assertEqual(settlement.payout - settlement.stake, Decimal("10.00"))
        self.assertEqual(settlement.house_delta, Decimal("-10.00"))

    def test_zero_win_without_commission_pays_thirty_five_to_one(self):
        game_id = _game_id_for_color("settle-zero", "green")
        resolved = self._resolve(game_id=game_id, bet="zero", stake="10", commission="0")
        settlement = resolved["settlement"]
        self.assertTrue(resolved["won"])
        self.assertEqual(resolved["pocket"], 0)
        self.assertEqual(resolved["color"], "green")
        self.assertEqual(settlement.payout, Decimal("360.00"))
        self.assertEqual(settlement.payout - settlement.stake, Decimal("350.00"))

    def test_straight_up_number_pays_the_same_as_zero(self):
        game_id = _game_id_for_pocket("settle-n17", 17)
        resolved = self._resolve(game_id=game_id, bet="17", stake="10", commission="0")
        settlement = resolved["settlement"]
        self.assertEqual(resolved["pocket"], 17)
        self.assertTrue(resolved["won"])
        self.assertEqual(resolved["bet"], "17")
        self.assertEqual(resolved["payout_multiplier"], Decimal("36"))
        self.assertEqual(settlement.payout, Decimal("360.00"))
        miss = self._resolve(game_id=game_id, bet="16", stake="10", commission="0")
        self.assertFalse(miss["won"])
        self.assertEqual(miss["settlement"].payout, Decimal("0.00"))

    def test_held_seat_payout_clamps_to_the_reserve_instead_of_409(self):
        live = calculate_house_settlement(Decimal("100"), Decimal("36"), Decimal("0"))
        self.assertEqual(live.payout, Decimal("3600.00"))
        clamped = clamp_held_roulette_payout(live, Decimal("3425"))
        self.assertEqual(clamped.payout, Decimal("3425.00"))
        self.assertEqual(clamped.house_delta, Decimal("-3325.00"))
        same = clamp_held_roulette_payout(live, Decimal("3600"))
        self.assertEqual(same.payout, Decimal("3600.00"))

    def test_ten_number_cover_win_returns_three_point_six_times_the_stake(self):
        game_id = _game_id_for_pocket("settle-cover10", 7)
        bet = "1,2,3,4,5,6,7,8,9,10"
        resolved = self._resolve(game_id=game_id, bet=bet, stake="10", commission="0")
        settlement = resolved["settlement"]
        self.assertEqual(resolved["pocket"], 7)
        self.assertTrue(resolved["won"])
        self.assertEqual(resolved["bet"], bet)
        self.assertEqual(resolved["payout_multiplier"], Decimal("3.6"))
        self.assertEqual(settlement.payout, Decimal("36.00"))
        self.assertEqual(settlement.payout - settlement.stake, Decimal("26.00"))
        miss = self._resolve(game_id=game_id, bet="11,12,13", stake="10", commission="0")
        self.assertFalse(miss["won"])
        self.assertEqual(miss["settlement"].payout, Decimal("0.00"))

    def test_ten_number_cover_at_five_percent(self):
        game_id = _game_id_for_pocket("commission-cover10", 1)
        resolved = self._resolve(
            game_id=game_id, bet="1,2,3,4,5,6,7,8,9,10", stake="10", commission="5"
        )
        settlement = resolved["settlement"]
        self.assertTrue(resolved["won"])
        # 10 × 3.6 = 36 gross, profit 26, 5% → 1.30, payout 34.70
        self.assertEqual(settlement.commission, Decimal("1.30"))
        self.assertEqual(settlement.payout, Decimal("34.70"))

    def test_red_win_at_five_percent_keeps_commission_off_the_profit_only(self):
        game_id = _game_id_for_color("commission-red", "red")
        resolved = self._resolve(game_id=game_id, bet="red", stake="100", commission="5")
        settlement = resolved["settlement"]
        self.assertEqual(settlement.commission, Decimal("5.00"))
        self.assertEqual(settlement.payout, Decimal("195.00"))

    def test_zero_win_at_five_percent(self):
        game_id = _game_id_for_color("commission-zero", "green")
        resolved = self._resolve(game_id=game_id, bet="zero", stake="10", commission="5")
        settlement = resolved["settlement"]
        self.assertEqual(settlement.commission, Decimal("17.50"))
        self.assertEqual(settlement.payout, Decimal("342.50"))

    def test_loss_takes_the_whole_stake_and_pays_nothing(self):
        game_id = _game_id_for_color("settle-black", "black")
        resolved = self._resolve(game_id=game_id, bet="red", stake="10", commission="5")
        settlement = resolved["settlement"]
        self.assertFalse(resolved["won"])
        self.assertEqual(resolved["payout_multiplier"], Decimal("0"))
        self.assertEqual(settlement.payout, Decimal("0.00"))
        self.assertEqual(settlement.commission, Decimal("0.00"))
        self.assertEqual(settlement.house_delta, Decimal("10.00"))

    def test_zero_makes_a_red_bet_lose_everything(self):
        game_id = _game_id_for_color("zero-kills-red", "green")
        resolved = self._resolve(game_id=game_id, bet="red", stake="50", commission="5")
        self.assertEqual(resolved["pocket"], 0)
        self.assertFalse(resolved["won"])
        self.assertEqual(resolved["settlement"].payout, Decimal("0.00"))

    def test_fractional_stake_stays_on_kopecks(self):
        game_id = _game_id_for_color("kopeck", "red")
        resolved = self._resolve(game_id=game_id, bet="red", stake="0.03", commission="5")
        settlement = resolved["settlement"]
        self.assertEqual(settlement.stake, Decimal("0.03"))
        self.assertEqual(settlement.payout, Decimal("0.06"))

    def test_very_large_stake_keeps_exact_decimal_math(self):
        game_id = _game_id_for_color("whale", "green")
        resolved = self._resolve(game_id=game_id, bet="zero", stake="1000000", commission="0")
        self.assertEqual(resolved["settlement"].payout, Decimal("36000000.00"))


class RouletteRngTests(unittest.TestCase):
    def test_draw_is_deterministic_and_inside_the_wheel(self):
        first = roulette_pocket(SEED, GAME_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        again = roulette_pocket(SEED, GAME_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        self.assertEqual(first, again)
        self.assertTrue(0 <= first < POCKET_COUNT)

    def test_all_thirty_seven_pockets_are_reachable(self):
        seen = {
            roulette_pocket(SEED, f"spread-{index}", client_seed=CLIENT_SEED, nonce=NONCE)
            for index in range(4000)
        }
        self.assertEqual(seen, set(range(POCKET_COUNT)))

    def test_seed_client_seed_nonce_and_game_id_all_change_the_pocket(self):
        base = roulette_pocket(SEED, GAME_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        variants = {
            roulette_pocket("ef" * 32, GAME_ID, client_seed=CLIENT_SEED, nonce=NONCE),
            roulette_pocket(SEED, "other-round", client_seed=CLIENT_SEED, nonce=NONCE),
            roulette_pocket(SEED, GAME_ID, client_seed="bob", nonce=NONCE),
            roulette_pocket(SEED, GAME_ID, client_seed=CLIENT_SEED, nonce=NONCE + 1),
        }
        self.assertTrue(any(value != base for value in variants))

    def test_message_shape_is_the_documented_one(self):
        self.assertEqual(
            pocket_message(client_seed=CLIENT_SEED, nonce=NONCE, game_id=GAME_ID),
            f"{CLIENT_SEED}:{NONCE}:{GAME_ID}:pocket",
        )

    def test_module_never_uses_local_randomness(self):
        source = Path(__file__).resolve().parents[1].joinpath("casino_roulette.py").read_text()
        self.assertNotIn("import random", source)
        self.assertNotIn("random.", source)
        self.assertNotIn("secrets.", source)
        self.assertIn("hmac.new", source)


class RouletteVerifyTests(unittest.TestCase):
    def _commit(self, game_id: str = GAME_ID) -> str:
        from casino_cards import game_commit

        return game_commit(SEED, game_id)

    def test_correct_seed_and_pocket_verify(self):
        pocket = roulette_pocket(SEED, GAME_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        result = verify_roulette_round(
            server_seed=SEED,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            game_id=GAME_ID,
            commit=self._commit(),
            expected_pocket=pocket,
        )
        self.assertTrue(result["matches"])
        self.assertTrue(result["commit_matches"])
        self.assertTrue(result["pocket_matches"])
        self.assertEqual(result["pocket"], pocket)
        self.assertEqual(result["modulus"], POCKET_COUNT)
        self.assertEqual(result["algorithm"], ROULETTE_ALGORITHM)

    def test_tampered_seed_does_not_verify(self):
        tampered = "a" + SEED[1:]
        result = verify_roulette_round(
            server_seed=tampered,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            game_id=GAME_ID,
            commit=self._commit(),
        )
        self.assertFalse(result["matches"])
        self.assertFalse(result["commit_matches"])

    def test_wrong_expected_pocket_does_not_verify(self):
        pocket = roulette_pocket(SEED, GAME_ID, client_seed=CLIENT_SEED, nonce=NONCE)
        result = verify_roulette_round(
            server_seed=SEED,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            game_id=GAME_ID,
            commit=self._commit(),
            expected_pocket=(pocket + 1) % POCKET_COUNT,
        )
        self.assertFalse(result["matches"])
        self.assertTrue(result["commit_matches"])
        self.assertFalse(result["pocket_matches"])


class RouletteRegistryTests(unittest.TestCase):
    def test_game_key_is_registered_everywhere_it_is_read(self):
        self.assertIn(ROULETTE_GAME_TYPE, GAME_KEYS)
        self.assertIn(ROULETTE_GAME_TYPE, KNOWN_GAME_TYPES)
        self.assertIn(ROULETTE_GAME_TYPE, HOUSE_PLAY_GAME_TYPES)
        self.assertIn(ROULETTE_GAME_TYPE, CASHBACK_GAME_TYPES)

    def test_settings_carry_the_enabled_flag(self):
        self.assertTrue(_settings().enabled_games[ROULETTE_GAME_TYPE])
        self.assertFalse(_settings(enabled=False).enabled_games[ROULETTE_GAME_TYPE])

    def test_per_game_limits_accept_roulette(self):
        settings = canonical_casino_settings(
            [
                {"key": "enabled_games", "value": {"roulette": True}},
                {"key": "min_bet_rub", "value": {"amount": 10}},
                {"key": "max_bet_rub", "value": {"amount": 100000}},
                {"key": "per_game_limits", "value": {"roulette": {"min": 20, "max": 5000}}},
            ]
        )
        self.assertEqual(
            settings.per_game_limits[ROULETTE_GAME_TYPE],
            {"min": Decimal("20.00"), "max": Decimal("5000.00")},
        )


class RouletteTapeTests(unittest.TestCase):
    def _row(self, outcome):
        return {
            "game_id": "g1",
            "game_type": ROULETTE_GAME_TYPE,
            "creator_id": 11,
            "winner_id": 11,
            "bet_rub": Decimal("100"),
            "payout_rub": Decimal("195"),
            "finished_at": None,
            "outcome": outcome,
        }

    def test_pocket_travels_to_the_tape(self):
        built = build_tape_row(self._row({"pocket": 23, "color": "red", "bet": "red"}), viewer_id=11)
        self.assertEqual(built["result"], {"pocket": 23, "color": "red", "bet": "red"})
        self.assertTrue(built["won"])
        self.assertTrue(built["is_mine"])

    def test_colour_is_recomputed_not_trusted(self):
        built = build_tape_row(self._row({"pocket": 15, "color": "red", "bet": "black"}), viewer_id=None)
        self.assertEqual(built["result"]["color"], "black")

    def test_json_text_outcome_is_parsed(self):
        row = self._row(json.dumps({"pocket": 0, "bet": "zero"}))
        self.assertEqual(tape_row_result(row), {"pocket": 0, "color": "green", "bet": "zero"})

    def test_broken_or_foreign_outcome_yields_no_result(self):
        self.assertIsNone(tape_row_result(self._row(None)))
        self.assertIsNone(tape_row_result(self._row("not json")))
        self.assertIsNone(tape_row_result(self._row({"pocket": 99})))
        self.assertIsNone(tape_row_result(self._row({"kind": "win"})))
        cub = {**self._row({"pocket": 5}), "game_type": "cub"}
        self.assertIsNone(tape_row_result(cub))
        self.assertNotIn("result", build_tape_row(cub, viewer_id=None))


class RouletteQuoteConn:
    def __init__(self, *, profile=True):
        self.profile = (
            {
                "min_bet_rub": Decimal("10"),
                "max_bet_rub": Decimal("100000"),
                "balance_rub": Decimal("5000000"),
            }
            if profile
            else None
        )
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _fetchrow(self, query, *args):
        if "FROM casino_robot_profiles" in query:
            return self.profile
        raise AssertionError(query)


class RouletteQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def _quote(self, *, bet: str, stake: str, profile=True, enabled=True):
        conn = RouletteQuoteConn(profile=profile)
        with patch(
            "casino_play.load_casino_settings", new=AsyncMock(return_value=_settings(enabled=enabled))
        ):
            return await load_roulette_play_quote(
                conn, stake_rub=Decimal(stake), viewer_id=None, bet=bet
            )

    async def test_red_quote_is_even_money(self):
        quote = await self._quote(bet="red", stake="100")
        self.assertEqual(quote["game_type"], ROULETTE_GAME_TYPE)
        self.assertEqual(quote["bet"], "red")
        self.assertEqual(quote["odds_ru"], "1:1")
        self.assertEqual(quote["payout_multiplier"], 2.0)
        self.assertEqual(quote["gross_payout_rub"], 200.0)
        self.assertEqual(quote["win_on_win_rub"], 195.0)
        self.assertTrue(quote["enabled"])
        self.assertIsNone(quote["bound_error"])
        self.assertEqual([item["key"] for item in quote["bets"]], list(ROULETTE_BET_KEYS))

    async def test_zero_quote_is_thirty_five_to_one(self):
        quote = await self._quote(bet="zero", stake="10")
        self.assertEqual(quote["payout_multiplier"], 36.0)
        self.assertEqual(quote["odds_ru"], "35:1")
        self.assertEqual(quote["gross_payout_rub"], 360.0)
        self.assertEqual(quote["profit_ratio"], 35.0)

    async def test_straight_quote_matches_zero_odds_and_max(self):
        number = await self._quote(bet="17", stake="10")
        zero = await self._quote(bet="zero", stake="10")
        self.assertEqual(number["bet"], "17")
        self.assertEqual(number["payout_multiplier"], 36.0)
        self.assertEqual(number["odds_ru"], "35:1")
        self.assertEqual(number["max_bet_rub"], zero["max_bet_rub"])
        alias = await self._quote(bet="0", stake="10")
        self.assertEqual(alias["bet"], "zero")

    async def test_ten_number_cover_quote_is_not_thirty_six(self):
        quote = await self._quote(bet="1,2,3,4,5,6,7,8,9,10", stake="10")
        straight = await self._quote(bet="17", stake="10")
        self.assertEqual(quote["bet"], "1,2,3,4,5,6,7,8,9,10")
        self.assertEqual(quote["payout_multiplier"], 3.6)
        self.assertEqual(quote["odds_ru"], "2.6:1")
        self.assertEqual(quote["profit_ratio"], 2.6)
        self.assertEqual(quote["gross_payout_rub"], 36.0)
        self.assertEqual(quote["win_on_win_rub"], 34.7)
        self.assertGreater(quote["max_bet_rub"], straight["max_bet_rub"])
        shuffled = await self._quote(bet="10,1,2,3,4,5,6,7,8,9", stake="10")
        self.assertEqual(shuffled["bet"], "1,2,3,4,5,6,7,8,9,10")

    async def test_stake_below_minimum_is_reported(self):
        quote = await self._quote(bet="red", stake="1")
        self.assertIn("ниже минимума", str(quote["bound_error"]))

    async def test_zero_bet_max_stake_is_lower_than_even_money(self):
        red = await self._quote(bet="red", stake="100")
        zero = await self._quote(bet="zero", stake="100")
        self.assertLess(zero["max_bet_rub"], red["max_bet_rub"])

    async def test_missing_house_robot_disables_the_quote(self):
        quote = await self._quote(bet="red", stake="100", profile=False)
        self.assertFalse(quote["enabled"])

    async def test_disabled_setting_disables_the_quote(self):
        quote = await self._quote(bet="red", stake="100", enabled=False)
        self.assertFalse(quote["enabled"])


class RouletteStakeWindowTests(unittest.TestCase):
    def test_straight_max_is_tighter_than_even_money(self):
        settings = _settings()
        profile = {
            "min_bet_rub": Decimal("10"),
            "max_bet_rub": Decimal("100000"),
            "balance_rub": Decimal("100000"),
        }
        _, even_hi = apply_roulette_stake_window(settings, Decimal("2"), profile)
        _, straight_hi = apply_roulette_stake_window(settings, STRAIGHT_RETURN, profile)
        self.assertEqual(even_hi, Decimal("1000.00"))
        self.assertEqual(straight_hi, Decimal("28.57"))
        self.assertLess(straight_hi, even_hi)

    def test_robot_exposure_caps_a_straight_below_profit_pct(self):
        settings = _settings()
        profile = {
            "min_bet_rub": Decimal("10"),
            "max_bet_rub": Decimal("100000"),
            "balance_rub": Decimal("100000"),
            "reserved_rub": Decimal("0"),
            "max_exposure_rub": Decimal("1000"),
        }
        _, even_hi = apply_roulette_stake_window(settings, Decimal("2"), profile)
        _, straight_hi = apply_roulette_stake_window(settings, STRAIGHT_RETURN, profile)
        self.assertEqual(even_hi, Decimal("500.00"))
        self.assertEqual(straight_hi, Decimal("27.78"))


class RoulettePlayConn:
    def __init__(self, *, balance=Decimal("500000")):
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
            "balance_rub": balance,
            "reserved_rub": Decimal("0"),
            "account_active": True,
        }
        self.inserted = None
        self.reserved = None
        self.finished = None
        self.ledger = None
        self.executes = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _execute(self, query, *args):
        self.executes.append((query, args))
        if "SET status = 'finished'" in query:
            self.finished = args
        if "INSERT INTO casino_house_ledger" in query:
            self.ledger = args
        return "UPDATE 1"

    async def _fetchrow(self, query, *args):
        if "FROM casino_house_policies" in query:
            return self.policy
        if "FROM casino_robot_profiles" in query:
            return self.profile
        if "INSERT INTO casino_games" in query:
            self.inserted = args
            return {"id": 77}
        if "UPDATE casino_house_accounts" in query and "reserved_rub = reserved_rub + $2" in query:
            self.reserved = args[1]
            return {"balance_rub": self.profile["balance_rub"], "reserved_rub": args[1]}
        if "UPDATE casino_house_accounts" in query and "balance_rub = balance_rub + $2" in query:
            return {"balance_rub": Decimal("499905"), "reserved_rub": Decimal("0")}
        raise AssertionError(query)


def _play_patches(conn, game_id, settings, *, credit):
    rng = {
        "server_seed": SEED,
        "rng_commit": "aa" * 32,
        "client_seed": CLIENT_SEED,
        "nonce": NONCE,
        "pair_commit": "bb" * 32,
    }
    return (
        patch("casino_roulette.lock_casino_game", new=AsyncMock()),
        patch("casino_roulette.lock_casino_users", new=AsyncMock()),
        patch("casino_roulette.load_casino_settings", new=AsyncMock(return_value=settings)),
        patch("casino_roulette.commission_rate_for_player", new=AsyncMock(return_value=Decimal("5"))),
        patch(
            "casino_roulette.commission_profile_for_player",
            new=AsyncMock(return_value=("wagering_complete", Decimal("5"))),
        ),
        patch("casino_roulette.reserve_unified_funds", new=AsyncMock()),
        patch("casino_roulette.confirm_unified_hold", new=AsyncMock()),
        patch("casino_roulette.uuid4", return_value=game_id),
        patch.object(internal_casino, "_load_or_create_card_commit", new=AsyncMock(return_value=rng)),
        patch.object(internal_casino, "_assert_stake_within_limits"),
        patch.object(internal_casino, "_credit_winner", new=credit),
        patch.object(internal_casino, "_resolve_active_creator_account", new=AsyncMock(return_value=None)),
        patch.object(internal_casino, "_resolve_loser_referrals", new=AsyncMock(return_value=(None, None))),
        patch.object(internal_casino, "_record_commissions", new=AsyncMock()),
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


class RoulettePlayTests(unittest.IsolatedAsyncioTestCase):
    async def _play(self, *, game_id, bet, stake, conn=None, settings=None):
        conn = conn or RoulettePlayConn()
        credit = AsyncMock()
        patches = _play_patches(conn, game_id, settings or _settings(), credit=credit)
        for entered in patches:
            entered.start()
        try:
            payload = await play_roulette_with_conn(
                conn, telegram_id=11, stake_rub=Decimal(stake), bet=bet
            )
        finally:
            for entered in reversed(patches):
                entered.stop()
        return conn, payload, credit

    async def test_red_win_writes_history_and_credits_the_player(self):
        game_id = _game_id_for_color("play-red", "red")
        conn, payload, credit = await self._play(game_id=game_id, bet="red", stake="100")
        self.assertEqual(conn.inserted[1], ROULETTE_GAME_TYPE)
        self.assertEqual(conn.inserted[2], 11)
        self.assertEqual(conn.inserted[3], Decimal("100.00"))
        self.assertEqual(payload["game_type"], ROULETTE_GAME_TYPE)
        self.assertEqual(payload["bet"], "red")
        self.assertEqual(payload["color"], "red")
        self.assertTrue(payload["won"])
        self.assertEqual(payload["outcome"]["kind"], "win")
        self.assertEqual(payload["outcome"]["winner_id"], 11)
        self.assertEqual(payload["stake_rub"], "100.00")
        self.assertEqual(payload["payout_rub"], "195.00")
        self.assertEqual(payload["commission_rub"], "5.00")
        self.assertEqual(payload["payout_multiplier"], "2.00")
        credit.assert_awaited_once()
        self.assertEqual(credit.await_args.kwargs["payout_rub"], Decimal("195.00"))
        outcome = json.loads(conn.finished[2])
        self.assertEqual(outcome["pocket"], payload["pocket"])
        self.assertEqual(outcome["color"], "red")
        self.assertEqual(conn.finished[4], Decimal("195.00"))

    async def test_loss_pays_nothing_and_never_credits(self):
        game_id = _game_id_for_color("play-black", "black")
        conn, payload, credit = await self._play(game_id=game_id, bet="red", stake="100")
        self.assertFalse(payload["won"])
        self.assertEqual(payload["outcome"]["kind"], "loss")
        self.assertIsNone(payload["outcome"]["winner_id"])
        self.assertEqual(payload["payout_rub"], "0.00")
        credit.assert_not_awaited()
        self.assertIsNone(conn.finished[1])

    async def test_zero_win_pays_thirty_five_to_one_after_commission(self):
        game_id = _game_id_for_color("play-zero", "green")
        conn, payload, credit = await self._play(game_id=game_id, bet="zero", stake="10")
        self.assertEqual(payload["pocket"], 0)
        self.assertEqual(payload["color"], "green")
        self.assertTrue(payload["won"])
        self.assertEqual(payload["payout_multiplier"], "36.00")
        self.assertEqual(payload["payout_rub"], "342.50")
        self.assertEqual(payload["commission_rub"], "17.50")
        self.assertEqual(credit.await_args.kwargs["payout_rub"], Decimal("342.50"))

    async def test_straight_up_win_pays_the_same_as_zero(self):
        game_id = _game_id_for_pocket("play-n17", 17)
        conn, payload, credit = await self._play(game_id=game_id, bet="17", stake="10")
        self.assertEqual(payload["pocket"], 17)
        self.assertEqual(payload["bet"], "17")
        self.assertTrue(payload["won"])
        self.assertEqual(payload["payout_multiplier"], "36.00")
        self.assertEqual(payload["payout_rub"], "342.50")
        self.assertEqual(credit.await_args.kwargs["payout_rub"], Decimal("342.50"))

    async def test_ten_number_cover_win_credits_three_point_six(self):
        game_id = _game_id_for_pocket("play-cover10", 4)
        conn, payload, credit = await self._play(
            game_id=game_id, bet="1,2,3,4,5,6,7,8,9,10", stake="10"
        )
        self.assertEqual(payload["pocket"], 4)
        self.assertEqual(payload["bet"], "1,2,3,4,5,6,7,8,9,10")
        self.assertTrue(payload["won"])
        self.assertEqual(payload["payout_multiplier"], "3.60")
        self.assertEqual(payload["payout_rub"], "34.70")
        self.assertEqual(payload["commission_rub"], "1.30")
        self.assertEqual(credit.await_args.kwargs["payout_rub"], Decimal("34.70"))
        game_data = json.loads(conn.inserted[-1])
        self.assertEqual(game_data["roulette"]["cover"], 10)
        self.assertEqual(game_data["roulette"]["pockets"], list(range(1, 11)))

    async def test_ten_number_cover_reserves_three_point_six_not_thirty_six(self):
        game_id = _game_id_for_pocket("reserve-cover10", 36)
        conn, payload, _ = await self._play(
            game_id=game_id, bet="1,2,3,4,5,6,7,8,9,10", stake="100"
        )
        self.assertFalse(payload["won"])
        # 100 × 3.6 = 360 gross, 260 winnings, 5% → 13, hold 347.
        self.assertEqual(conn.reserved, Decimal("347.00"))

    async def test_zero_bet_reserves_the_full_thirty_six_times_payout(self):
        game_id = _game_id_for_color("reserve-zero", "black")
        conn, payload, _ = await self._play(game_id=game_id, bet="zero", stake="100")
        self.assertFalse(payload["won"])
        # 100 × 36 = 3600 gross, 3500 winnings, 5% commission 175 → 3425 must be held.
        self.assertEqual(conn.reserved, Decimal("3425.00"))

    async def test_even_money_bet_reserves_only_double(self):
        game_id = _game_id_for_color("reserve-red", "black")
        conn, _payload, _ = await self._play(game_id=game_id, bet="red", stake="100")
        self.assertEqual(conn.reserved, Decimal("195.00"))

    async def test_round_records_rng_audit_and_wheel_seat(self):
        game_id = _game_id_for_color("audit", "red")
        conn, payload, _ = await self._play(game_id=game_id, bet="red", stake="100")
        self.assertEqual(payload["rng"]["algorithm"], ROULETTE_ALGORITHM)
        self.assertEqual(payload["rng"]["modulus"], POCKET_COUNT)
        self.assertEqual(payload["rng"]["seed"], SEED)
        self.assertEqual(payload["rng"]["client_seed"], CLIENT_SEED)
        self.assertEqual(payload["rng"]["nonce"], NONCE)
        self.assertEqual(
            payload["rng"]["message"],
            pocket_message(client_seed=CLIENT_SEED, nonce=NONCE, game_id=game_id),
        )
        self.assertEqual(payload["wheel_index"], wheel_position(payload["pocket"]))
        game_data = json.loads(conn.inserted[-1])
        self.assertEqual(game_data["roulette"]["pocket"], payload["pocket"])
        self.assertEqual(
            game_data["house_policy_snapshot"]["payout_source"], "european_roulette_rules"
        )
        verified = verify_roulette_round(
            server_seed=SEED,
            client_seed=CLIENT_SEED,
            nonce=NONCE,
            game_id=game_id,
            commit=payload["rng"]["commit"],
            expected_pocket=payload["pocket"],
        )
        self.assertTrue(verified["pocket_matches"])

    async def test_house_ledger_moves_by_the_settlement_delta(self):
        game_id = _game_id_for_color("ledger", "black")
        conn, _payload, _ = await self._play(game_id=game_id, bet="red", stake="100")
        self.assertIn("roulette-settlement-", conn.ledger[2])
        self.assertEqual(conn.ledger[3], Decimal("100.00"))

    async def test_disabled_roulette_refuses_to_spin(self):
        conn = RoulettePlayConn()
        with patch("casino_roulette.lock_casino_users", new=AsyncMock()), patch(
            "casino_roulette.lock_casino_game", new=AsyncMock()
        ), patch(
            "casino_roulette.load_casino_settings",
            new=AsyncMock(return_value=_settings(enabled=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await play_roulette_with_conn(
                    conn, telegram_id=11, stake_rub=Decimal("100"), bet="red"
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(conn.inserted)

    async def test_unknown_bet_never_reaches_the_ledger(self):
        conn = RoulettePlayConn()
        with self.assertRaises(HTTPException) as raised:
            await play_roulette_with_conn(
                conn, telegram_id=11, stake_rub=Decimal("100"), bet="dozen"
            )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIsNone(conn.inserted)
        conn.execute.assert_not_awaited()

    async def test_stake_outside_robot_limits_is_refused(self):
        conn = RoulettePlayConn()
        settings = _settings()
        patches = _play_patches(conn, GAME_ID, settings, credit=AsyncMock())
        for entered in patches:
            entered.start()
        try:
            with self.assertRaises(HTTPException) as raised:
                await play_roulette_with_conn(
                    conn, telegram_id=11, stake_rub=Decimal("9"), bet="red"
                )
        finally:
            for entered in reversed(patches):
                entered.stop()
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(conn.inserted)

    async def test_thin_bankroll_refuses_a_zero_bet(self):
        conn = RoulettePlayConn(balance=Decimal("1000"))
        settings = _settings()
        patches = _play_patches(conn, GAME_ID, settings, credit=AsyncMock())
        for entered in patches:
            entered.start()
        try:
            with self.assertRaises(HTTPException) as raised:
                await play_roulette_with_conn(
                    conn, telegram_id=11, stake_rub=Decimal("100"), bet="zero"
                )
        finally:
            for entered in reversed(patches):
                entered.stop()
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(conn.inserted)


class RouletteHouseSeatTests(unittest.IsolatedAsyncioTestCase):
    def _seat_patches(self, limits):
        return (
            patch("casino_roulette.load_casino_settings", new=AsyncMock(return_value=_settings())),
            patch("casino_roulette.commission_rate_for_player", new=AsyncMock(return_value=Decimal("5"))),
            patch(
                "casino_roulette.commission_profile_for_player",
                new=AsyncMock(return_value=("wagering_complete", Decimal("5"))),
            ),
            patch.object(internal_casino, "_assert_stake_within_limits", limits),
        )

    async def test_already_held_table_seat_skips_live_stake_window(self):
        conn = RoulettePlayConn(balance=Decimal("38634.65"))
        conn.profile["reserved_rub"] = Decimal("36685.00")
        limits = MagicMock(
            side_effect=HTTPException(status_code=409, detail="Ставка вне лимита (10.00–277.58 ₽)")
        )
        patches = self._seat_patches(limits)
        for entered in patches:
            entered.start()
        try:
            seat = await load_roulette_house_seat(
                conn,
                telegram_id=11,
                stake_rub=Decimal("300"),
                bet="11",
                extra_available_rub=Decimal("10275"),
                require_stake_window=False,
            )
        finally:
            for entered in reversed(patches):
                entered.stop()
        limits.assert_not_called()
        self.assertEqual(seat.stake, Decimal("300.00"))

    async def test_already_held_seat_skips_live_bankroll_recheck(self):
        conn = RoulettePlayConn(balance=Decimal("100"))
        conn.profile["reserved_rub"] = Decimal("100")
        limits = MagicMock()
        patches = self._seat_patches(limits)
        for entered in patches:
            entered.start()
        try:
            seat = await load_roulette_house_seat(
                conn,
                telegram_id=11,
                stake_rub=Decimal("300"),
                bet="11",
                extra_available_rub=Decimal("1"),
                require_stake_window=False,
            )
        finally:
            for entered in reversed(patches):
                entered.stop()
        self.assertEqual(seat.stake, Decimal("300.00"))

    async def test_fresh_seat_still_enforces_the_stake_window(self):
        conn = RoulettePlayConn(balance=Decimal("38634.65"))
        conn.profile["reserved_rub"] = Decimal("36685.00")
        limits = MagicMock(
            side_effect=HTTPException(status_code=409, detail="Ставка вне лимита (10.00–277.58 ₽)")
        )
        patches = self._seat_patches(limits)
        for entered in patches:
            entered.start()
        try:
            with self.assertRaises(HTTPException) as raised:
                await load_roulette_house_seat(
                    conn,
                    telegram_id=11,
                    stake_rub=Decimal("300"),
                    bet="11",
                    extra_available_rub=Decimal("10275"),
                )
        finally:
            for entered in reversed(patches):
                entered.stop()
        self.assertEqual(raised.exception.status_code, 409)
        limits.assert_called_once()


if __name__ == "__main__":
    unittest.main()
