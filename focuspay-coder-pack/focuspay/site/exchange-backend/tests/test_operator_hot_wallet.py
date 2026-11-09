"""GET /operator/hot-wallet: 403 без грейда и без смены, адрес только старшему на смене."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from hot_wallet_runway import assemble_runway
from routers.operator import operator_hot_wallet


def _pool(shift_row):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=shift_row)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def get_pool():
        return pool

    return get_pool, conn


def _finance(grade: str):
    return {
        "id": 4,
        "operator_roles": ["finance"],
        "operator_role": "finance",
    }, {"finance": grade}


class OperatorHotWalletAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_junior_finance_forbidden(self):
        op, grades = _finance("junior")
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value=grades),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await operator_hot_wallet(op=op)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("старший", ctx.exception.detail)

    async def test_client_senior_forbidden(self):
        op = {"id": 5, "operator_roles": ["client"], "operator_role": "client"}
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value={"client": "senior"}),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await operator_hot_wallet(op=op)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_senior_off_shift_forbidden(self):
        op, grades = _finance("senior")
        get_pool, _conn = _pool(None)
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value=grades),
        ), patch("routers.operator.get_pool", new=get_pool):
            with self.assertRaises(HTTPException) as ctx:
                await operator_hot_wallet(op=op)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("смену", str(ctx.exception.detail))

    async def test_senior_on_shift_gets_hours_and_deposit_address(self):
        op, grades = _finance("senior")
        get_pool, _conn = _pool({"id": 9, "operator_id": 4})
        runway = assemble_runway(
            coins=[{"coin": "btc", "spendable": 0.03, "rate_rub": 1_000_000}],
            outflow={"btc": {"buy_crypto": 0.07, "buy_rub": 70_000, "withdraw_rub": 0, "deals": 2}},
            min_hot_balance_rub=50_000,
            signer_ok=True,
        )
        with patch(
            "permissions.load_operator_role_grades",
            new=AsyncMock(return_value=grades),
        ), patch(
            "routers.operator.get_pool", new=get_pool
        ), patch(
            "hot_wallet_runway.build_hot_wallet_runway",
            new=AsyncMock(return_value=runway),
        ), patch(
            "signer_client.fetch_signer_deposit_addresses",
            new=AsyncMock(return_value={"addresses": {"btc": "bc1qexample", "ltc": "ltc1qexample"}}),
        ):
            result = await operator_hot_wallet(op=op)
        btc = result["coins"][0]
        ltc = result["coins"][1]
        self.assertEqual(btc["hours_phrase"], "хватит ≈ 72 ч")
        self.assertEqual(btc["deposit_address"], "bc1qexample")
        self.assertEqual(ltc["deposit_address"], "ltc1qexample")


if __name__ == "__main__":
    unittest.main()
