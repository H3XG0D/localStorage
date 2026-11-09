"""SELL: постоянный адрес приёма, «Я оплатил», гейт матчера по приходу крипты."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]

BTC_ADDRESS = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"


def sell_row(**over):
    row = {
        "order_id": "S1",
        "direction": "sell",
        "status": "OPERATOR_PENDING",
        "crypto": "BTC",
        "crypto_amount": 0.05,
        "fiat_amount": 400000,
        "requisites": "2202200112345678",
        "crypto_confirmed_at": None,
    }
    row.update(over)
    return row


class DepositAddressTests(unittest.TestCase):
    def _payment(self, settings_patch, row=None):
        import order_service

        with patch("runtime_settings.get_settings_sync", return_value=settings_patch):
            return order_service._sell_payment_for_row(row or sell_row())

    def test_configured_btc_address_is_handed_out(self):
        payment = self._payment({"sell_deposit_address_btc": BTC_ADDRESS})
        self.assertEqual(payment["type"], "deposit")
        self.assertEqual(payment["deposit_wallet"], BTC_ADDRESS)

    def test_empty_setting_falls_back_to_operator(self):
        payment = self._payment({"sell_deposit_address_btc": "   "})
        self.assertEqual(payment["type"], "operator")
        self.assertNotIn("deposit_wallet", payment)

    def test_other_coins_stay_on_operator(self):
        payment = self._payment(
            {"sell_deposit_address_btc": BTC_ADDRESS}, sell_row(crypto="USDT_TRC20")
        )
        self.assertEqual(payment["type"], "operator")

    def test_accessor_reads_per_coin_key(self):
        from runtime_settings import sell_deposit_address

        with patch(
            "runtime_settings.get_settings_sync",
            return_value={"sell_deposit_address_btc": BTC_ADDRESS},
        ):
            self.assertEqual(sell_deposit_address("BTC"), BTC_ADDRESS)
            self.assertIsNone(sell_deposit_address("ltc"))


class AddressValidationTests(unittest.TestCase):
    def _patch(self, addr):
        from routers.admin_pricing import PricingSettingsPatch

        return PricingSettingsPatch(sell_deposit_address_btc=addr)

    def test_bech32_and_legacy_pass(self):
        self.assertEqual(self._patch(BTC_ADDRESS).sell_deposit_address_btc, BTC_ADDRESS)
        legacy = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
        self.assertEqual(self._patch(legacy).sell_deposit_address_btc, legacy)

    def test_blank_clears_the_setting(self):
        self.assertEqual(self._patch("  ").sell_deposit_address_btc, "")

    def test_garbage_rejected(self):
        with self.assertRaises(Exception):
            self._patch("не адрес")

    def test_key_is_persisted(self):
        from runtime_settings import _SETTING_KEYS, merge_settings

        self.assertIn("sell_deposit_address_btc", _SETTING_KEYS)
        self.assertEqual(merge_settings(None)["sell_deposit_address_btc"], "")


class MatcherGateTests(unittest.TestCase):
    def test_candidates_require_confirmed_crypto(self):
        src = (ROOT / "payout_requisite_matcher.py").read_text()
        self.assertIn("o.crypto_confirmed_at IS NOT NULL", src)


class CryptoReceivedTests(unittest.IsolatedAsyncioTestCase):
    def _conn(self, row, updated=None):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[row, updated] if updated is not None else [row])
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        return conn

    def _pool(self, conn):
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        async def get_pool():
            return pool

        return get_pool

    async def _call(self, row, updated=None, op_id=5, *, with_requisites_perm=False, triangle=None):
        from permissions import PERM_PAYOUT_REQUISITES
        from routers import operator as mod

        conn = self._conn(row, updated)
        perms = {PERM_PAYOUT_REQUISITES} if with_requisites_perm else set()
        op = {"id": op_id, "operator_roles": ["finance"], "permissions": perms}
        triangle_ret = triangle or (
            {"id": 42, "status": "QUEUED"},
            None,
            None,
            True,
        )
        with patch("routers.operator.get_pool", new=self._pool(conn)), patch(
            "routers.operator._require_active_shift", new=AsyncMock()
        ), patch("routers.operator.require_operator_role", side_effect=lambda o, r: o), patch(
            "permissions.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        ), patch(
            "routers.operator_payout_requisites.ensure_triangle_from_sell",
            new=AsyncMock(return_value=triangle_ret),
        ) as ensure:
            out = await mod.confirm_sell_crypto_received(order_id="S1", op=op)
        return out, conn, ensure

    async def test_sets_timestamp_once(self):
        out, conn, ensure = await self._call(
            sell_row(), sell_row(crypto_confirmed_at="2026-09-05T10:00:00+00:00")
        )
        self.assertFalse(out["already_confirmed"])
        sql = conn.fetchrow.await_args_list[1].args[0]
        self.assertIn("crypto_confirmed_at = now()", sql)
        self.assertIn("crypto_confirmed_at IS NULL", sql)
        ensure.assert_not_called()
        self.assertNotIn("triangle_requisite", out)

    async def test_second_call_is_idempotent(self):
        out, conn, ensure = await self._call(
            sell_row(crypto_confirmed_at="2026-09-05T10:00:00+00:00")
        )
        self.assertTrue(out["already_confirmed"])
        self.assertEqual(conn.fetchrow.await_count, 1)
        ensure.assert_not_called()

    async def test_auto_triangle_when_has_requisites_perm(self):
        out, _conn, ensure = await self._call(
            sell_row(),
            sell_row(crypto_confirmed_at="2026-09-05T10:00:00+00:00"),
            with_requisites_perm=True,
        )
        ensure.assert_awaited_once()
        self.assertEqual(
            out["triangle_requisite"],
            {"id": 42, "status": "QUEUED", "created": True},
        )

    async def test_buy_order_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sell_row(direction="buy"))
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_terminal_status_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sell_row(status="PAID"))
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_foreign_finance_operator_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sell_row(finance_operator_id=9))
        self.assertEqual(ctx.exception.status_code, 403)


class WiringTests(unittest.TestCase):
    def test_confirm_paid_accepts_operator_pending_sell(self):
        src = (ROOT / "order_service.py").read_text()
        self.assertIn('("CREATED", "OPERATOR_PENDING") if row_raw["direction"] == "sell"', src)

    def test_client_can_download_payout_receipt(self):
        src = (ROOT / "routers" / "web_orders.py").read_text()
        self.assertIn('@router.get("/orders/{order_id}/payout-receipt")', src)
        self.assertIn("payout_requisite_allocations", src)

    def test_operator_can_attach_receipt_for_client(self):
        src = (ROOT / "routers" / "operator_payout_requisites.py").read_text()
        self.assertIn(
            '@router.post("/payout-requisites/{requisite_id}/allocations/{allocation_id}/receipt")',
            src,
        )

    def test_client_can_confirm_payout_receipt(self):
        src = (ROOT / "routers" / "web_orders.py").read_text()
        self.assertIn('@router.post("/orders/{order_id}/payout-receipt/confirm")', src)

    def test_payout_receipt_state_wired(self):
        src = (ROOT / "order_service.py").read_text()
        self.assertIn("payout_receipt_confirmed", src)
        self.assertIn("payout_receipt_available", src)

    def test_migration_declares_column(self):
        sql = (
            ROOT.parents[1]
            / "bot"
            / "tg_bot_btc"
            / "migrations"
            / "add_order_crypto_confirmed.sql"
        ).read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS crypto_confirmed_at", sql)


if __name__ == "__main__":
    unittest.main()
