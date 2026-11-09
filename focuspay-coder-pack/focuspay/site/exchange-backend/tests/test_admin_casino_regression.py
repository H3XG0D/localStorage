"""Focused regressions for the public admin casino endpoints."""
from __future__ import annotations

import json
import sys
import types
import unittest
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("dependency override required")


_auth_module = sys.modules.get("auth")
_db_module = sys.modules.get("db")
if _auth_module is None:
    sys.modules["auth"] = types.SimpleNamespace(
        get_current_admin=_dependency_stub,
        get_current_finance_owner=_dependency_stub,
        get_current_user=_dependency_stub,
    )
if _db_module is None:
    sys.modules["db"] = types.SimpleNamespace(get_pool=_dependency_stub)

try:
    from routers import admin_casino
finally:
    if _auth_module is None:
        del sys.modules["auth"]
    if _db_module is None:
        del sys.modules["db"]


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AsyncContext(self.conn)


class _SettingsConn:
    def __init__(self, settings: dict | None = None):
        self.settings = settings or {
            "commission_rate": {"percent": 15.0},
            "creator_cut_percent": {"percent": 5.0},
            "referral_l1_percent": {"percent": 2.0},
            "referral_l2_percent": {"percent": 2.0},
            "min_bet_rub": {"amount": 10.0},
            "max_bet_rub": {"amount": 100000.0},
            "min_withdrawal_rub": {"amount": 100.0},
            "enabled_games": {"pvp_dice": False},
            "creator_telegram_id": {"telegram_id": 123},
        }
        self.transaction_entries = 0
        self.execute_calls: list[tuple[str, tuple]] = []
        self.audit_rows: list[dict] = []
        self.fetch_queries: list[str] = []

    def transaction(self):
        conn = self

        class _Transaction:
            async def __aenter__(self):
                conn.transaction_entries += 1

            async def __aexit__(self, *args):
                return False

        return _Transaction()

    async def fetchval(self, query, *args):
        if "COUNT(*) FROM casino_settings_audit" in query:
            return len(self.audit_rows)
        raise AssertionError(query)

    async def fetch(self, query, *args):
        self.fetch_queries.append(query)
        if "FROM casino_settings_audit" in query:
            return self.audit_rows
        if "FROM casino_settings" not in query:
            raise AssertionError(query)
        return [{"key": key, "value": value} for key, value in self.settings.items()]

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        if "casino_settings_audit" in query:
            batch_id, key, old_raw, new_raw, changed_by, reason = args
            self.audit_rows.append(
                {
                    "id": len(self.audit_rows) + 1,
                    "batch_id": batch_id,
                    "key": key,
                    "old_value": None if old_raw is None else json.loads(old_raw),
                    "new_value": json.loads(new_raw),
                    "changed_by": changed_by,
                    "changed_at": datetime.now(timezone.utc),
                    "reason": reason,
                }
            )
            return "OK"
        if "INSERT INTO casino_settings" in query:
            key, raw_value, _updated_by = args
            self.settings[key] = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
        return "OK"


def _setting_inserts(conn: _SettingsConn):
    return [
        (query, args)
        for query, args in conn.execute_calls
        if "INSERT INTO casino_settings" in query and "casino_settings_audit" not in query
    ]


class _BindingConn:
    def __init__(self):
        self.execute_calls: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.transaction_entries = 0
        self.row = {
            "id": 3,
            "chat_id": -100123,
            "chat_type": "supergroup",
            "chat_title": "Games",
            "status": "active",
            "requested_by_telegram_id": 7,
            "created_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
            "confirmed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
            "disabled_at": None,
        }

    def transaction(self):
        conn = self

        class _Transaction:
            async def __aenter__(self):
                conn.transaction_entries += 1

            async def __aexit__(self, *args):
                return False

        return _Transaction()

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "OK"

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        if "FOR UPDATE" in query:
            return {"id": 3}
        return self.row


class CasinoGameChatBindingAdminTests(unittest.IsolatedAsyncioTestCase):
    def test_action_rejects_extra_fields(self):
        with self.assertRaises(ValidationError):
            admin_casino.GameChatBindingAction.model_validate({"binding_id": 3, "secret": "no"})

    async def test_confirm_replaces_active_binding_under_transaction(self):
        conn = _BindingConn()
        with patch.object(admin_casino, "get_pool", _dependency_stub):
            # Direct endpoint invocation needs the pool patched to a concrete fake.
            async def pool():
                return _Pool(conn)

            with patch.object(admin_casino, "get_pool", pool):
                result = await admin_casino.confirm_game_chat_binding(
                    admin_casino.GameChatBindingAction(binding_id=3),
                    admin={"id": 9, "username": "admin"},
                )

        self.assertEqual(result["chat_id"], -100123)
        self.assertEqual(result["status"], "active")
        self.assertEqual(conn.transaction_entries, 1)
        self.assertIn("pg_advisory_xact_lock", conn.execute_calls[0][0])
        self.assertIn("status = 'disabled'", conn.execute_calls[1][0])
        self.assertIn("status = 'active'", conn.fetchrow_calls[-1][0])


    async def test_disable_uses_the_binding_advisory_lock(self):
        conn = _BindingConn()

        async def pool():
            return _Pool(conn)

        with patch.object(admin_casino, "get_pool", pool):
            result = await admin_casino.disable_game_chat_binding(
                admin_casino.GameChatBindingAction(binding_id=3),
                admin={"id": 9, "username": "admin"},
            )

        self.assertEqual(result["status"], "active")
        self.assertEqual(conn.transaction_entries, 1)
        self.assertIn("pg_advisory_xact_lock(741921)", conn.execute_calls[0][0])
        self.assertIn("status = 'disabled'", conn.fetchrow_calls[-1][0])

    def test_rejects_extra_fields(self):
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate.model_validate({"commission_rate": 15, "secret": 1})

    def test_percentages_are_whole_percent_values(self):
        self.assertEqual(
            admin_casino.CasinoSettingsUpdate(commission_rate=15).commission_rate,
            15,
        )
        for value in (-0.01, 100.01):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                admin_casino.CasinoSettingsUpdate(commission_rate=value)

    def test_creator_and_referral_shares_cannot_exceed_supplied_commission_rate(self):
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(
                commission_rate=15,
                creator_cut_percent=12,
                referral_l1_percent=2,
                referral_l2_percent=2,
            )

        for field in ("min_bet_rub", "max_bet_rub", "min_withdrawal_rub"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                admin_casino.CasinoSettingsUpdate.model_validate({field: 0})

    def test_enabled_games_accepts_only_known_keys(self):
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(enabled_games={"keno": True})
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(provably_fair_enabled={"keno": True})
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(per_game_limits={"keno": {"min": 10, "max": 20}})
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(pending_invite_ttl_minutes=61)
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(holdem_action_timeout_seconds=4)
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(holdem_small_blind_rub=0)
        self.assertEqual(
            admin_casino.CasinoSettingsUpdate(enabled_games={"holdem": True}).enabled_games,
            {"holdem": True},
        )
        with self.assertRaises(ValidationError):
            admin_casino.HouseProfileCreate(
                profile_key="bot1",
                display_name="Bot",
                allowed_games=["holdem"],
            )
        with self.assertRaises(ValidationError):
            admin_casino.HouseProfileCreate(
                profile_key="bot1",
                display_name="Bot",
                allowed_games=["jackpot"],
            )
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(jackpot_collect_seconds=29)
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate(roulette_table_collect_seconds=4)
        self.assertEqual(
            admin_casino.CasinoSettingsUpdate(commission_cap_rub=0).commission_cap_rub,
            0,
        )

    def test_legacy_creator_telegram_id_is_not_a_settings_field(self):
        with self.assertRaises(ValidationError):
            admin_casino.CasinoSettingsUpdate.model_validate({"creator_telegram_id": 123})

    def test_explicit_null_is_rejected_for_all_settings(self):
        for field in (
            "commission_rate",
            "creator_cut_percent",
            "referral_l1_percent",
            "referral_l2_percent",
            "min_bet_rub",
            "max_bet_rub",
            "min_withdrawal_rub",
            "enabled_games",
            "commission_cap_rub",
            "bankroll_floor_rub",
            "per_game_limits",
            "provably_fair_enabled",
            "deposit_limit_enabled",
            "reason",
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                admin_casino.CasinoSettingsUpdate.model_validate({field: None})

    def test_withdrawal_actions_reject_extra_fields(self):
        with self.assertRaises(ValidationError):
            admin_casino.WithdrawalApproval.model_validate(
                {"tx_hash": "hash", "status": "approved"}
            )
        with self.assertRaises(ValidationError):
            admin_casino.WithdrawalRejection.model_validate(
                {"reason": "no", "refund": False}
            )


class CasinoSettingsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_unknown_registry_key_returns_http_400(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        class _Payload:
            def model_dump(self, exclude_unset=True):
                return {"not_a_real_setting": 1, "reason": "x"}

        with patch("routers.admin_casino.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await admin_casino.update_casino_settings(
                    _Payload(),
                    admin={"id": 7, "username": "owner"},
                )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(conn.execute_calls, [])

    async def test_get_returns_a_full_safe_game_map(self):
        conn = _SettingsConn(
            {
                "enabled_games": {
                    "pvp_dice": False,
                    "raffle": True,
                    "unknown_game": True,
                }
            }
        )

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.get_casino_settings(admin={"id": 7, "username": "owner"})

        self.assertEqual(set(response.enabled_games), set(admin_casino.KNOWN_GAME_KEYS))
        self.assertFalse(response.enabled_games["pvp_dice"])
        self.assertTrue(response.enabled_games["blackjack"])
        self.assertNotIn("unknown_game", response.enabled_games)

    async def test_patch_merges_games_in_one_transaction(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        update = admin_casino.CasinoSettingsUpdate(
            enabled_games={"raffle": False},
            reason="audit test",
        )
        with patch("routers.admin_casino.get_pool", new=get_pool), patch.object(
            admin_casino.logger, "info"
        ) as log_info:
            response = await admin_casino.update_casino_settings(
                update,
                admin={"id": 7, "username": "owner"},
            )

        self.assertEqual(conn.transaction_entries, 1)
        self.assertFalse(response.enabled_games["pvp_dice"])
        self.assertFalse(response.enabled_games["raffle"])
        self.assertTrue(response.enabled_games["blackjack"])
        self.assertTrue(all(call[1][2] == "owner" for call in _setting_inserts(conn)))
        self.assertNotIn("enabled_games", repr(log_info.call_args))

    async def test_patch_validates_shares_and_limits_against_stored_values(self):
        for update in (
            admin_casino.CasinoSettingsUpdate(creator_cut_percent=16, reason="audit test"),
            admin_casino.CasinoSettingsUpdate(max_bet_rub=5, reason="audit test"),
        ):
            with self.subTest(update=update):
                conn = _SettingsConn()

                async def get_pool():
                    return _Pool(conn)

                with patch("routers.admin_casino.get_pool", new=get_pool):
                    with self.assertRaises(HTTPException) as raised:
                        await admin_casino.update_casino_settings(
                            update,
                            admin={"id": 7, "username": "owner"},
                        )
                self.assertEqual(raised.exception.status_code, 422)
                self.assertEqual(conn.execute_calls, [])

    async def test_patch_recovers_invalid_stored_settings_to_safe_defaults(self):
        conn = _SettingsConn(
            {
                "commission_rate": {"percent": 200},
                "creator_cut_percent": {"percent": -1},
                "referral_l1_percent": {"percent": 2},
                "referral_l2_percent": {"percent": 2},
                "min_bet_rub": {"amount": 0},
                "max_bet_rub": {"amount": -5},
                "min_withdrawal_rub": {"amount": 0},
                "creator_telegram_id": {"telegram_id": "invalid"},
            }
        )

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.update_casino_settings(
                admin_casino.CasinoSettingsUpdate(commission_rate_wagering_active=20, reason="audit test"),
                admin={"id": 7, "username": "owner"},
            )

        self.assertEqual(response.commission_rate, 20)
        self.assertEqual(response.commission_rate_wagering_active, 20)
        self.assertEqual(response.creator_cut_percent, 3)
        self.assertEqual(response.min_bet_rub, 10)
        self.assertEqual(response.max_bet_rub, 100000)
        self.assertEqual(response.min_withdrawal_rub, 100)
        self.assertNotIn("creator_telegram_id", response.model_fields_set)

    async def test_get_derives_owner_share_and_ruble_preview(self):
        # commission 15 = creator 5 + L1 2 + L2 2 → владельцу остаётся 6%.
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.get_casino_settings(admin={"id": 7, "username": "owner"})

        self.assertEqual(response.owner_share_percent, 8.0)
        preview = response.commission_preview
        self.assertEqual(preview.stake_rub, 100.0)
        self.assertEqual(preview.commission_rub, 15.0)
        self.assertEqual(preview.creator_rub, 3.0)
        self.assertEqual(preview.referral_l1_rub, 2.0)
        self.assertEqual(preview.referral_l2_rub, 2.0)
        self.assertEqual(preview.owner_rub, 8.0)
        active_preview = response.commission_preview_wagering_active
        self.assertEqual(active_preview.owner_rub, 8.0)
        complete_preview = response.commission_preview_wagering_complete
        self.assertEqual(complete_preview.commission_rub, 5.0)
        self.assertEqual(complete_preview.owner_rub, 3.0)

    async def test_owner_share_never_goes_negative(self):
        conn = _SettingsConn(
            {
                "commission_rate_wagering_active": {"percent": 5.0},
                "creator_cut_percent_wagering_active": {"percent": 4.0},
                "referral_l1_percent_wagering_active": {"percent": 1.0},
                "referral_l2_percent_wagering_active": {"percent": 1.0},
                "min_bet_rub": {"amount": 10.0},
                "max_bet_rub": {"amount": 100000.0},
                "min_withdrawal_rub": {"amount": 100.0},
            }
        )

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.get_casino_settings(admin={"id": 7, "username": "owner"})

        self.assertEqual(response.owner_share_percent, 0.0)
        self.assertEqual(response.commission_preview.owner_rub, 0.0)

    async def test_get_returns_task2_defaults_when_keys_are_missing(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.get_casino_settings(admin={"id": 7, "username": "owner"})

        self.assertEqual(response.commission_cap_rub, 0.0)
        self.assertEqual(response.commission_min_rub, 0.0)
        self.assertEqual(response.bankroll_floor_rub, 0.0)
        self.assertEqual(response.liability_amount_rub, 0.0)
        self.assertEqual(response.max_profit_pct_per_round, 1.0)
        self.assertEqual(response.max_profit_pct_per_round_all, 1.5)
        self.assertEqual(response.per_game_limits, {})
        self.assertEqual(response.max_rounds_per_player_per_day, {})
        self.assertEqual(response.bet_step_rub, 10.0)
        self.assertEqual(response.max_concurrent_games_per_player, 10)
        self.assertEqual(response.pending_invite_ttl_minutes, 10)
        self.assertEqual(response.move_timeout_minutes, 120)
        self.assertEqual(response.holdem_small_blind_rub, 10.0)
        self.assertEqual(response.holdem_big_blind_rub, 20.0)
        self.assertEqual(response.holdem_rake_percent, 5.0)
        self.assertEqual(response.holdem_rake_cap_rub, 50.0)
        self.assertEqual(response.holdem_action_timeout_seconds, 30)
        self.assertEqual(response.holdem_min_buyin_bb, 20)
        self.assertEqual(response.holdem_max_buyin_bb, 100)
        self.assertEqual(response.jackpot_collect_seconds, 300)
        self.assertEqual(response.jackpot_max_players, 30)
        self.assertEqual(response.jackpot_rake_percent, 5.0)
        self.assertEqual(response.roulette_table_collect_seconds, 25)
        self.assertEqual(response.roulette_table_max_players, 24)
        self.assertTrue(response.clans_enabled)
        self.assertEqual(response.clan_max_members, 20)
        self.assertFalse(response.deposit_limit_enabled)
        self.assertFalse(response.loss_limit_enabled)
        self.assertFalse(response.wager_limit_enabled)
        self.assertFalse(response.session_limit_enabled)
        self.assertEqual(response.reality_check_default_minutes, 60)
        self.assertEqual(response.self_exclusion_min_hours, 24)
        self.assertEqual(response.timeout_max_hours, 72)
        self.assertEqual(response.limit_loosening_delay_hours, 24)
        self.assertEqual(response.withdrawal_auto_approve_max_rub, 0.0)
        self.assertEqual(response.withdrawal_manual_review_min_rub, 0.0)
        self.assertEqual(response.withdrawal_daily_limit_rub, 0.0)
        self.assertEqual(response.withdrawal_hourly_limit_rub, 0.0)
        self.assertTrue(response.seed_rotation_allowed)
        self.assertEqual(set(response.provably_fair_enabled), set(admin_casino.KNOWN_GAME_KEYS))
        self.assertTrue(all(flag is False for flag in response.provably_fair_enabled.values()))

    async def test_patch_stores_zero_commission_cap_as_amount_wrapper(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.update_casino_settings(
                admin_casino.CasinoSettingsUpdate(commission_cap_rub=0, reason="audit test"),
                admin={"id": 7, "username": "owner"},
            )

        self.assertEqual(response.commission_cap_rub, 0.0)
        stored = None
        for _query, args in conn.execute_calls:
            if args and args[0] == "commission_cap_rub":
                stored = json.loads(args[1])
        self.assertEqual(stored, {"amount": 0.0})

    async def test_patch_stores_holdem_wrappers(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.update_casino_settings(
                admin_casino.CasinoSettingsUpdate(
                    holdem_small_blind_rub=5,
                    holdem_big_blind_rub=10,
                    holdem_rake_percent=4,
                    holdem_rake_cap_rub=0,
                    holdem_action_timeout_seconds=15,
                    holdem_min_buyin_bb=10,
                    holdem_max_buyin_bb=40,
                    reason="audit test",
                ),
                admin={"id": 7, "username": "owner"},
            )

        self.assertEqual(response.holdem_small_blind_rub, 5.0)
        self.assertEqual(response.holdem_big_blind_rub, 10.0)
        self.assertEqual(response.holdem_rake_percent, 4.0)
        self.assertEqual(response.holdem_rake_cap_rub, 0.0)
        self.assertEqual(response.holdem_action_timeout_seconds, 15)
        self.assertEqual(response.holdem_min_buyin_bb, 10)
        self.assertEqual(response.holdem_max_buyin_bb, 40)
        stored = {args[0]: json.loads(args[1]) for _query, args in _setting_inserts(conn)}
        self.assertEqual(stored["holdem_small_blind_rub"], {"amount": 5.0})
        self.assertEqual(stored["holdem_rake_percent"], {"percent": 4.0})
        self.assertEqual(stored["holdem_action_timeout_seconds"], {"value": 15})
        self.assertEqual(stored["holdem_rake_cap_rub"], {"amount": 0.0})

    async def test_patch_rejects_inverted_holdem_buyin_bb(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await admin_casino.update_casino_settings(
                    admin_casino.CasinoSettingsUpdate(
                        holdem_min_buyin_bb=80,
                        holdem_max_buyin_bb=20,
                        reason="audit test",
                    ),
                    admin={"id": 7, "username": "owner"},
                )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(conn.execute_calls, [])

    async def test_patch_stores_int_and_bool_wrappers(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.update_casino_settings(
                admin_casino.CasinoSettingsUpdate(
                    max_concurrent_games_per_player=4,
                    deposit_limit_enabled=True,
                    per_game_limits={"pvp_dice": {"min": 10, "max": 50000}},
                    reason="audit test",
                ),
                admin={"id": 7, "username": "owner"},
            )

        self.assertEqual(response.max_concurrent_games_per_player, 4)
        self.assertTrue(response.deposit_limit_enabled)
        self.assertEqual(response.per_game_limits["pvp_dice"]["min"], 10.0)
        stored = {args[0]: json.loads(args[1]) for _query, args in _setting_inserts(conn)}
        self.assertEqual(stored["max_concurrent_games_per_player"], {"value": 4})
        self.assertEqual(stored["deposit_limit_enabled"], {"enabled": True})
        self.assertEqual(stored["per_game_limits"], {"pvp_dice": {"min": 10.0, "max": 50000.0}})

    async def test_patch_saves_when_volume_tiers_arrive_as_dicts(self):
        conn = _SettingsConn(
            {
                "commission_rate": {"percent": 15.0},
                "commission_rate_wagering_active": {"percent": 15.0},
                "commission_rate_wagering_complete": {"percent": 5.0},
                "creator_cut_percent": {"percent": 3.0},
                "referral_l1_percent": {"percent": 2.0},
                "referral_l2_percent": {"percent": 2.0},
                "creator_cut_percent_wagering_active": {"percent": 3.0},
                "referral_l1_percent_wagering_active": {"percent": 2.0},
                "referral_l2_percent_wagering_active": {"percent": 2.0},
                "creator_cut_percent_wagering_complete": {"percent": 1.0},
                "referral_l1_percent_wagering_complete": {"percent": 0.5},
                "referral_l2_percent_wagering_complete": {"percent": 0.5},
                "wagering_percent": {"percent": 21.0},
                "min_bet_rub": {"amount": 10.0},
                "max_bet_rub": {"amount": 100000.0},
                "min_withdrawal_rub": {"amount": 100.0},
            }
        )

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.update_casino_settings(
                admin_casino.CasinoSettingsUpdate(
                    commission_rate_wagering_active=13,
                    cashback_volume_tiers=[
                        admin_casino.CashbackVolumeTierRow(min_wager_rub=0, percent=2),
                    ],
                    commission_volume_tiers=[
                        admin_casino.CommissionVolumeTierRow(
                            min_wager_rub=0, active_rate=13, complete_rate=5
                        ),
                    ],
                    reason="audit test",
                ),
                admin={"id": 7, "username": "owner"},
            )

        self.assertEqual(response.commission_rate_wagering_active, 13.0)
        stored = {args[0]: json.loads(args[1]) for _query, args in _setting_inserts(conn)}
        self.assertEqual(stored["commission_rate_wagering_active"], {"percent": 13.0})
        self.assertEqual(stored["commission_volume_tiers"][0]["active_rate"], 13.0)

    async def test_patch_without_reason_is_rejected(self):
        conn = _SettingsConn()

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await admin_casino.update_casino_settings(
                    admin_casino.CasinoSettingsUpdate(commission_cap_rub=0),
                    admin={"id": 7, "username": "owner"},
                )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(conn.execute_calls, [])
        self.assertEqual(conn.audit_rows, [])

    async def test_patch_writes_one_audit_row_per_changed_key_with_shared_batch(self):
        conn = _SettingsConn(
            {
                "commission_rate": {"percent": 15.0},
                "commission_rate_wagering_active": {"percent": 15.0},
                "commission_rate_wagering_complete": {"percent": 5.0},
                "creator_cut_percent": {"percent": 3.0},
                "referral_l1_percent": {"percent": 2.0},
                "referral_l2_percent": {"percent": 2.0},
                "creator_cut_percent_wagering_active": {"percent": 3.0},
                "referral_l1_percent_wagering_active": {"percent": 2.0},
                "referral_l2_percent_wagering_active": {"percent": 2.0},
                "creator_cut_percent_wagering_complete": {"percent": 1.0},
                "referral_l1_percent_wagering_complete": {"percent": 0.5},
                "referral_l2_percent_wagering_complete": {"percent": 0.5},
                "min_bet_rub": {"amount": 10.0},
                "max_bet_rub": {"amount": 100000.0},
                "min_withdrawal_rub": {"amount": 100.0},
                "commission_cap_rub": {"amount": 0.0},
                "bankroll_floor_rub": {"amount": 0.0},
                "deposit_limit_enabled": {"enabled": False},
            }
        )

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            await admin_casino.update_casino_settings(
                admin_casino.CasinoSettingsUpdate(
                    commission_cap_rub=50,
                    bankroll_floor_rub=1000,
                    deposit_limit_enabled=True,
                    reason="три поля",
                ),
                admin={"id": 7, "username": "owner"},
            )

        by_key = {row["key"]: row for row in conn.audit_rows}
        self.assertEqual(
            set(by_key),
            {"commission_cap_rub", "bankroll_floor_rub", "deposit_limit_enabled"},
        )
        self.assertEqual(len({row["batch_id"] for row in conn.audit_rows}), 1)
        self.assertEqual(by_key["commission_cap_rub"]["old_value"], {"amount": 0.0})
        self.assertEqual(by_key["commission_cap_rub"]["new_value"], {"amount": 50.0})
        self.assertEqual(by_key["bankroll_floor_rub"]["old_value"], {"amount": 0.0})
        self.assertEqual(by_key["bankroll_floor_rub"]["new_value"], {"amount": 1000.0})
        self.assertEqual(by_key["deposit_limit_enabled"]["old_value"], {"enabled": False})
        self.assertEqual(by_key["deposit_limit_enabled"]["new_value"], {"enabled": True})
        self.assertTrue(all(row["reason"] == "три поля" for row in conn.audit_rows))
        self.assertTrue(all(row["changed_by"] == "owner" for row in conn.audit_rows))

    async def test_list_audit_applies_date_key_and_author_filters(self):
        conn = _SettingsConn()
        conn.audit_rows = [
            {
                "id": 1,
                "batch_id": "11111111-1111-1111-1111-111111111111",
                "key": "commission_cap_rub",
                "old_value": {"amount": 0.0},
                "new_value": {"amount": 50.0},
                "changed_by": "owner",
                "changed_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
                "reason": "три поля",
            }
        ]

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            response = await admin_casino.list_casino_settings_audit(
                admin={"id": 7, "username": "owner"},
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 28),
                key="commission_cap_rub",
                changed_by="owner",
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.items[0].key, "commission_cap_rub")
        self.assertEqual(response.items[0].old_value, {"amount": 0.0})
        self.assertEqual(response.items[0].new_value, {"amount": 50.0})
        self.assertTrue(any("casino_settings_audit" in query for query in conn.fetch_queries))
        self.assertTrue(any("key =" in query for query in conn.fetch_queries))
        self.assertTrue(any("changed_by =" in query for query in conn.fetch_queries))

    async def test_list_audit_window_q_and_batch_filters(self):
        conn = _SettingsConn()
        conn.audit_rows = [
            {
                "id": 1,
                "batch_id": "11111111-1111-1111-1111-111111111111",
                "key": "cashback_volume_tiers",
                "old_value": [{"percent": 2.0, "min_wager_rub": 0.0}],
                "new_value": [{"percent": 5.0, "min_wager_rub": 0.0}],
                "changed_by": "123",
                "changed_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
                "reason": "ук",
            }
        ]

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await admin_casino.list_casino_settings_audit(
                    admin={"id": 7, "username": "owner"},
                    window="1y",
                )
            self.assertEqual(raised.exception.status_code, 422)

            response = await admin_casino.list_casino_settings_audit(
                admin={"id": 7, "username": "owner"},
                window="7d",
                q="cashback",
                batch_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.items[0].key, "cashback_volume_tiers")
        joined = "\n".join(conn.fetch_queries)
        self.assertIn("interval '7 days'", joined)
        self.assertIn("strpos(lower(key)", joined)
        self.assertIn("batch_id =", joined)


class CasinoFinanceOwnerAclTests(unittest.TestCase):
    """finance-owner ACL закрывает привязку чата и статус бота от рядового админа."""

    def test_chat_binding_and_bot_status_require_finance_owner(self):
        import inspect

        for endpoint in (
            admin_casino.get_game_chat_binding,
            admin_casino.get_casino_bot_status,
            admin_casino.confirm_game_chat_binding,
            admin_casino.disable_game_chat_binding,
        ):
            with self.subTest(endpoint=endpoint.__name__):
                sig = inspect.signature(endpoint)
                admin_param = sig.parameters["admin"]
                self.assertIs(
                    admin_param.default.dependency,
                    admin_casino.get_current_finance_owner,
                )


class _DashboardConn:
    def __init__(self):
        self.queries: list[str] = []
        self.fetchrow_calls = 0

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        self.fetchrow_calls += 1
        if "focus_vpn_users" in query:
            raise AssertionError("dashboard must use bot_users without N+1 queries")
        if "total_games" in query:
            return {"total_games": 2, "total_turnover": 300, "total_commission": 30}
        if "commission_profit" in query and "casino_house_ledger" in query:
            return {"commission_profit": 21, "house_game_profit": 9}
        if "active_players" in query:
            return {"active_players": 3}
        if "games_today" in query:
            return {"games_today": 1, "turnover_today": 200, "commission_today": 20}
        raise AssertionError(query)

    async def fetch(self, query, *args):
        self.queries.append(query)
        if "GROUP BY game_type" in query:
            return [{"game_type": "pvp_dice", "count": 2}]
        if "casino_clans" in query or "/* clan:" in query:
            return []
        if "bot_users" not in query:
            raise AssertionError("top-player query must join bot_users")
        return [
            {
                "player_id": 42,
                "username": None,
                "first_name": "Player Name",
                "games_count": 2,
                "total_bet": 200,
            }
        ]


class CasinoDashboardEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_uses_normalized_stats_handle(self):
        from casino_stats import assemble_casino_stats

        lifetime = assemble_casino_stats(
            round_rows=[{
                "day": date(2026, 9, 1),
                "surface": "v2",
                "game_type": "pvp_dice",
                "round_key": "t1",
                "player_count": 2,
                "bot_count": 0,
                "handle_rub": 200,
                "house_stake_rub": 0,
                "player_payout_rub": 190,
                "rake_rub": 10,
            }],
            player_rows=[{"player_id": 42, "username": "Player Name", "rounds": 2, "handle_rub": 200, "payout_rub": 190}],
            owner={"commission_profit_rub": 0, "house_game_profit_rub": 10, "owner_profit_rub": 10},
        )
        today = assemble_casino_stats(round_rows=[], player_rows=[])

        async def fake_stats(conn, d_from=None, d_to=None):
            return lifetime if d_from is None else today

        class _Pool:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *args):
                        return False

                return _Ctx()

        async def get_pool():
            return _Pool()

        with patch("routers.admin_casino.get_pool", new=get_pool), patch(
            "routers.admin_casino.fetch_casino_stats", side_effect=fake_stats
        ), patch("routers.admin_casino.today_moscow", return_value=date(2026, 9, 1)):
            response = await admin_casino.get_casino_dashboard(admin={"id": 7})

        self.assertEqual(response.total_turnover_rub, 200.0)
        self.assertEqual(response.top_players[0]["username"], "Player Name")
        self.assertEqual(response.games_by_type, {"pvp_dice": 1})

    async def test_chart_uses_the_same_turnover_definition(self):
        from casino_stats import assemble_casino_stats

        stats = assemble_casino_stats(
            round_rows=[{
                "day": date(2026, 8, 21),
                "surface": "v2",
                "game_type": "pvp_dice",
                "round_key": "t1",
                "player_count": 2,
                "bot_count": 0,
                "handle_rub": 200,
                "house_stake_rub": 0,
                "player_payout_rub": 190,
                "rake_rub": 20,
            }],
            player_rows=[],
            owner_daily={"2026-08-21": 20},
            d_from=date(2026, 8, 21),
            d_to=date(2026, 8, 21),
        )

        class _Pool:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *args):
                        return False

                return _Ctx()

        async def get_pool():
            return _Pool()

        with patch("routers.admin_casino.get_pool", new=get_pool), patch(
            "routers.admin_casino.fetch_casino_stats", new=AsyncMock(return_value=stats)
        ), patch("routers.admin_casino.today_moscow", return_value=date(2026, 8, 21)):
            response = await admin_casino.get_casino_chart_data(admin={"id": 7}, days=1)

        self.assertEqual(response[0]["turnover_rub"], 200.0)
        self.assertEqual(response[0]["ggr_rub"], 10.0)

    async def test_chart_handles_nullable_aggregates_without_crashing(self):
        from casino_stats import empty_casino_stats

        empty = empty_casino_stats(d_from=date(2026, 8, 21), d_to=date(2026, 8, 21))

        class _Pool:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *args):
                        return False

                return _Ctx()

        async def get_pool():
            return _Pool()

        with patch("routers.admin_casino.get_pool", new=get_pool), patch(
            "routers.admin_casino.fetch_casino_stats", new=AsyncMock(return_value=empty)
        ), patch("routers.admin_casino.today_moscow", return_value=date(2026, 8, 21)):
            response = await admin_casino.get_casino_chart_data(admin={"id": 7}, days=1)

        self.assertEqual(response[0]["turnover_rub"], 0.0)
        self.assertEqual(response[0]["commission_rub"], 0.0)
        self.assertEqual(response[0]["owner_profit_rub"], 0.0)


class _WithdrawalConn:
    def __init__(
        self,
        *,
        status="pending",
        creator_account_id: int | None = 42,
        telegram_id: int | None = None,
        balance_exists=True,
        update_result="UPDATE 1",
    ):
        self.status = status
        self.creator_account_id = creator_account_id
        self.telegram_id = telegram_id
        self.balance_exists = balance_exists
        self.update_result = update_result
        self.transaction_entries = 0
        self.fetchrow_queries: list[str] = []
        self.execute_calls: list[tuple[str, tuple]] = []

    def transaction(self):
        conn = self

        class _Transaction:
            async def __aenter__(self):
                conn.transaction_entries += 1

            async def __aexit__(self, *args):
                return False

        return _Transaction()

    async def fetchrow(self, query, *args):
        self.fetchrow_queries.append(query)
        if "FROM casino_creator_withdrawals" in query:
            return {
                "id": 11,
                "creator_account_id": self.creator_account_id,
                "telegram_id": self.telegram_id,
                "amount_rub": 250,
                "status": self.status,
            }
        if "FROM casino_creator_balance" in query:
            if not self.balance_exists:
                return None
            return {
                "creator_account_id": self.creator_account_id,
                "telegram_id": self.telegram_id,
            }
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return self.update_result


class CasinoWithdrawalEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_maps_migration_columns_to_frontend_aliases(self):
        created_at = datetime(2026, 8, 21, tzinfo=timezone.utc)
        captured = {}

        class _ListConn:
            async def fetch(self, query, *args):
                captured["query"] = query
                return [
                    {
                        "withdrawal_id": 11,
                        "created_at": created_at,
                        "amount_rub": 250,
                        "method": "sbp",
                        "requisites": "masked",
                        "status": "rejected",
                        "processed_at": created_at,
                        "processed_by_admin_id": "owner",
                        "tx_hash": None,
                        "rejection_reason": "invalid",
                    }
                ]

        async def get_pool():
            return _Pool(_ListConn())

        with patch("routers.admin_casino.get_pool", new=get_pool):
            rows = await admin_casino.get_creator_withdrawals(admin={"id": 7})

        normalized = " ".join(captured["query"].split()).lower()
        self.assertIn("id as withdrawal_id", normalized)
        self.assertIn("reject_reason as rejection_reason", normalized)
        self.assertIn("processed_by_username as processed_by_admin_id", normalized)
        self.assertEqual(rows[0].withdrawal_id, 11)
        self.assertEqual(rows[0].processed_by_admin_id, "owner")

    async def test_approve_locks_and_updates_the_account_only_creator_total(self):
        conn = _WithdrawalConn(creator_account_id=42, telegram_id=None)

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool), patch.object(
            admin_casino.logger, "info"
        ) as log_info:
            result = await admin_casino.approve_creator_withdrawal(
                11,
                admin_casino.WithdrawalApproval(tx_hash="sensitive-hash"),
                admin={"id": 7, "username": "owner"},
            )

        self.assertTrue(result["success"])
        self.assertEqual(conn.transaction_entries, 1)
        self.assertTrue(all("FOR UPDATE" in query for query in conn.fetchrow_queries))
        balance_update = next(call for call in conn.execute_calls if "casino_creator_balance" in call[0])
        withdrawal_update = next(call for call in conn.execute_calls if "casino_creator_withdrawals" in call[0])
        self.assertIn("creator_account_id = $2", balance_update[0])
        self.assertEqual(balance_update[1], (250, 42))
        self.assertIn("status = 'pending'", withdrawal_update[0])
        self.assertEqual(withdrawal_update[1], ("owner", "sensitive-hash", 11))
        self.assertNotIn("sensitive-hash", repr(log_info.call_args))

    async def test_reject_locks_and_refunds_the_account_only_creator(self):
        conn = _WithdrawalConn(creator_account_id=42, telegram_id=None)

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool), patch.object(
            admin_casino.logger, "info"
        ) as log_info:
            result = await admin_casino.reject_creator_withdrawal(
                11,
                admin_casino.WithdrawalRejection(reason="sensitive reason"),
                admin={"id": 7, "username": "owner"},
            )

        self.assertTrue(result["success"])
        self.assertEqual(conn.transaction_entries, 1)
        self.assertTrue(all("FOR UPDATE" in query for query in conn.fetchrow_queries))
        balance_update = next(call for call in conn.execute_calls if "casino_creator_balance" in call[0])
        withdrawal_update = next(call for call in conn.execute_calls if "casino_creator_withdrawals" in call[0])
        self.assertIn("creator_account_id = $2", balance_update[0])
        self.assertEqual(balance_update[1], (250, 42))
        self.assertIn("status = 'pending'", withdrawal_update[0])
        self.assertEqual(withdrawal_update[1], ("owner", "sensitive reason", 11))
        self.assertNotIn("sensitive reason", repr(log_info.call_args))

    async def test_legacy_withdrawal_uses_locked_telegram_balance(self):
        conn = _WithdrawalConn(creator_account_id=None, telegram_id=777)

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            await admin_casino.approve_creator_withdrawal(
                11,
                admin_casino.WithdrawalApproval(tx_hash="hash"),
                admin={"id": 7, "username": "owner"},
            )

        balance_update = next(call for call in conn.execute_calls if "casino_creator_balance" in call[0])
        self.assertIn("telegram_id = $2", balance_update[0])
        self.assertEqual(balance_update[1], (250, 777))

    async def test_missing_creator_balance_preserves_pending_withdrawal(self):
        conn = _WithdrawalConn(balance_exists=False)

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await admin_casino.approve_creator_withdrawal(
                    11,
                    admin_casino.WithdrawalApproval(tx_hash="hash"),
                    admin={"id": 7, "username": "owner"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(conn.execute_calls, [])

    async def test_unexpected_update_count_preserves_pending_withdrawal(self):
        conn = _WithdrawalConn(update_result="UPDATE 0")

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await admin_casino.reject_creator_withdrawal(
                    11,
                    admin_casino.WithdrawalRejection(reason="invalid"),
                    admin={"id": 7, "username": "owner"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(conn.execute_calls), 1)

    async def test_repeated_processing_is_rejected_without_balance_change(self):
        conn = _WithdrawalConn(status="approved")

        async def get_pool():
            return _Pool(conn)

        with patch("routers.admin_casino.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await admin_casino.approve_creator_withdrawal(
                    11,
                    admin_casino.WithdrawalApproval(tx_hash="hash"),
                    admin={"id": 7, "username": "owner"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(conn.transaction_entries, 1)
        self.assertEqual(conn.execute_calls, [])


if __name__ == "__main__":
    unittest.main()
