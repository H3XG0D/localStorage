"""Focused regressions for casino creator account endpoints."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("dependency override required")


_auth_module = sys.modules.get("auth")
_db_module = sys.modules.get("db")
_referral_module = sys.modules.get("referral_links")
if _auth_module is None:
    sys.modules["auth"] = types.SimpleNamespace(get_current_user=_dependency_stub)
if _db_module is None:
    sys.modules["db"] = types.SimpleNamespace(get_pool=_dependency_stub)
if _referral_module is None:
    sys.modules["referral_links"] = types.SimpleNamespace(web_ref_link=lambda token: f"https://focuspay.org/ref/{token}")
try:
    from routers import casino_creator
finally:
    if _auth_module is None:
        del sys.modules["auth"]
    if _db_module is None:
        del sys.modules["db"]
    if _referral_module is None:
        del sys.modules["referral_links"]


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


class CreatorRequestModelTests(unittest.TestCase):
    def test_withdrawal_request_rejects_extra_fields(self):
        with self.assertRaises(ValidationError):
            casino_creator.CreateWithdrawalRequest.model_validate(
                {"amount_rub": 100, "method": "sbp", "requisites": "masked", "status": "approved"}
            )

    def test_withdrawal_amount_requires_money_precision(self):
        request = casino_creator.CreateWithdrawalRequest.model_validate(
            {"amount_rub": "100.01", "method": "sbp", "requisites": "masked"}
        )
        self.assertEqual(request.amount_rub, Decimal("100.01"))
        with self.assertRaises(ValidationError):
            casino_creator.CreateWithdrawalRequest.model_validate(
                {"amount_rub": "100.001", "method": "sbp", "requisites": "masked"}
            )

    def test_invalid_minimum_setting_falls_back_to_canonical_default(self):
        self.assertEqual(casino_creator._minimum_withdrawal({"amount": "125.50"}), Decimal("125.50"))
        self.assertEqual(casino_creator._minimum_withdrawal({"amount": "invalid"}), Decimal("100.00"))
        self.assertEqual(casino_creator._minimum_withdrawal({"amount": 0}), Decimal("100.00"))
        self.assertEqual(casino_creator._minimum_withdrawal(None), Decimal("100.00"))


class CreatorAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticates_by_active_web_user_creator_account(self):
        captured = {}

        class _Conn:
            async def fetchrow(self, query, *args):
                captured["query"] = query
                captured["args"] = args
                return {"account_id": 44, "web_user_id": 12, "ref_token": "creatorref"}

        async def get_pool():
            return _Pool(_Conn())

        with patch("routers.casino_creator.get_pool", new=get_pool):
            creator = await casino_creator.get_creator_account({"id": 12, "telegram_user_id": 999})

        self.assertEqual(creator.account_id, 44)
        self.assertEqual(creator.web_user_id, 12)
        self.assertEqual(captured["args"], (12,))
        self.assertIn("casino_creator_accounts", captured["query"])
        self.assertNotIn("creator_telegram_id", captured["query"])

    async def test_rejects_user_without_active_creator_account(self):
        class _Conn:
            async def fetchrow(self, query, *args):
                return None

        async def get_pool():
            return _Pool(_Conn())

        with patch("routers.casino_creator.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as raised:
                await casino_creator.get_creator_account({"id": 12})
        self.assertEqual(raised.exception.status_code, 403)


class CreatorStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_filter_by_creator_account_and_count_distinct_games(self):
        queries = []

        class _Conn:
            async def fetchrow(self, query, *args):
                queries.append((query, args))
                return {"games": 2, "commission": 10.0}

        async def get_pool():
            return _Pool(_Conn())

        creator = casino_creator.CreatorPrincipal(account_id=44, web_user_id=12, ref_token="ref")
        with patch("routers.casino_creator.get_pool", new=get_pool):
            response = await casino_creator.get_creator_stats(creator=creator)

        self.assertEqual(response.total_games, 2)
        self.assertEqual(len(queries), 4)
        self.assertEqual(queries[0][1], (44,))
        self.assertEqual(queries[1][1], (44, timedelta(days=0)))
        self.assertEqual(queries[2][1], (44, timedelta(days=7)))
        self.assertEqual(queries[3][1], (44, timedelta(days=30)))
        for query, args in queries:
            normalized = " ".join(query.split()).lower()
            self.assertIn("count(distinct game_id)", normalized)
            self.assertIn("creator_account_id = $1", normalized)
            self.assertIn("status in ('accrued', 'paid')", normalized)
            self.assertEqual(args[0], 44)

    async def test_chart_filters_by_creator_account(self):
        captured = {}

        class _Conn:
            async def fetch(self, query, *args):
                captured["query"] = query
                captured["args"] = args
                return []

        async def get_pool():
            return _Pool(_Conn())

        creator = casino_creator.CreatorPrincipal(account_id=44, web_user_id=12, ref_token="ref")
        with patch("routers.casino_creator.get_pool", new=get_pool):
            response = await casino_creator.get_creator_chart(creator=creator, days=30)

        normalized = " ".join(captured["query"].split()).lower()
        self.assertIn("count(distinct game_id)", normalized)
        self.assertIn("creator_account_id = $1", normalized)
        self.assertIn("status in ('accrued', 'paid')", normalized)
        self.assertIn("current_date - $2::interval", normalized)
        self.assertEqual(captured["args"], (44, timedelta(days=30)))
        self.assertEqual(response, {"days": 30, "data": []})


class CreatorProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_returns_configured_minimum_withdrawal(self):
        class _Conn:
            async def fetchrow(self, query, *args):
                if "casino_creator_balance" in query:
                    return {
                        "balance_rub": 50,
                        "total_earned_rub": 200,
                        "total_withdrawn_rub": 150,
                        "games_count": 3,
                        "last_game_at": None,
                    }
                if "casino_settings" in query:
                    return {"value": {"amount": "125.50"}}
                raise AssertionError(query)

        async def get_pool():
            return _Pool(_Conn())

        creator = casino_creator.CreatorPrincipal(account_id=44, web_user_id=12, ref_token="ref")
        with patch("routers.casino_creator.get_pool", new=get_pool):
            response = await casino_creator.get_creator_profile(creator=creator)

        self.assertEqual(response.account_id, 44)
        self.assertEqual(response.min_withdrawal_rub, 125.5)

    async def test_profile_uses_safe_minimum_when_setting_is_missing(self):
        class _Conn:
            async def fetchrow(self, query, *args):
                if "casino_creator_balance" in query:
                    return {
                        "balance_rub": 0,
                        "total_earned_rub": 0,
                        "total_withdrawn_rub": 0,
                        "games_count": 0,
                        "last_game_at": None,
                    }
                if "casino_settings" in query:
                    return None
                raise AssertionError(query)

        async def get_pool():
            return _Pool(_Conn())

        creator = casino_creator.CreatorPrincipal(account_id=44, web_user_id=12, ref_token="ref")
        with patch("routers.casino_creator.get_pool", new=get_pool):
            response = await casino_creator.get_creator_profile(creator=creator)

        self.assertEqual(response.min_withdrawal_rub, 100.0)
