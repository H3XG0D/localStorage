from decimal import Decimal
import unittest

from casino_finance import KNOWN_GAME_TYPES
from casino_settings_registry import (
    REGISTRY,
    UnknownSettingKey,
    SettingValueError,
    canonical_defaults,
    clamp_commission_rub,
    default_numeric,
    effective_max_stake,
    is_known_key,
    to_storage,
    validate_value,
)


# Снимок старого DEFAULT_SETTINGS из routers/admin_casino.py до задачи 1.
LEGACY_DEFAULT_SETTINGS = {
    "commission_rate": 15.0,
    "commission_rate_wagering_active": 15.0,
    "commission_rate_wagering_complete": 5.0,
    "wagering_percent": 21.0,
    "creator_cut_percent": 5.0,
    "referral_l1_percent": 2.0,
    "referral_l2_percent": 2.0,
    "creator_cut_percent_wagering_active": 3.0,
    "referral_l1_percent_wagering_active": 2.0,
    "referral_l2_percent_wagering_active": 2.0,
    "creator_cut_percent_wagering_complete": 1.0,
    "referral_l1_percent_wagering_complete": 0.5,
    "referral_l2_percent_wagering_complete": 0.5,
    "min_bet_rub": 10.0,
    "max_bet_rub": 100000.0,
    "min_withdrawal_rub": 100.0,
}


class CasinoSettingsRegistryTests(unittest.TestCase):
    def test_legacy_default_keys_keep_the_same_values(self):
        for key, expected in LEGACY_DEFAULT_SETTINGS.items():
            with self.subTest(key=key):
                self.assertTrue(is_known_key(key))
                self.assertEqual(float(REGISTRY[key].default), expected)
                self.assertEqual(float(default_numeric(key)), expected)

    def test_game_keys_match_finance_known_types(self):
        enabled = REGISTRY["enabled_games"].default
        self.assertIsInstance(enabled, dict)
        self.assertEqual(set(enabled), set(KNOWN_GAME_TYPES))
        self.assertTrue(all(enabled[game] is True for game in KNOWN_GAME_TYPES))

    def test_retired_sport_keys_are_rejected(self):
        from casino_finance import RETIRED_SPORT_GAME_TYPES
        from casino_settings_registry import GAME_KEYS

        self.assertEqual(
            RETIRED_SPORT_GAME_TYPES,
            {"pvp_darts", "pvp_bowling", "pvp_football", "pvp_basketball"},
        )
        self.assertFalse(RETIRED_SPORT_GAME_TYPES & set(GAME_KEYS))
        with self.assertRaises(SettingValueError) as raised:
            validate_value("enabled_games", {"pvp_dice": True, "pvp_darts": True})
        self.assertIn("pvp_darts", str(raised.exception))

    def test_canonical_defaults_keep_storage_wrappers(self):
        stored = canonical_defaults()
        self.assertEqual(stored["commission_rate"], {"percent": 15.0})
        self.assertEqual(stored["min_bet_rub"], {"amount": 10.0})
        self.assertEqual(stored["enabled_games"]["pvp_dice"], True)

    def test_unknown_key_is_rejected(self):
        self.assertFalse(is_known_key("not_a_real_setting"))
        with self.assertRaises(UnknownSettingKey):
            validate_value("not_a_real_setting", {"percent": 1})

    def test_values_outside_min_max_are_rejected(self):
        with self.assertRaises(SettingValueError):
            validate_value("commission_rate", {"percent": 101})
        with self.assertRaises(SettingValueError):
            validate_value("commission_rate", -1)
        with self.assertRaises(SettingValueError):
            validate_value("min_bet_rub", {"amount": 0})
        validate_value("commission_rate", {"percent": 0})
        validate_value("commission_rate", {"percent": 100})
        validate_value("min_bet_rub", {"amount": Decimal("0.01")})

    def test_wagering_help_describes_house_take_not_stake_turnover(self):
        help_ru = REGISTRY["wagering_percent"].help_ru
        self.assertIn("комиссией", help_ru)
        self.assertIn("1400", help_ru)
        self.assertNotIn("прокрутить ставками", help_ru)

    def test_grid_defaults_are_accepted(self):
        stored = canonical_defaults()
        validate_value("cashback_volume_tiers", stored["cashback_volume_tiers"])
        validate_value("commission_volume_tiers", stored["commission_volume_tiers"])
        validate_value("level_reach_bonuses", stored["level_reach_bonuses"])
        validate_value("enabled_games", stored["enabled_games"])
        self.assertEqual(
            stored["level_reach_bonuses"],
            [
                {"min_wager_rub": 50000.0, "bonus_rub": 500.0},
                {"min_wager_rub": 100000.0, "bonus_rub": 1000.0},
                {"min_wager_rub": 200000.0, "bonus_rub": 2500.0},
                {"min_wager_rub": 500000.0, "bonus_rub": 5000.0},
            ],
        )


class BankrollSettingsTests(unittest.TestCase):
    def test_defaults_do_not_change_live_limits(self):
        self.assertEqual(float(REGISTRY["max_profit_pct_per_round"].default), 1.0)
        self.assertEqual(float(REGISTRY["max_profit_pct_per_round_all"].default), 1.5)
        self.assertEqual(float(REGISTRY["bankroll_floor_rub"].default), 0.0)
        self.assertEqual(float(REGISTRY["liability_amount_rub"].default), 0.0)
        stored = canonical_defaults()
        self.assertEqual(stored["bankroll_floor_rub"], {"amount": 0.0})
        self.assertEqual(stored["liability_amount_rub"], {"amount": 0.0})
        self.assertEqual(stored["max_profit_pct_per_round"], {"percent": 1.0})

    def test_zero_liability_and_bankroll_keep_global_max_bet(self):
        self.assertEqual(
            effective_max_stake(
                max_bet_rub=100000,
                liability_amount_rub=0,
                max_profit_pct_per_round=1.0,
                bankroll_rub=0,
                payout_multiplier=2,
            ),
            Decimal("100000.00"),
        )

    def test_liability_and_profit_pct_shrink_max_stake(self):
        self.assertEqual(
            effective_max_stake(
                max_bet_rub=100000,
                liability_amount_rub=200,
                max_profit_pct_per_round=1.0,
                bankroll_rub=0,
                payout_multiplier=2,
            ),
            Decimal("100.00"),
        )
        self.assertEqual(
            effective_max_stake(
                max_bet_rub=100000,
                liability_amount_rub=0,
                max_profit_pct_per_round=1.0,
                bankroll_rub=10000,
                payout_multiplier=2,
            ),
            Decimal("100.00"),
        )


class AppliedStakeBoundsTests(unittest.TestCase):
    def test_per_game_max_and_profit_pct_shrink_allowed_stake(self):
        from casino_finance import canonical_casino_settings, game_stake_bounds

        settings = canonical_casino_settings(
            [
                {"key": "min_bet_rub", "value": {"amount": 10}},
                {"key": "max_bet_rub", "value": {"amount": 100000}},
                {"key": "per_game_limits", "value": {"pvp_dice": {"min": 20, "max": 80}}},
            ]
        )
        lo, hi = game_stake_bounds(settings, "pvp_dice")
        self.assertEqual(lo, Decimal("20.00"))
        self.assertEqual(hi, Decimal("80.00"))
        cub = canonical_casino_settings(
            [
                {"key": "min_bet_rub", "value": {"amount": 10}},
                {"key": "max_bet_rub", "value": {"amount": 100000}},
                {"key": "max_profit_pct_per_round", "value": {"percent": 1.0}},
            ]
        )
        _, cub_hi = game_stake_bounds(
            cub, "cub", payout_multiplier=2, bankroll_rub=10000
        )
        self.assertEqual(cub_hi, Decimal("100.00"))


class LimitsSettingsTests(unittest.TestCase):
    def test_defaults_and_ranges(self):
        self.assertEqual(REGISTRY["per_game_limits"].default, {})
        self.assertEqual(float(REGISTRY["bet_step_rub"].default), 10.0)
        self.assertEqual(int(REGISTRY["max_concurrent_games_per_player"].default), 10)
        self.assertEqual(REGISTRY["max_rounds_per_player_per_day"].default, {})
        self.assertEqual(int(REGISTRY["pending_invite_ttl_minutes"].default), 10)
        self.assertEqual(int(REGISTRY["move_timeout_minutes"].default), 120)
        validate_value("pending_invite_ttl_minutes", {"value": 1})
        validate_value("pending_invite_ttl_minutes", {"value": 60})
        with self.assertRaises(SettingValueError):
            validate_value("pending_invite_ttl_minutes", {"value": 0})
        with self.assertRaises(SettingValueError):
            validate_value("pending_invite_ttl_minutes", {"value": 61})
        with self.assertRaises(SettingValueError):
            validate_value("max_concurrent_games_per_player", {"value": 0})

    def test_holdem_cash_table_keys(self):
        self.assertEqual(float(REGISTRY["holdem_small_blind_rub"].default), 10.0)
        self.assertEqual(float(REGISTRY["holdem_big_blind_rub"].default), 20.0)
        self.assertEqual(float(REGISTRY["holdem_rake_percent"].default), 5.0)
        self.assertEqual(float(REGISTRY["holdem_rake_cap_rub"].default), 50.0)
        self.assertEqual(int(REGISTRY["holdem_action_timeout_seconds"].default), 30)
        self.assertEqual(int(REGISTRY["holdem_min_buyin_bb"].default), 20)
        self.assertEqual(int(REGISTRY["holdem_max_buyin_bb"].default), 100)
        validate_value("holdem_action_timeout_seconds", {"value": 5})
        validate_value("holdem_action_timeout_seconds", {"value": 300})
        with self.assertRaises(SettingValueError):
            validate_value("holdem_action_timeout_seconds", {"value": 4})
        validate_value("per_game_limits", {"holdem": {"min": 400, "max": 2000}})
        self.assertIn("holdem", REGISTRY["enabled_games"].default)
        self.assertIn("jackpot", REGISTRY["enabled_games"].default)
        self.assertIn("fixed_room", REGISTRY["enabled_games"].default)
        self.assertIn("clan_war", REGISTRY["enabled_games"].default)
        self.assertEqual(float(REGISTRY["fixed_room_rake_percent"].default), 5.0)
        self.assertEqual(int(REGISTRY["fixed_room_max_seats"].default), 10)
        self.assertEqual(int(REGISTRY["fixed_room_collect_seconds"].default), 600)
        self.assertEqual(float(REGISTRY["clan_war_rake_percent"].default), 5.0)
        self.assertEqual(int(REGISTRY["clan_war_max_fighters"].default), 5)
        self.assertEqual(int(REGISTRY["clan_war_collect_seconds"].default), 1800)
        self.assertEqual(int(REGISTRY["jackpot_collect_seconds"].default), 300)
        self.assertEqual(int(REGISTRY["jackpot_max_players"].default), 30)
        self.assertEqual(float(REGISTRY["jackpot_rake_percent"].default), 5.0)
        self.assertEqual(int(REGISTRY["roulette_table_collect_seconds"].default), 25)
        self.assertEqual(int(REGISTRY["roulette_table_max_players"].default), 24)
        self.assertIs(REGISTRY["clans_enabled"].default, True)
        self.assertEqual(int(REGISTRY["clan_max_members"].default), 20)
        validate_value("clan_max_members", {"value": 2})
        validate_value("clan_max_members", {"value": 50})
        with self.assertRaises(SettingValueError):
            validate_value("clan_max_members", {"value": 1})
        validate_value("jackpot_collect_seconds", {"value": 30})
        validate_value("jackpot_collect_seconds", {"value": 3600})
        with self.assertRaises(SettingValueError):
            validate_value("jackpot_collect_seconds", {"value": 29})
        validate_value("roulette_table_collect_seconds", {"value": 5})
        validate_value("roulette_table_collect_seconds", {"value": 120})
        with self.assertRaises(SettingValueError):
            validate_value("roulette_table_collect_seconds", {"value": 4})
        validate_value("roulette_table_max_players", {"value": 2})
        validate_value("roulette_table_max_players", {"value": 48})
        with self.assertRaises(SettingValueError):
            validate_value("roulette_table_max_players", {"value": 1})

    def test_unknown_game_in_per_game_limits_is_rejected(self):
        with self.assertRaises(SettingValueError):
            validate_value("per_game_limits", {"keno": {"min": 10, "max": 100}})
        with self.assertRaises(SettingValueError):
            validate_value("max_rounds_per_player_per_day", {"keno": 3})
        validate_value("per_game_limits", {"pvp_dice": {"min": 10, "max": 50000}})
        validate_value("max_rounds_per_player_per_day", {"cub": 0})
        self.assertEqual(to_storage("per_game_limits", {}), {})
        self.assertEqual(to_storage("max_rounds_per_player_per_day", {}), {})


class CommissionCapSettingsTests(unittest.TestCase):
    def test_zero_cap_and_min_keep_current_commission(self):
        self.assertEqual(float(REGISTRY["commission_cap_rub"].default), 0.0)
        self.assertEqual(float(REGISTRY["commission_min_rub"].default), 0.0)
        self.assertEqual(canonical_defaults()["commission_cap_rub"], {"amount": 0.0})
        self.assertEqual(
            clamp_commission_rub(15, cap_rub=0, min_rub=0),
            Decimal("15.00"),
        )
        self.assertEqual(
            clamp_commission_rub(Decimal("50"), cap_rub=10, min_rub=0),
            Decimal("10.00"),
        )
        self.assertEqual(
            clamp_commission_rub(Decimal("5"), cap_rub=0, min_rub=10),
            Decimal("10.00"),
        )


class ResponsibleSettingsTests(unittest.TestCase):
    def test_tools_are_off_by_default(self):
        for key in (
            "deposit_limit_enabled",
            "loss_limit_enabled",
            "wager_limit_enabled",
            "session_limit_enabled",
        ):
            with self.subTest(key=key):
                self.assertIs(REGISTRY[key].default, False)
                self.assertEqual(canonical_defaults()[key], {"enabled": False})
        self.assertEqual(int(REGISTRY["reality_check_default_minutes"].default), 60)
        self.assertEqual(int(REGISTRY["self_exclusion_min_hours"].default), 24)
        self.assertEqual(int(REGISTRY["timeout_max_hours"].default), 72)
        self.assertEqual(int(REGISTRY["limit_loosening_delay_hours"].default), 24)
        validate_value("reality_check_default_minutes", {"value": 0})
        with self.assertRaises(SettingValueError):
            validate_value("self_exclusion_min_hours", {"value": 0})


class PayoutSettingsTests(unittest.TestCase):
    def test_withdrawal_thresholds_default_to_manual(self):
        for key in (
            "withdrawal_auto_approve_max_rub",
            "withdrawal_manual_review_min_rub",
            "withdrawal_daily_limit_rub",
            "withdrawal_hourly_limit_rub",
        ):
            with self.subTest(key=key):
                self.assertEqual(float(REGISTRY[key].default), 0.0)
                self.assertEqual(canonical_defaults()[key], {"amount": 0.0})
                validate_value(key, {"amount": 0})


class FairnessSettingsTests(unittest.TestCase):
    def test_provably_fair_defaults_off(self):
        enabled = REGISTRY["provably_fair_enabled"].default
        self.assertEqual(set(enabled), set(KNOWN_GAME_TYPES))
        self.assertTrue(all(flag is False for flag in enabled.values()))
        self.assertIs(REGISTRY["seed_rotation_allowed"].default, True)
        self.assertEqual(canonical_defaults()["seed_rotation_allowed"], {"enabled": True})
        with self.assertRaises(SettingValueError):
            validate_value("provably_fair_enabled", {"keno": True})


class CasinoSettingsV2MigrationTests(unittest.TestCase):
    def test_v2_sql_inserts_registry_defaults_without_overwriting(self):
        from pathlib import Path

        sql_path = Path(__file__).resolve().parents[1] / "migrations" / "add_casino_settings_v2.sql"
        sql = sql_path.read_text(encoding="utf-8")
        self.assertIn("ON CONFLICT (key) DO NOTHING", sql)
        self.assertNotIn("DO UPDATE", sql)
        stored = canonical_defaults()
        for key in (
            "commission_cap_rub",
            "commission_min_rub",
            "bankroll_floor_rub",
            "liability_amount_rub",
            "per_game_limits",
            "max_profit_pct_per_round",
            "provably_fair_enabled",
            "seed_rotation_allowed",
        ):
            with self.subTest(key=key):
                self.assertIn(f"'{key}'", sql)
        self.assertIn("'{\"amount\": 0.0}'", sql)
        self.assertIn("'{}'", sql)
        self.assertEqual(stored["commission_cap_rub"], {"amount": 0.0})
        self.assertEqual(stored["bankroll_floor_rub"], {"amount": 0.0})
        self.assertEqual(stored["per_game_limits"], {})


if __name__ == "__main__":
    unittest.main()
