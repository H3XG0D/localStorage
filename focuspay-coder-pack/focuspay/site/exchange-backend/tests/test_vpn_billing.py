"""FocusVPN billing: settings validation, gates, saga decisions, reconciliation diff."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import vpn_billing
from routers.admin_vpn import reconcile_rows


def _row(**kw):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "telegram_id": 42,
        "kind": "paid",
        "plan_code": "week",
        "days": 7,
        "price_rub": Decimal("300.00"),
        "status": "held",
        "order_ref": "vpn-1",
        "cp_ends_at": None,
        "error": None,
    }
    base.update(kw)
    return base


class SettingsTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        cfg = vpn_billing.validate_settings(vpn_billing.DEFAULT_SETTINGS)
        self.assertEqual([p["code"] for p in cfg["plans"]], ["week", "month", "q3"])
        self.assertEqual([p["code"] for p in cfg["device_addons"]], ["week", "month", "q3"])
        self.assertEqual(cfg["device_addons"][0]["price_rub"], "300.00")
        self.assertEqual(cfg["purchase_min_exchanges"], 10)
        self.assertEqual(cfg["purchase_min_invited"], 30)
        self.assertEqual(cfg["trial"]["min_exchanges"], 0)
        self.assertTrue(cfg["trial"]["enabled"])
        self.assertEqual(cfg["app_url"], "https://focuspay.org/vpn.apk")
        self.assertEqual(cfg["review_bonus_text_rub"], 25)
        self.assertEqual(cfg["review_bonus_photo_rub"], 50)

    def test_legacy_deposit_keys_still_read(self):
        cfg = vpn_billing.validate_settings({
            "plans": [{"code": "week", "days": 7, "price_rub": "300"}],
            "trial": {"enabled": True, "days": 1, "min_deposits": 3},
            "purchase_min_deposits": 7,
        })
        self.assertEqual(cfg["purchase_min_exchanges"], 7)
        self.assertEqual(cfg["trial"]["min_exchanges"], 3)
        self.assertNotIn("purchase_min_deposits", cfg)
        self.assertEqual([p["code"] for p in cfg["device_addons"]], ["week", "month", "q3"])
        self.assertEqual(cfg["purchase_min_invited"], 30)
        self.assertEqual(cfg["review_bonus_text_rub"], 25)
        self.assertEqual(cfg["review_bonus_photo_rub"], 50)

    def test_review_bonus_must_be_whole_rubles(self):
        with self.assertRaises(ValueError):
            vpn_billing.validate_settings({
                "plans": [{"code": "week", "days": 7, "price_rub": "300"}],
                "review_bonus_text_rub": 25.5,
            })
        cfg = vpn_billing.validate_settings({
            "plans": [{"code": "week", "days": 7, "price_rub": "300"}],
            "review_bonus_text_rub": 30,
            "review_bonus_photo_rub": 60,
        })
        self.assertEqual((cfg["review_bonus_text_rub"], cfg["review_bonus_photo_rub"]), (30, 60))

    def test_device_addons_can_be_cleared(self):
        cfg = vpn_billing.validate_settings({
            "plans": [{"code": "week", "days": 7, "price_rub": "300"}],
            "device_addons": [],
        })
        self.assertEqual(cfg["device_addons"], [])
        with self.assertRaises(ValueError):
            vpn_billing.validate_settings({
                "plans": [{"code": "week", "days": 7, "price_rub": "300"}],
                "device_addons": [{"code": "week", "days": 7, "price_rub": "0"}],
            })

    def test_app_url_must_be_http(self):
        with self.assertRaises(ValueError):
            vpn_billing.validate_settings({"plans": [{"code": "w", "days": 7, "price_rub": "1"}], "app_url": "javascript:x"})

    def test_rejects_bad_plans(self):
        bad = [
            {"plans": []},
            {"plans": [{"code": "week", "days": 7, "price_rub": "0"}]},
            {"plans": [{"code": "week", "days": 0, "price_rub": "1"}]},
            {"plans": [{"code": "week", "days": 400, "price_rub": "1"}]},
            {"plans": [{"code": "trial", "days": 7, "price_rub": "1"}]},
            {"plans": [{"code": "a", "days": 7, "price_rub": "1"}, {"code": "A", "days": 7, "price_rub": "1"}]},
            {"plans": [{"code": "x y", "days": 7, "price_rub": "1"}]},
        ]
        for raw in bad:
            with self.assertRaises(ValueError, msg=raw):
                vpn_billing.validate_settings(raw)

    def test_price_is_normalised_to_kopecks(self):
        cfg = vpn_billing.validate_settings({"plans": [{"code": "Week", "days": 7, "price_rub": 299.9}]})
        self.assertEqual(cfg["plans"][0], {"code": "week", "title": "week", "days": 7, "price_rub": "299.90"})
        self.assertFalse(cfg["trial"]["enabled"])

    def test_gate(self):
        self.assertTrue(vpn_billing.gate_ok(0, 1, 0))
        self.assertFalse(vpn_billing.gate_ok(9, 1, 10))
        self.assertTrue(vpn_billing.gate_ok(10, 1, 10))
        self.assertFalse(vpn_billing.purchase_allowed(9, 29, 1, 10, 30))
        self.assertTrue(vpn_billing.purchase_allowed(10, 0, 1, 10, 30))
        self.assertTrue(vpn_billing.purchase_allowed(0, 30, 1, 10, 30))
        self.assertFalse(vpn_billing.purchase_allowed(0, 30, 1, 10, 0))
        self.assertTrue(vpn_billing.purchase_allowed(0, 0, 7, 10, 30, {7}))
        self.assertFalse(vpn_billing.purchase_allowed(0, 0, 7, 10, 30, set()))
        self.assertTrue(vpn_billing.gate_ok(0, 7, 10, {7}))
        self.assertFalse(vpn_billing.gate_ok(0, 8, 10, {7}))
        self.assertEqual(vpn_billing.parse_trusted_ids([7, 7, 3]), [3, 7])
        self.assertEqual(vpn_billing.parse_trusted_ids("[9]"), [9])
        for bad in (True, 0, -1, "7", 1.5, None):
            with self.assertRaises(ValueError):
                vpn_billing.parse_trusted_ids([bad])
        with patch.dict("os.environ", {"VPN_GATE_ALLOWLIST": "1, 2"}):
            self.assertTrue(vpn_billing.gate_ok(0, 2, 10))
        with patch.dict("os.environ", {"VPN_GATE_ALLOWLIST": "", "VPN_DEPOSIT_GATE_ALLOWLIST": "3"}):
            self.assertTrue(vpn_billing.gate_ok(0, 3, 10))

    def test_plan_cards_discount_and_per_day(self):
        cfg = vpn_billing.validate_settings(vpn_billing.DEFAULT_SETTINGS)
        cards = {c["code"]: c for c in vpn_billing.plan_cards(cfg["plans"])}
        self.assertEqual(cards["week"]["per_day_rub"], 42.86)
        self.assertEqual(cards["week"]["discount_pct"], 0)
        self.assertEqual(cards["month"]["discount_pct"], 23)
        self.assertEqual(cards["q3"]["discount_pct"], 35)

    def test_subscription_view_days_left_rounds_up(self):
        from datetime import datetime, timezone

        now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        view = vpn_billing.subscription_view(
            {"has_live": True, "plan_code": "month", "status": "active", "ends_at": "2026-10-12T15:00:00Z"}, now
        )
        self.assertEqual((view["active"], view["days_left"], view["plan"]), (True, 6, "month"))
        self.assertFalse(vpn_billing.subscription_view({"has_live": False}, now)["active"])
        self.assertFalse(vpn_billing.subscription_view(None, now)["active"])


class LockTests(unittest.IsolatedAsyncioTestCase):
    async def test_lock_binds_telegram_id_as_text(self):
        conn = AsyncMock()
        await vpn_billing.lock_user(conn, 5631021835)
        query, arg = conn.execute.await_args.args
        self.assertIn("pg_advisory_xact_lock(hashtext(", query)
        self.assertNotIn("::text", query)
        self.assertEqual(arg, "5631021835")


class GateCountTests(unittest.IsolatedAsyncioTestCase):
    async def test_gate_counts_completed_exchanges(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=4)
        self.assertEqual(await vpn_billing.exchange_count(conn, 42), 4)
        sql = conn.fetchval.await_args.args[0]
        self.assertIn("FROM orders", sql)
        self.assertIn("'COMPLETED'", sql)

    async def test_status_reports_progress_and_open_trial(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=30)
        with patch.object(vpn_billing, "load_settings", AsyncMock(return_value=vpn_billing.validate_settings(vpn_billing.DEFAULT_SETTINGS))), \
             patch.object(vpn_billing, "exchange_count", AsyncMock(return_value=3)), \
             patch.object(vpn_billing, "trial_used", AsyncMock(return_value=False)), \
             patch.object(vpn_billing, "load_trusted_ids", AsyncMock(return_value=set())), \
             patch("user_unified_balance.unified_available", AsyncMock(return_value=Decimal("500"))):
            st = await vpn_billing.user_status(conn, 42)
        self.assertEqual(st["exchanges"], {"have": 3, "need": 10})
        self.assertEqual(st["invited"], {"have": 30, "need": 30})
        self.assertTrue(st["purchase_open"])
        self.assertFalse(st["trusted"])
        self.assertTrue(st["trial_available"])

    async def test_trusted_account_buys_without_exchanges_or_invites(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=0)

        def status_patches(trusted):
            return (
                patch.object(vpn_billing, "load_settings", AsyncMock(return_value=vpn_billing.validate_settings(vpn_billing.DEFAULT_SETTINGS))),
                patch.object(vpn_billing, "exchange_count", AsyncMock(return_value=0)),
                patch.object(vpn_billing, "trial_used", AsyncMock(return_value=False)),
                patch.object(vpn_billing, "load_trusted_ids", AsyncMock(return_value=trusted)),
                patch("user_unified_balance.unified_available", AsyncMock(return_value=Decimal("500"))),
            )

        from contextlib import ExitStack

        with ExitStack() as stack:
            for item in status_patches({42}):
                stack.enter_context(item)
            opened = await vpn_billing.user_status(conn, 42)
        self.assertTrue(opened["trusted"])
        self.assertTrue(opened["purchase_open"])
        self.assertEqual(opened["exchanges"], {"have": 0, "need": 10})
        self.assertEqual(opened["invited"], {"have": 0, "need": 30})

        with ExitStack() as stack:
            for item in status_patches(set()):
                stack.enter_context(item)
            closed = await vpn_billing.user_status(conn, 42)
        self.assertFalse(closed["trusted"])
        self.assertFalse(closed["purchase_open"])


class CPErrorTests(unittest.TestCase):
    def test_definitive_only_for_client_refusals(self):
        self.assertTrue(vpn_billing.CPError(400, "x").definitive)
        self.assertTrue(vpn_billing.CPError(409, "x").definitive)
        for status in (None, 401, 403, 429, 500, 502):
            self.assertFalse(vpn_billing.CPError(status, "x").definitive, status)


class DriveTests(unittest.IsolatedAsyncioTestCase):
    async def test_grant_ok_confirms(self):
        conn = AsyncMock()
        with patch.object(vpn_billing, "cp_grant", AsyncMock(return_value={"ends_at": "2026-10-14T15:00:00.123456789Z"})), \
             patch.object(vpn_billing, "_mark_granted", AsyncMock()) as mark, \
             patch.object(vpn_billing, "finalize_granted", AsyncMock(return_value=_row(status="paid"))) as fin, \
             patch.object(vpn_billing, "refuse", AsyncMock()) as ref:
            out = await vpn_billing.drive(conn, _row())
        self.assertEqual(out.status, "paid")
        mark.assert_awaited_once()
        self.assertEqual(mark.await_args.args[2].year, 2026)
        fin.assert_awaited_once()
        ref.assert_not_awaited()

    async def test_definitive_refusal_releases(self):
        conn = AsyncMock()
        with patch.object(vpn_billing, "cp_grant", AsyncMock(side_effect=vpn_billing.CPError(400, "bad"))), \
             patch.object(vpn_billing, "refuse", AsyncMock(return_value=_row(status="released"))) as ref, \
             patch.object(vpn_billing, "finalize_granted", AsyncMock()) as fin:
            out = await vpn_billing.drive(conn, _row())
        self.assertEqual(out.status, "released")
        ref.assert_awaited_once()
        fin.assert_not_awaited()

    async def test_network_error_keeps_money_held(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_row(status="held"))
        with patch.object(vpn_billing, "cp_grant", AsyncMock(side_effect=vpn_billing.CPError(None, "timeout"))), \
             patch.object(vpn_billing, "refuse", AsyncMock()) as ref, \
             patch.object(vpn_billing, "_note_attempt", AsyncMock()) as note, \
             patch.object(vpn_billing, "finalize_granted", AsyncMock()) as fin:
            out = await vpn_billing.drive(conn, _row())
        self.assertEqual(out.status, "pending")
        ref.assert_not_awaited()
        fin.assert_not_awaited()
        note.assert_awaited_once()

    async def test_granted_row_skips_cp_and_retries_confirm(self):
        conn = AsyncMock()
        with patch.object(vpn_billing, "cp_grant", AsyncMock()) as grant, \
             patch.object(vpn_billing, "finalize_granted", AsyncMock(return_value=_row(status="paid"))):
            out = await vpn_billing.drive(conn, _row(status="granted"))
        grant.assert_not_awaited()
        self.assertEqual(out.status, "paid")

    async def test_confirm_failure_stays_pending(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_row(status="granted"))
        with patch.object(vpn_billing, "cp_grant", AsyncMock(return_value={"ends_at": None})), \
             patch.object(vpn_billing, "_mark_granted", AsyncMock()), \
             patch.object(vpn_billing, "finalize_granted", AsyncMock(side_effect=RuntimeError("boom"))), \
             patch.object(vpn_billing, "_note_attempt", AsyncMock()) as note:
            out = await vpn_billing.drive(conn, _row())
        self.assertEqual(out.status, "pending")
        note.assert_awaited_once()

    async def test_replay_of_finished_purchase_does_not_call_cp(self):
        conn = AsyncMock()
        with patch.object(vpn_billing, "start_purchase", AsyncMock(return_value=(_row(status="paid"), True))), \
             patch.object(vpn_billing, "drive", AsyncMock()) as drive:
            out = await vpn_billing.purchase(conn, telegram_id=42, plan_code="week", idem_key="k" * 8)
        drive.assert_not_awaited()
        self.assertTrue(out.replay)
        self.assertEqual(out.status, "paid")


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_reminders_kinds_and_dedupe(self):
        from datetime import datetime, timezone

        now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        cp = {"subscriptions": [
            {"telegram_id": 1, "plan_code": "trial", "status": "trialing", "ends_at": "2026-10-07T15:00:00Z"},
            {"telegram_id": 2, "plan_code": "week", "status": "expired", "ends_at": "2026-10-07T09:00:00Z"},
            {"telegram_id": 3, "plan_code": "week", "status": "active", "ends_at": "2026-10-07T16:00:00Z"},
        ]}
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[None, None, 1])  # tg 3 already reminded
        with patch.object(vpn_billing, "cp_request", AsyncMock(return_value=cp)) as req:
            due = await vpn_billing.due_reminders(conn, now)
        path = req.await_args.args[1]
        self.assertIn("from=2026-10-06T12:00:00Z", path)
        self.assertIn("to=2026-10-07T18:00:00Z", path)
        self.assertEqual([(d["telegram_id"], d["kind"]) for d in due], [(1, "soon"), (2, "ended")])

    async def test_mark_reminded_reports_first_writer(self):
        from datetime import datetime, timezone

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"telegram_id": 1}, None])
        at = datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.assertTrue(await vpn_billing.mark_reminded(conn, 1, "soon", at))
        self.assertFalse(await vpn_billing.mark_reminded(conn, 1, "soon", at))
        with self.assertRaises(ValueError):
            await vpn_billing.mark_reminded(conn, 1, "later", at)


class ReconcileTests(unittest.TestCase):
    def test_issues(self):
        fp = [
            _row(id="a", status="paid"),
            _row(id="b", status="released"),
            _row(id="c", status="paid", price_rub=Decimal("990.00"), days=30),
            _row(id="d", status="granted"),
            _row(id="e", status="held"),
            _row(id="f", status="paid"),
            _row(id="t", status="paid", kind="trial", price_rub=Decimal("0"), days=1),
        ]
        cp = [
            {"external_id": "b", "amount_kopecks": 30000, "days": 7},
            {"external_id": "c", "amount_kopecks": 30000, "days": 7},
            {"external_id": "d", "amount_kopecks": 30000, "days": 7},
            {"external_id": "f", "amount_kopecks": 30000, "days": 7},
            {"external_id": "t", "amount_kopecks": 0, "days": 1},
            {"external_id": "z", "amount_kopecks": 30000, "days": 7, "telegram_id": 5},
        ]
        got = {i["purchase_id"]: i["issue"] for i in reconcile_rows(fp, cp)}
        self.assertEqual(got, {
            "a": "paid_without_grant",
            "b": "grant_without_payment",
            "c": "amount_or_days_mismatch",
            "d": "granted_not_confirmed",
            "e": "pending",
            "z": "grant_unknown_to_focuspay",
        })


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class ReconciliationQueryTest(unittest.IsolatedAsyncioTestCase):
    async def test_purchase_lookup_binds_a_timestamp_not_an_interval(self):
        """Postgres infers `$1 - interval` as interval, so timestamptz >= interval 500s."""
        from routers import admin_vpn

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        before = datetime.now(timezone.utc)
        with patch.object(admin_vpn, "get_pool", AsyncMock(return_value=_Pool(conn))), \
             patch.object(admin_vpn, "_cp_or_502", AsyncMock(return_value={"grants": []})):
            out = await admin_vpn.vpn_reconciliation()
        sql, bound = conn.fetch.await_args.args
        self.assertNotIn("- interval", sql)
        self.assertIn("created_at >= $1", sql)
        self.assertIsInstance(bound, datetime)
        # Window is 30 days; the lookup reaches one extra day so an edge purchase still matches.
        age = before - bound
        self.assertGreater(age, timedelta(days=31) - timedelta(seconds=2))
        self.assertLess(age, timedelta(days=31) + timedelta(seconds=2))
        self.assertEqual(out["ok"], True)
        self.assertEqual(out["issues"], [])


class AdminUserTest(unittest.IsolatedAsyncioTestCase):
    async def test_user_card_survives_cp_outage(self):
        from routers import admin_vpn

        conn = AsyncMock()
        conn.fetch.return_value = []
        conn.fetchrow = AsyncMock(return_value=None)
        with patch.object(admin_vpn, "get_pool", AsyncMock(return_value=_Pool(conn))), \
             patch.object(vpn_billing, "user_status", AsyncMock(return_value={"exchanges": {"have": 2, "need": 10}})), \
             patch.object(vpn_billing, "cp_status", AsyncMock(return_value=None)), \
             patch.object(vpn_billing, "cp_request", AsyncMock(side_effect=vpn_billing.CPError(None, "ClientError"))):
            out = await admin_vpn.vpn_user(42)
        self.assertEqual(out["exchanges"], {"have": 2, "need": 10})
        self.assertEqual(out["devices"], [])
        self.assertFalse(out["subscription"]["active"])
        self.assertEqual(out["cp_error"], "ClientError")
        self.assertIsNone(out["username"])

    async def test_resolve_username_and_id(self):
        from fastapi import HTTPException
        from routers import admin_vpn

        self.assertEqual(admin_vpn.user_query("  @Nick_1 "), ("username", "Nick_1"))
        self.assertEqual(admin_vpn.user_query("77"), ("id", "77"))
        with self.assertRaises(ValueError):
            admin_vpn.user_query("@bad name")

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"user_id": 77, "username": "Nick_1", "first_name": "Ann"}])
        with patch.object(admin_vpn, "get_pool", AsyncMock(return_value=_Pool(conn))):
            found = await admin_vpn.vpn_resolve(q="@Nick_1")
        self.assertEqual(found["telegram_id"], 77)
        self.assertIn("LOWER(username)", conn.fetch.await_args.args[0])

        conn.fetchrow = AsyncMock(return_value={"user_id": 77, "username": "Nick_1", "first_name": "Ann"})
        with patch.object(admin_vpn, "get_pool", AsyncMock(return_value=_Pool(conn))):
            by_id = await admin_vpn.vpn_resolve(q="77")
        self.assertEqual(by_id["telegram_id"], 77)
        self.assertIn("user_id = $1", conn.fetchrow.await_args.args[0])

        conn.fetch = AsyncMock(return_value=[])
        with patch.object(admin_vpn, "get_pool", AsyncMock(return_value=_Pool(conn))):
            with self.assertRaises(HTTPException) as ctx:
                await admin_vpn.vpn_resolve(q="missing")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_revoke_unknown_device_is_404(self):
        from fastapi import HTTPException
        from routers import admin_vpn

        with patch.object(vpn_billing, "cp_request", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await admin_vpn.vpn_user_revoke_device(42, "dev-1")
        self.assertEqual(ctx.exception.status_code, 404)

        req = AsyncMock(return_value={})
        with patch.object(vpn_billing, "cp_request", req):
            self.assertEqual(await admin_vpn.vpn_user_revoke_device(42, "dev-1"), {"ok": True})
        req.assert_awaited_once_with("POST", "/v1/internal/telegram/devices/revoke", {"telegram_id": 42, "device_id": "dev-1"})

    async def test_trusted_toggle_rejects_non_bool_and_writes_flag(self):
        import json
        from fastapi import HTTPException
        from routers import admin_vpn

        with self.assertRaises(HTTPException) as ctx:
            await admin_vpn.vpn_user_set_trusted(42, {"trusted": 1})
        self.assertEqual(ctx.exception.status_code, 400)

        stored: dict[str, str] = {}

        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        conn = AsyncMock()
        conn.transaction = lambda: _Tx()

        async def execute(sql, *args):
            if len(args) == 2:
                stored[args[0]] = args[1]

        async def fetchrow(sql, key):
            if key not in stored:
                return None
            return {"value": json.loads(stored[key])}

        conn.execute = execute
        conn.fetchrow = fetchrow
        with patch.object(admin_vpn, "get_pool", AsyncMock(return_value=_Pool(conn))):
            opened = await admin_vpn.vpn_user_set_trusted(77, {"trusted": True})
            self.assertEqual(json.loads(stored[vpn_billing.TRUSTED_KEY]), [77])
            again = await admin_vpn.vpn_user_set_trusted(77, {"trusted": True})
            self.assertEqual(json.loads(stored[vpn_billing.TRUSTED_KEY]), [77])
            closed = await admin_vpn.vpn_user_set_trusted(77, {"trusted": False})
        self.assertEqual(opened, {"telegram_id": 77, "trusted": True})
        self.assertEqual(again, {"telegram_id": 77, "trusted": True})
        self.assertEqual(closed, {"telegram_id": 77, "trusted": False})
        self.assertEqual(json.loads(stored[vpn_billing.TRUSTED_KEY]), [])


_TIER = {
    "base_percent": 5.0,
    "step_percent": 5.0,
    "every_n": 5,
    "max_percent": 20.0,
}
_PURCHASE = "11111111-1111-1111-1111-111111111111"


def _reward_patches(*, exchanges: int = 0, cashback_pct: float = 5.0):
    return (
        patch("cashback_tier.count_completed_exchanges", AsyncMock(return_value=exchanges)),
        patch("cashback_tier.percent_for_completed_count", return_value=cashback_pct),
        patch("runtime_settings.partner_tier_global", return_value=dict(_TIER)),
    )


class VpnRewardTests(unittest.IsolatedAsyncioTestCase):
    async def test_referrer_ladder_starts_at_five_and_caps_at_twenty(self):
        cases = [
            (1, Decimal("49.50"), "5%"),
            (5, Decimal("99.00"), "10%"),
            (15, Decimal("198.00"), "20%"),
            (40, Decimal("198.00"), "20%"),
        ]
        for invited, referral, label in cases:
            conn = AsyncMock()
            conn.fetchval = AsyncMock(side_effect=[77, invited])
            count, pct, tier = _reward_patches()
            with count, pct, tier:
                await vpn_billing.accrue_vpn_rewards(conn, _row(status="granted", price_rub=Decimal("990.00")))
            cashback_sql, *cashback_args = conn.execute.await_args_list[0].args
            referral_sql, *referral_args = conn.execute.await_args_list[1].args
            self.assertIn("user_cashback_ledger", cashback_sql)
            self.assertIn("ON CONFLICT (order_id) DO NOTHING", cashback_sql)
            self.assertEqual(cashback_args[2], f"vpn:{_PURCHASE}")
            self.assertEqual(cashback_args[1], Decimal("49.50"))
            self.assertIn("user_referral_ledger", referral_sql)
            self.assertIn("ON CONFLICT (order_id) DO NOTHING", referral_sql)
            self.assertEqual(referral_args[0], 77)
            self.assertEqual(referral_args[1], referral, invited)
            self.assertEqual(referral_args[2], f"vpn:{_PURCHASE}")
            self.assertIn(label, referral_args[3])

    async def test_notice_only_when_referral_insert_is_new(self):
        fresh = AsyncMock()
        fresh.fetchval = AsyncMock(side_effect=[77, 1])
        fresh.execute = AsyncMock(side_effect=["INSERT 0 1", "INSERT 0 1"])
        count, pct, tier = _reward_patches()
        with count, pct, tier:
            notice = await vpn_billing.accrue_vpn_rewards(fresh, _row(status="granted", price_rub=Decimal("990.00")))
        self.assertEqual(notice["referrer_id"], 77)
        self.assertEqual(notice["amount_rub"], Decimal("49.50"))
        self.assertEqual(notice["percent"], 5.0)
        text = vpn_billing.vpn_referral_notice_text(
            amount=notice["amount_rub"], percent=notice["percent"], price=notice["price_rub"],
        )
        self.assertIn("Друг оплатил VPN", text)
        self.assertIn("49,50 ₽", text)
        self.assertIn("5% от 990,00 ₽", text)

        replay = AsyncMock()
        replay.fetchval = AsyncMock(side_effect=[77, 1])
        replay.execute = AsyncMock(side_effect=["INSERT 0 1", "INSERT 0 0"])
        count, pct, tier = _reward_patches()
        with count, pct, tier:
            self.assertIsNone(await vpn_billing.accrue_vpn_rewards(
                replay, _row(status="granted", price_rub=Decimal("990.00")),
            ))

    async def test_finalize_notifies_after_commit_and_survives_telegram_error(self):
        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        order = []
        conn = AsyncMock()
        conn.transaction = MagicMock(return_value=_Tx())

        async def fetchrow(sql, *args):
            paid = "SET status" in sql
            order.append("update" if paid else "lock")
            return _row(status="paid" if paid else "granted")

        conn.fetchrow = fetchrow

        async def confirm(*args, **kwargs):
            order.append("confirm")

        async def accrue(*args, **kwargs):
            order.append("accrue")
            return {"referrer_id": 77, "amount_rub": Decimal("49.50"), "percent": 5.0, "price_rub": Decimal("990.00")}

        async def notify(notice):
            order.append("notify")
            raise RuntimeError("telegram down")

        with patch.object(vpn_billing, "confirm_unified_hold", confirm), \
             patch.object(vpn_billing, "accrue_vpn_rewards", accrue), \
             patch.object(vpn_billing, "_notify_vpn_referrer", notify):
            row = await vpn_billing.finalize_granted(conn, _PURCHASE, None)
        self.assertEqual(row["status"], "paid")
        self.assertEqual(order, ["lock", "confirm", "accrue", "update", "notify"])

    async def test_cashback_follows_exchange_tier(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        pct = MagicMock(return_value=15.0)
        with patch("cashback_tier.count_completed_exchanges", AsyncMock(return_value=25)) as count, \
             patch("cashback_tier.percent_for_completed_count", pct), \
             patch("runtime_settings.partner_tier_global", return_value=dict(_TIER)):
            await vpn_billing.accrue_vpn_rewards(conn, _row(status="granted", price_rub=Decimal("990.00")))
        count.assert_awaited_once()
        pct.assert_called_once_with(25)
        self.assertEqual(len(conn.execute.await_args_list), 1)
        self.assertEqual(conn.execute.await_args.args[2], Decimal("148.50"))
        self.assertIn("15%", conn.execute.await_args.args[4])

    async def test_no_referrer_still_pays_cashback(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        count, pct, tier = _reward_patches()
        with count, pct, tier:
            await vpn_billing.accrue_vpn_rewards(conn, _row(status="granted", price_rub=Decimal("300.00")))
        self.assertEqual(len(conn.execute.await_args_list), 1)
        self.assertIn("user_cashback_ledger", conn.execute.await_args.args[0])
        self.assertEqual(conn.execute.await_args.args[2], Decimal("15.00"))

    async def test_self_referral_skips_referrer(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=42)
        count, pct, tier = _reward_patches()
        with count, pct, tier:
            await vpn_billing.accrue_vpn_rewards(conn, _row(status="granted", price_rub=Decimal("300.00")))
        self.assertEqual(len(conn.execute.await_args_list), 1)
        self.assertEqual(conn.fetchval.await_count, 1)

    async def test_trial_and_zero_price_accrue_nothing(self):
        for row in (_row(kind="trial", price_rub=Decimal("0")), _row(price_rub=Decimal("0"))):
            conn = AsyncMock()
            await vpn_billing.accrue_vpn_rewards(conn, row)
            conn.execute.assert_not_awaited()
            conn.fetchval.assert_not_awaited()

    async def test_finalize_accrues_after_confirm_before_paid(self):
        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        order = []
        conn = AsyncMock()
        conn.transaction = MagicMock(return_value=_Tx())

        async def fetchrow(sql, *args):
            paid = "SET status" in sql
            order.append("update" if paid else "lock")
            return _row(status="paid" if paid else "granted")

        conn.fetchrow = fetchrow

        async def confirm(*args, **kwargs):
            order.append("confirm")

        async def accrue(*args, **kwargs):
            order.append("accrue")

        with patch.object(vpn_billing, "confirm_unified_hold", confirm), \
             patch.object(vpn_billing, "accrue_vpn_rewards", accrue):
            row = await vpn_billing.finalize_granted(conn, _PURCHASE, None)
        self.assertEqual(row["status"], "paid")
        self.assertEqual(order, ["lock", "confirm", "accrue", "update"])


class VpnProfitTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_profit_is_sales_minus_vpn_rewards(self):
        from datetime import date

        from finance_pnl import fetch_vpn_revenue

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"purchases": 1, "revenue": 990})
        conn.fetchval = AsyncMock(side_effect=[198, 49.5])
        got = await fetch_vpn_revenue(conn, date(2026, 10, 1), date(2026, 10, 8))
        self.assertEqual(got["revenue_rub"], 990.0)
        self.assertEqual(got["referral_rub"], 198.0)
        self.assertEqual(got["cashback_rub"], 49.5)
        self.assertEqual(got["owner_profit_rub"], 742.5)
        referral_sql, cashback_sql = (c.args[0] for c in conn.fetchval.await_args_list)
        self.assertIn("user_referral_ledger", referral_sql)
        self.assertIn("user_cashback_ledger", cashback_sql)
        self.assertIn("vpn:%", referral_sql)
        sales_sql = conn.fetchrow.await_args.args[0]
        self.assertIn("'device'", sales_sql)

    async def test_missing_purchases_table_is_zero(self):
        import asyncpg
        from datetime import date

        from finance_pnl import fetch_vpn_revenue

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UndefinedTableError("vpn_purchases"))
        got = await fetch_vpn_revenue(conn, date(2026, 10, 1), date(2026, 10, 1))
        self.assertEqual(got["owner_profit_rub"], 0.0)
        self.assertEqual(got["purchases"], 0)


class DeviceSeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuses_without_live_subscription_before_hold(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with patch.object(vpn_billing, "cp_status", AsyncMock(return_value={"has_live": False})), \
             patch.object(vpn_billing, "start_device_purchase", AsyncMock()) as start:
            with self.assertRaises(vpn_billing.BillingError) as caught:
                await vpn_billing.purchase_device(conn, telegram_id=42, plan_code="month", idem_key="k" * 8)
        self.assertEqual(caught.exception.code, "subscription_required")
        start.assert_not_awaited()

    async def test_live_subscription_starts_the_saga(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        done = vpn_billing.Outcome(
            purchase_id="d1", status="paid", kind="device", plan_code="month", days=30, price_rub=Decimal("990"),
        )
        with patch.object(vpn_billing, "cp_status", AsyncMock(return_value={"has_live": True})), \
             patch.object(vpn_billing, "start_device_purchase", AsyncMock(return_value=(_row(kind="device", plan_code="month", days=30), False))) as start, \
             patch.object(vpn_billing, "drive", AsyncMock(return_value=done)) as drive:
            out = await vpn_billing.purchase_device(conn, telegram_id=42, plan_code="month", idem_key="k" * 8)
        start.assert_awaited_once()
        drive.assert_awaited_once()
        self.assertEqual(out.status, "paid")
        self.assertEqual(out.kind, "device")

    async def test_replay_does_not_ask_the_control_plane_again(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_row(kind="device", status="paid"))
        with patch.object(vpn_billing, "cp_status", AsyncMock()) as cp, \
             patch.object(vpn_billing, "start_device_purchase", AsyncMock(return_value=(_row(kind="device", status="paid"), True))), \
             patch.object(vpn_billing, "drive", AsyncMock()) as drive:
            out = await vpn_billing.purchase_device(conn, telegram_id=42, plan_code="month", idem_key="k" * 8)
        cp.assert_not_awaited()
        drive.assert_not_awaited()
        self.assertTrue(out.replay)

    def test_devices_limit_view(self):
        view = vpn_billing.devices_limit_view({
            "max_devices": 2, "base_devices": 1,
            "extra_slots": [{"plan_code": "month", "ends_at": "2026-11-07T00:00:00Z"}],
        })
        self.assertEqual(view["max_devices"], 2)
        self.assertEqual(view["extra_slots"][0]["plan_code"], "month")
        self.assertEqual(vpn_billing.devices_limit_view(None)["extra_slots"], [])

    def test_reconcile_counts_device_amount(self):
        fp = [_row(id="d", status="paid", kind="device", price_rub=Decimal("990.00"), days=30)]
        match = reconcile_rows(fp, [{"external_id": "d", "amount_kopecks": 99000, "days": 30}])
        self.assertEqual(match, [])
        mismatch = reconcile_rows(fp, [{"external_id": "d", "amount_kopecks": 30000, "days": 30}])
        self.assertEqual(mismatch[0]["issue"], "amount_or_days_mismatch")


if __name__ == "__main__":
    unittest.main()
