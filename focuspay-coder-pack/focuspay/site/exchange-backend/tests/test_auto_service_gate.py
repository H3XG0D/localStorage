"""Tests for auto_service_gate (shadow / eligibility)."""
import unittest
from unittest.mock import AsyncMock, patch

from auto_service_gate import NoShiftDecision, resolve_no_shift_access


class AutoServiceGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_on_shift_allows(self):
        with patch(
            "operator_availability.has_operator_on_shift",
            new=AsyncMock(return_value=True),
        ):
            d = await resolve_no_shift_access(1, "buy", 5000)
        self.assertEqual(d.kind, "allow_shift")

    async def test_shadow_blocks_but_logs_would_auto(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.execute = AsyncMock()

        with patch(
            "operator_availability.has_operator_on_shift",
            new=AsyncMock(return_value=False),
        ), patch(
            "auto_service_gate.auto_no_shift_enabled",
            return_value=True,
        ), patch(
            "auto_service_gate.auto_no_shift_shadow_mode",
            return_value=True,
        ), patch(
            "auto_service_gate.auto_whitelist_user_ids",
            return_value=set(),
        ), patch(
            "auto_service_gate.auto_no_shift_min_buy_paid",
            return_value=3,
        ), patch(
            "auto_service_gate.auto_no_shift_max_rub",
            return_value=10_000,
        ), patch(
            "auto_service_gate.buy_paid_count",
            new=AsyncMock(return_value=10),
        ), patch(
            "auto_payout_guard.signer_circuit_closed",
            new=AsyncMock(return_value=True),
        ), patch(
            "auto_service_gate.buy_coin_fits",
            new=AsyncMock(return_value=None),
        ):
            d = await resolve_no_shift_access(
                1, "buy", 4000, conn=conn, crypto="btc", crypto_amount=0.001
            )
        self.assertEqual(d.kind, "block")
        self.assertEqual(d.reason, "shadow_would_auto")
        conn.execute.assert_called()

    def _eligible(self):
        return (
            patch(
                "operator_availability.has_operator_on_shift",
                new=AsyncMock(return_value=False),
            ),
            patch("auto_service_gate.auto_no_shift_enabled", return_value=True),
            patch("auto_service_gate.auto_no_shift_shadow_mode", return_value=False),
            patch("auto_service_gate.auto_whitelist_user_ids", return_value=set()),
            patch("auto_service_gate.auto_no_shift_min_buy_paid", return_value=3),
            patch("auto_service_gate.auto_no_shift_max_rub", return_value=10_000),
            patch("auto_service_gate.buy_paid_count", new=AsyncMock(return_value=10)),
            patch(
                "auto_payout_guard.signer_circuit_closed",
                new=AsyncMock(return_value=True),
            ),
        )

    async def test_blocks_when_coin_balance_is_short(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.execute = AsyncMock()
        patches = self._eligible()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch(
            "auto_payout_guard.coin_spendable",
            new=AsyncMock(return_value=0.001),
        ), patch(
            "auto_payout_guard.reserved_buy_crypto",
            new=AsyncMock(return_value=0.0008),
        ):
            d = await resolve_no_shift_access(
                1, "buy", 4000, conn=conn, crypto="BTC", crypto_amount=0.001
            )
        self.assertEqual(d.kind, "block")
        self.assertEqual(d.reason, "coin_short")
        self.assertEqual(d.coin, "btc")
        self.assertAlmostEqual(d.spendable or 0, 0.001)
        self.assertAlmostEqual(d.reserved or 0, 0.0008)

    async def test_allows_when_coin_covers_the_order_and_open_buys(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.execute = AsyncMock()
        patches = self._eligible()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch(
            "auto_payout_guard.coin_spendable",
            new=AsyncMock(return_value=0.01),
        ), patch(
            "auto_payout_guard.reserved_buy_crypto",
            new=AsyncMock(return_value=0.004),
        ):
            d = await resolve_no_shift_access(
                1, "buy", 4000, conn=conn, crypto="LTC", crypto_amount=0.005
            )
        self.assertEqual(d.kind, "allow_auto")

    async def test_blocks_when_coin_balance_cannot_be_read(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.execute = AsyncMock()
        patches = self._eligible()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patch(
            "auto_payout_guard.coin_spendable",
            new=AsyncMock(return_value=None),
        ):
            d = await resolve_no_shift_access(
                1, "buy", 4000, conn=conn, crypto="btc", crypto_amount=0.001
            )
        self.assertEqual(d.kind, "block")
        self.assertEqual(d.reason, "coin_unknown")

    async def test_on_shift_does_not_look_at_the_coin(self):
        with patch(
            "operator_availability.has_operator_on_shift",
            new=AsyncMock(return_value=True),
        ), patch(
            "auto_service_gate.buy_coin_fits",
            new=AsyncMock(return_value=None),
        ) as fits:
            d = await resolve_no_shift_access(
                1, "buy", 5000, crypto="btc", crypto_amount=1
            )
        self.assertEqual(d.kind, "allow_shift")
        fits.assert_not_called()


class CoinSpendableTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_coin_is_zero(self):
        from auto_payout_guard import coin_spendable

        with patch("signer_client.signer_configured", return_value=True), patch(
            "signer_client.fetch_signer_balances",
            new=AsyncMock(return_value={"ok": True, "coins": {"btc": {"spendable": 0.01}}}),
        ):
            self.assertEqual(await coin_spendable("USDT_TRC20"), 0.0)

    async def test_signer_down_is_unknown(self):
        from auto_payout_guard import coin_spendable

        with patch("signer_client.signer_configured", return_value=True), patch(
            "signer_client.fetch_signer_balances",
            new=AsyncMock(return_value={"ok": False, "coins": {}}),
        ):
            self.assertIsNone(await coin_spendable("btc"))


if __name__ == "__main__":
    unittest.main()
