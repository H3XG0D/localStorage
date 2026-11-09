"""Tests for casino house readiness and profile admin helpers."""
from __future__ import annotations

import unittest
from decimal import Decimal

from casino_house_readiness import build_house_readiness, validate_profile_mode_games


class HouseReadinessTests(unittest.TestCase):
    def test_blocked_when_bank_empty_and_wrong_mode(self):
        accounts = [
            {
                "id": 1,
                "account_key": "main",
                "display_name": "Main",
                "balance_rub": Decimal("0.00"),
                "reserved_rub": Decimal("0.00"),
                "is_active": True,
            }
        ]
        profiles = [
            {
                "id": 1,
                "profile_key": "focuscasino-house",
                "display_name": "FocusCasino",
                "mode": "house_robot",
                "account_id": 1,
                "account_active": True,
                "is_active": True,
                "allowed_games": ["cub"],
                "min_bet_rub": Decimal("10.00"),
                "max_bet_rub": Decimal("100000.00"),
                "max_concurrent_games": 1,
                "max_exposure_rub": Decimal("0.00"),
            }
        ]
        payload = build_house_readiness(accounts, profiles, stake_rub=Decimal("100.00"))
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["max_bots_capacity"], 0)
        checks = {item["id"]: item for item in payload["checks"]}
        self.assertFalse(checks["bank_balance"]["ok"])
        self.assertFalse(checks["pvp_profiles_active"]["ok"])
        self.assertFalse(checks["profile_mode"]["ok"])

    def test_ready_with_pvp_profiles_and_balance(self):
        accounts = [
            {
                "id": 1,
                "account_key": "main",
                "display_name": "Main",
                "balance_rub": Decimal("10000.00"),
                "reserved_rub": Decimal("0.00"),
                "is_active": True,
            }
        ]
        profiles = [
            {
                "id": index,
                "profile_key": f"pvp-robot-{index}",
                "display_name": f"Bot {index}",
                "mode": "pvp_robot",
                "account_id": 1,
                "account_active": True,
                "is_active": True,
                "allowed_games": ["pvp_dice"],
                "min_bet_rub": Decimal("10.00"),
                "max_bet_rub": Decimal("1000.00"),
                "max_concurrent_games": 20,
                "max_exposure_rub": Decimal("5000.00"),
            }
            for index in range(1, 4)
        ]
        payload = build_house_readiness(accounts, profiles, stake_rub=Decimal("100.00"))
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["max_bots_capacity"], 3)

    def test_capacity_limited_by_profile_count(self):
        accounts = [
            {
                "id": 1,
                "account_key": "main",
                "display_name": "Main",
                "balance_rub": Decimal("100000.00"),
                "reserved_rub": Decimal("0.00"),
                "is_active": True,
            }
        ]
        profiles = [
            {
                "id": 1,
                "profile_key": "pvp-robot-1",
                "display_name": "Bot 1",
                "mode": "pvp_robot",
                "account_id": 1,
                "account_active": True,
                "is_active": True,
                "allowed_games": ["pvp_dice"],
                "min_bet_rub": Decimal("10.00"),
                "max_bet_rub": Decimal("1000.00"),
                "max_concurrent_games": 20,
                "max_exposure_rub": Decimal("5000.00"),
            }
        ]
        payload = build_house_readiness(accounts, profiles, stake_rub=Decimal("100.00"))
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["max_bots_capacity"], 1)


HEALTHY_SETTINGS = {
    "bankroll_floor_rub": {"amount": 1000.0},
    "min_bet_rub": {"amount": 10.0},
    "max_bet_rub": {"amount": 100000.0},
    "commission_rate_wagering_complete": {"percent": 5.0},
    "enabled_games": {"pvp_dice": True, "raffle": False},
}


def _account(balance: str, reserved: str = "0.00") -> dict:
    return {
        "id": 1,
        "account_key": "main",
        "display_name": "Main",
        "balance_rub": Decimal(balance),
        "reserved_rub": Decimal(reserved),
        "is_active": True,
    }


def _pvp_profile() -> dict:
    return {
        "id": 1,
        "profile_key": "pvp-robot-1",
        "display_name": "Bot 1",
        "mode": "pvp_robot",
        "account_id": 1,
        "account_active": True,
        "is_active": True,
        "allowed_games": ["pvp_dice"],
        "min_bet_rub": Decimal("10.00"),
        "max_bet_rub": Decimal("1000.00"),
        "max_concurrent_games": 20,
        "max_exposure_rub": Decimal("5000.00"),
    }


class RequiredReadinessTests(unittest.TestCase):
    def test_exactly_five_required_and_zero_bank_is_red(self):
        payload = build_house_readiness(
            [_account("0.00")],
            [_pvp_profile()],
            stake_rub=Decimal("100.00"),
            settings=HEALTHY_SETTINGS,
            chat_bound=True,
            chat_title="FocusCasino",
        )
        self.assertEqual(len(payload["required"]), 5)
        self.assertEqual(payload["required_total"], 5)
        ids = [item["id"] for item in payload["required"]]
        self.assertEqual(
            ids,
            [
                "bank_above_floor",
                "commission_and_limits",
                "game_enabled",
                "robot_active",
                "telegram_bound",
            ],
        )
        by_id = {item["id"]: item for item in payload["required"]}
        self.assertFalse(by_id["bank_above_floor"]["ok"])
        self.assertTrue(by_id["commission_and_limits"]["ok"])
        self.assertTrue(by_id["game_enabled"]["ok"])
        self.assertTrue(by_id["robot_active"]["ok"])
        self.assertTrue(by_id["telegram_bound"]["ok"])
        self.assertEqual(payload["required_ok"], 4)
        self.assertFalse(payload["required_ready"])

    def test_bank_must_be_strictly_above_floor(self):
        equal = build_house_readiness(
            [_account("1000.00")],
            [_pvp_profile()],
            settings=HEALTHY_SETTINGS,
            chat_bound=True,
        )
        above = build_house_readiness(
            [_account("1000.01")],
            [_pvp_profile()],
            settings=HEALTHY_SETTINGS,
            chat_bound=True,
        )
        equal_check = next(item for item in equal["required"] if item["id"] == "bank_above_floor")
        above_check = next(item for item in above["required"] if item["id"] == "bank_above_floor")
        self.assertFalse(equal_check["ok"])
        self.assertTrue(above_check["ok"])
        self.assertTrue(above["required_ready"])

    def test_all_games_off_and_missing_chat_fail(self):
        settings = {
            **HEALTHY_SETTINGS,
            "enabled_games": {"pvp_dice": False, "cub": False},
        }
        payload = build_house_readiness(
            [_account("5000.00")],
            [_pvp_profile()],
            settings=settings,
            chat_bound=False,
        )
        by_id = {item["id"]: item for item in payload["required"]}
        self.assertFalse(by_id["game_enabled"]["ok"])
        self.assertFalse(by_id["telegram_bound"]["ok"])
        self.assertFalse(payload["required_ready"])
        self.assertIn("/x8/casino/settings#section-games", by_id["game_enabled"]["href"])
        self.assertIn("/x8/casino/settings#section-chat", by_id["telegram_bound"]["href"])

    def test_zero_min_bet_fails_limits(self):
        settings = {**HEALTHY_SETTINGS, "min_bet_rub": {"amount": 0.0}}
        payload = build_house_readiness(
            [_account("5000.00")],
            [_pvp_profile()],
            settings=settings,
            chat_bound=True,
        )
        limits = next(item for item in payload["required"] if item["id"] == "commission_and_limits")
        self.assertFalse(limits["ok"])


class ProfileModeValidationTests(unittest.TestCase):
    def test_pvp_robot_requires_pvp_game(self):
        with self.assertRaises(ValueError):
            validate_profile_mode_games("pvp_robot", ["cub"])

    def test_house_robot_requires_cub(self):
        with self.assertRaises(ValueError):
            validate_profile_mode_games("house_robot", ["pvp_dice"])
