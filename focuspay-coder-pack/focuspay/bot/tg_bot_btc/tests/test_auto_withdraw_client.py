"""Авто-reserve вывода из бота через internal API."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class AutoWithdrawClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_auto_reserve_posts_withdrawal_id(self):
        from services.auto_withdraw_client import request_auto_reserve

        response = MagicMock()
        response.status = 200
        response.text = AsyncMock(return_value='{"ok":true,"outcome":"auto"}')
        response.json = AsyncMock(return_value={"ok": True, "outcome": "auto"})
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(
            "os.environ",
            {
                "EXCHANGE_API_URL": "http://backend.test:8000",
                "INTERNAL_API_SECRET": "secret",
            },
            clear=False,
        ), patch("services.auto_withdraw_client.INTERNAL_TOKEN", "secret"), patch(
            "services.auto_withdraw_client.EXCHANGE_API_URL",
            "http://backend.test:8000",
        ), patch(
            "services.auto_withdraw_client.aiohttp.ClientSession",
            return_value=session,
        ):
            data = await request_auto_reserve(75)

        self.assertEqual(data, {"ok": True, "outcome": "auto"})
        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        self.assertTrue(args[0].endswith("/api/internal/withdrawals/auto-reserve"))
        self.assertEqual(kwargs["json"], {"withdrawal_id": 75})
        self.assertEqual(kwargs["headers"]["X-Internal-Token"], "secret")


class TryBackendAutoReserveTests(unittest.IsolatedAsyncioTestCase):
    async def test_reject_raises_user_facing_error(self):
        from services.user_referral_withdraw import _try_backend_auto_reserve

        with patch(
            "services.auto_withdraw_client.request_auto_reserve",
            new=AsyncMock(return_value={"ok": True, "outcome": "reject"}),
        ):
            with self.assertRaises(ValueError) as ctx:
                await _try_backend_auto_reserve(
                    {
                        "id": 75,
                        "method": "crypto",
                        "source": "balance",
                        "status": "pending",
                    }
                )
        self.assertIn("поддержку", str(ctx.exception))

    async def test_reject_wallet_reason_passes_through(self):
        from services.user_referral_withdraw import _try_backend_auto_reserve

        with patch(
            "services.auto_withdraw_client.request_auto_reserve",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "outcome": "reject",
                    "reason": "Неверный формат адреса Litecoin (ожидается ltc1…, L… или M…)",
                }
            ),
        ):
            with self.assertRaises(ValueError) as ctx:
                await _try_backend_auto_reserve(
                    {
                        "id": 89,
                        "method": "crypto",
                        "source": "balance",
                        "status": "pending",
                    }
                )
        self.assertIn("Litecoin", str(ctx.exception))

    async def test_auto_refreshes_row(self):
        from services.user_referral_withdraw import _try_backend_auto_reserve

        refreshed = {
            "id": 75,
            "status": "reserved",
            "method": "crypto",
            "source": "balance",
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=refreshed)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        with patch(
            "services.auto_withdraw_client.request_auto_reserve",
            new=AsyncMock(return_value={"ok": True, "outcome": "auto"}),
        ), patch(
            "services.user_referral_withdraw.get_pool",
            new=AsyncMock(return_value=pool),
        ):
            out = await _try_backend_auto_reserve(
                {"id": 75, "status": "pending", "method": "crypto"}
            )
        self.assertEqual(out["status"], "reserved")


if __name__ == "__main__":
    unittest.main()
