"""Ручные заявки оператора: покупатель, валидация."""
import re
import unittest
from decimal import Decimal
from pathlib import Path

import asyncpg
from fastapi import HTTPException
from pydantic import ValidationError

from routers.operator import (
    CreateOrderRequest,
    ManualPaidRequest,
    _manual_buy_overpay,
    _manual_buy_pricing,
    _operator_order_exception_detail,
    _order_out,
    _operator_has_role,
    _raise_manual_payout_error,
    _require_order_buyer,
    _role_split_update_query,
)

_OPERATOR_PY = Path(__file__).resolve().parent.parent / "routers" / "operator.py"


class CreateOrderRequestTests(unittest.TestCase):
    def test_buyer_user_id_required(self):
        with self.assertRaises(ValidationError):
            CreateOrderRequest(
                crypto="usdt",
                tx_hash="abc123def4567890",
                fiat_amount=10_000,
                manual_spread_pct="20.00",
                received_fiat_amount="10000.00",
            )

    def test_exchange_discount_id_optional(self):
        req = CreateOrderRequest(
            crypto="usdt",
            buyer_user_id=123456789,
            tx_hash="abc123def4567890",
            fiat_amount=10_000,
            manual_spread_pct="20.00",
            received_fiat_amount="10000.00",
            exchange_discount_id=42,
        )
        self.assertEqual(req.exchange_discount_id, 42)

    def test_apply_balance_optional(self):
        req = CreateOrderRequest(
            crypto="usdt",
            buyer_user_id=123456789,
            tx_hash="abc123def4567890",
            fiat_amount=10_000,
            manual_spread_pct="20.00",
            received_fiat_amount="10000.00",
        )
        self.assertIsNone(req.apply_balance)
        req_on = CreateOrderRequest(
            crypto="usdt",
            buyer_user_id=123456789,
            tx_hash="abc123def4567890",
            fiat_amount=10_000,
            manual_spread_pct="20.00",
            received_fiat_amount="10000.00",
            apply_balance=True,
        )
        self.assertTrue(req_on.apply_balance)
        req_off = CreateOrderRequest(
            crypto="usdt",
            buyer_user_id=123456789,
            tx_hash="abc123def4567890",
            fiat_amount=10_000,
            manual_spread_pct="20.00",
            received_fiat_amount="10000.00",
            apply_balance=False,
        )
        self.assertFalse(req_off.apply_balance)

    def test_buy_tx_hash_is_role_specific(self):
        req = CreateOrderRequest(
            crypto="usdt",
            buyer_user_id=123456789,
            fiat_amount=10_000,
            manual_spread_pct="20.00",
            received_fiat_amount="10000.00",
        )
        self.assertIsNone(req.tx_hash)

    def test_buy_minimal_ok(self):
        req = CreateOrderRequest(
            crypto="usdt",
            buyer_user_id=123456789,
            tx_hash="abc123def4567890",
            fiat_amount=10_000,
            manual_spread_pct="20.00",
            received_fiat_amount="10000.00",
        )
        self.assertEqual(req.buyer_user_id, 123456789)
        self.assertEqual(req.order_type, "buy")
        self.assertEqual(req.tx_hash, "abc123def4567890")

    def test_buy_wallet_can_be_recorded_without_tx_hash_for_handoff(self):
        req = CreateOrderRequest(
            crypto="usdt",
            buyer_user_id=123456789,
            wallet_address="TXyz",
            fiat_amount=10_000,
            manual_spread_pct="20.00",
            received_fiat_amount="10000.00",
        )
        self.assertEqual(req.wallet_address, "TXyz")

    def test_manual_buy_spread_accepts_bounds(self):
        for spread in ("14.00", "25.00"):
            req = CreateOrderRequest(
                crypto="usdt",
                buyer_user_id=123456789,
                fiat_amount=10_000,
                manual_spread_pct=spread,
                received_fiat_amount="10000.00",
            )
            self.assertEqual(str(req.manual_spread_pct), spread)

    def test_manual_buy_rejects_invalid_money_and_spread(self):
        base = {
            "crypto": "usdt",
            "buyer_user_id": 123456789,
            "fiat_amount": 10_000,
            "manual_spread_pct": "20.00",
            "received_fiat_amount": "10000.00",
        }
        for key, value in (
            ("manual_spread_pct", "13.99"),
            ("manual_spread_pct", "25.01"),
            ("manual_spread_pct", "20.001"),
            ("manual_spread_pct", "NaN"),
            ("received_fiat_amount", "Infinity"),
            ("fiat_amount", float("nan")),
            ("crypto_amount", float("inf")),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                CreateOrderRequest(**(base | {key: value}))

    def test_manual_buy_requires_pricing_and_received_amount(self):
        base = {
            "crypto": "usdt",
            "buyer_user_id": 123456789,
            "fiat_amount": 10_000,
        }
        with self.assertRaises(ValidationError):
            CreateOrderRequest(**base, received_fiat_amount="10000.00")
        with self.assertRaises(ValidationError):
            CreateOrderRequest(**base, manual_spread_pct="20.00")

    def test_manual_buy_pricing_and_overpay_use_server_rounding(self):
        crypto, fiat, rate = _manual_buy_pricing(
            market_rate=100,
            fiat_amount=2800,
            crypto_amount=None,
            spread_pct=Decimal("20.00"),
        )
        overpay, credit = _manual_buy_overpay(fiat, Decimal("3000.00"), Decimal("20.00"))
        self.assertEqual(rate, Decimal("120.00000000"))
        self.assertEqual(fiat, Decimal("2800.00"))
        self.assertEqual(crypto, Decimal("23.33333333"))
        self.assertEqual(overpay, Decimal("200.00"))
        self.assertEqual(credit, Decimal("160.00"))

    def test_sell_does_not_require_manual_buy_fields(self):
        req = CreateOrderRequest(
            order_type="sell",
            crypto="usdt",
            buyer_user_id=123456789,
            fiat_amount=10_000,
            requisites="СБП +79990000000",
        )
        self.assertEqual(req.order_type, "sell")

    def test_manual_buy_spread_limits(self):
        base = {
            "crypto": "usdt",
            "buyer_user_id": 123456789,
            "fiat_amount": 10_000,
            "received_fiat_amount": "10000.00",
        }
        self.assertEqual(CreateOrderRequest(**base, manual_spread_pct="14.00").manual_spread_pct, 14)
        self.assertEqual(CreateOrderRequest(**base, manual_spread_pct="25.00").manual_spread_pct, 25)
        with self.assertRaises(ValidationError):
            CreateOrderRequest(**base, manual_spread_pct="13.99")
        with self.assertRaises(ValidationError):
            CreateOrderRequest(**base, manual_spread_pct="25.01")
        with self.assertRaises(ValidationError):
            CreateOrderRequest(**base, manual_spread_pct="20.001")

    def test_manual_buy_requires_received_amount_and_spread(self):
        base = {"crypto": "usdt", "buyer_user_id": 123456789, "fiat_amount": 10_000}
        with self.assertRaises(ValidationError):
            CreateOrderRequest(**base, received_fiat_amount="10000.00")
        with self.assertRaises(ValidationError):
            CreateOrderRequest(**base, manual_spread_pct="20.00")

    def test_sell_qr_ok(self):
        req = CreateOrderRequest(
            order_type="sell_qr",
            crypto="usdt",
            buyer_user_id=1,
            crypto_received=100,
            fiat_amount=7000,
        )
        self.assertEqual(req.order_type, "sell_qr")


class ManualPaidRequestTests(unittest.TestCase):
    def test_manual_buy_overpay_calculation(self):
        overpay, credit = _manual_buy_overpay(2800, 3000, Decimal("20.00"))
        self.assertEqual(overpay, Decimal("200.00"))
        self.assertEqual(credit, Decimal("160.00"))

    def test_manual_buy_overpay_is_zero_without_excess(self):
        self.assertEqual(_manual_buy_overpay(2800, 2800, Decimal("20.00")), (Decimal("0"), Decimal("0.00")))
        self.assertEqual(_manual_buy_overpay(2800, 2700, Decimal("20.00")), (Decimal("0"), Decimal("0.00")))

    def test_manual_buy_pricing_uses_individual_spread(self):
        crypto, fiat, rate = _manual_buy_pricing(
            market_rate=100,
            fiat_amount=None,
            crypto_amount=10,
            spread_pct=Decimal("20.00"),
        )
        self.assertEqual(rate, Decimal("120.00000000"))
        self.assertEqual(fiat, Decimal("1200"))
        self.assertEqual(crypto, Decimal("10"))

    def test_tx_strip(self):
        req = ManualPaidRequest(tx_hash="  abc123def4567890  ")
        self.assertEqual(req.tx_hash, "abc123def4567890")

    def test_empty_tx_rejected(self):
        with self.assertRaises(ValidationError):
            ManualPaidRequest(tx_hash="   ")


class ManualPayoutErrorTests(unittest.TestCase):
    def test_duplicate_tx_hash_message(self):
        with self.assertRaises(HTTPException) as ctx:
            _raise_manual_payout_error("duplicate_tx_hash:OP123ABC")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("OP123ABC", ctx.exception.detail)


def _sql_placeholders(sql: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\$(\d+)", sql)})


class RoleSplitUpdateQueryTests(unittest.TestCase):
    def _assert_dense(self, sql: str, values: list) -> None:
        ids = _sql_placeholders(sql)
        self.assertEqual(ids, list(range(1, len(values) + 1)), msg=sql)
        self.assertEqual(values[-1], "OPTEST")
        self.assertIn(f"WHERE order_id = ${len(values)}", sql)

    def test_finance_required_uses_dollar_one(self):
        """Prod 500: unused $1 → asyncpg IndeterminateDatatypeError on finalize."""
        sql, values = _role_split_update_query(
            "OPTEST",
            finance_operator_id=2,
            required=True,
        )
        self._assert_dense(sql, values)
        self.assertEqual(values, [2, "OPTEST"])
        self.assertIn("finance_operator_id = $1", sql)
        self.assertIn("payroll_split_required = TRUE", sql)
        self.assertIn("WHERE order_id = $2", sql)

    def test_required_only(self):
        sql, values = _role_split_update_query("OPTEST", required=True)
        self._assert_dense(sql, values)
        self.assertEqual(values, ["OPTEST"])

    def test_intake_and_source(self):
        sql, values = _role_split_update_query(
            "OPTEST",
            intake_operator_id=7,
            finance_operator_id=9,
            source="manual_operator",
            required=True,
        )
        self._assert_dense(sql, values)
        self.assertEqual(values, ["manual_operator", 7, 9, "OPTEST"])
        self.assertIn("order_source = $1", sql)
        self.assertIn("intake_operator_id = COALESCE(intake_operator_id, $2)", sql)
        self.assertIn("finance_operator_id = $3", sql)
        self.assertIn("WHERE order_id = $4", sql)


class OperatorOrderExceptionDetailTests(unittest.TestCase):
    def test_partner_ledger_check_violation(self):
        exc = asyncpg.CheckViolationError(
            "new row violates check constraint partner_ledger_type_check"
        )
        code, detail = _operator_order_exception_detail(exc)
        self.assertEqual(code, 503)
        self.assertIn("partner_ledger", detail)

    def test_duplicate_tx_unique_violation(self):
        exc = asyncpg.UniqueViolationError(
            'duplicate key value violates unique constraint "idx_orders_payout_tx_hash_unique"'
        )
        code, detail = _operator_order_exception_detail(exc)
        self.assertEqual(code, 409)
        self.assertIn("hash", detail.lower())


class BuyerHelperTests(unittest.TestCase):
    def test_operator_role_fallback_is_client(self):
        self.assertTrue(_operator_has_role({"operator_role": "client"}, "client"))
        self.assertFalse(_operator_has_role({"operator_role": "client"}, "finance"))

    def test_operator_roles_allow_finance(self):
        self.assertTrue(_operator_has_role({"operator_roles": ["client", "finance"]}, "finance"))

    def test_require_order_buyer_missing(self):
        with self.assertRaises(HTTPException) as ctx:
            _require_order_buyer({"user_id": None})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_require_order_buyer_ok(self):
        self.assertEqual(_require_order_buyer({"user_id": 42}), 42)

    def test_order_out_username_prefix(self):
        out = _order_out(
            {
                "order_id": "OP1",
                "buyer_username": "alice",
                "created_at": None,
                "updated_at": None,
            }
        )
        self.assertEqual(out["buyer_username"], "@alice")


class OperatorBuyInsertSqlTests(unittest.TestCase):
    def test_buy_insert_wallet_requisites_use_explicit_casts(self):
        """Regression: same param for text + varchar causes asyncpg AmbiguousParameterError."""
        source = _OPERATOR_PY.read_text(encoding="utf-8")
        self.assertIn("$7::text", source)
        self.assertIn("$7::varchar", source)
        self.assertNotRegex(
            source,
            re.compile(r"\$6,\s*\$7,\s*\$8,\s*\$7,"),
            msg="buy INSERT must not reuse bare $7 for wallet_address and requisites",
        )

    def test_buy_insert_persists_manual_buy_financial_fields(self):
        source = _OPERATOR_PY.read_text(encoding="utf-8")
        buy_impl = source.split("async def _create_operator_order_impl", 1)[1]
        buy_block = buy_impl.split('if body.order_type == "sell":', 1)[0]
        self.assertIn("'manual_operator'", buy_block)
        self.assertIn(
            "manual_spread_pct, received_fiat_amount, overpay_rub, overpay_credit_rub",
            buy_block,
        )
        self.assertIn("$17, $18, $19, $20", buy_block)

    def test_buy_insert_persists_payout_tx_hash_before_finalize(self):
        """Hash must be written on primary INSERT so a timed-out finalize still keeps it."""
        source = _OPERATOR_PY.read_text(encoding="utf-8")
        buy_impl = source.split("async def _create_operator_order_impl", 1)[1]
        buy_block = buy_impl.split("if body.order_type == \"sell\":", 1)[0]
        self.assertIn("payout_tx_hash", buy_block)
        self.assertIn("payout_tx_hash = _normalize_operator_tx", buy_block)
        # _ensure_payout_tx_hash_available удалена — проверка дублей перенесена в bot_status_bridge
        insert_pos = buy_block.find("INSERT INTO orders")
        finalize_pos = buy_block.find("_finalize_manual_buy_paid")
        hash_col_pos = buy_block.find("payout_tx_hash,", insert_pos)
        self.assertGreater(insert_pos, 0)
        self.assertGreater(finalize_pos, insert_pos)
        self.assertGreater(hash_col_pos, insert_pos)
        self.assertLess(hash_col_pos, finalize_pos)

    def test_manual_buy_uses_individual_spread_in_economics_snapshot(self):
        source = _OPERATOR_PY.read_text(encoding="utf-8")
        buy_impl = source.split("async def _create_operator_order_impl", 1)[1]
        buy_block = buy_impl.split('if body.order_type == "sell":', 1)[0]
        self.assertIn("buy_markup_override=1 + float(manual_spread_pct) / 100", buy_block)
        self.assertIn("economics_snapshot", buy_block)
        self.assertIn("$21::jsonb", buy_block)

    def test_manual_sell_paths_persist_economics_snapshot(self):
        source = _OPERATOR_PY.read_text(encoding="utf-8")
        buy_impl = source.split("async def _create_operator_order_impl", 1)[1]
        sell_block, qr_block = buy_impl.split("# sell_qr", 1)
        self.assertIn("build_economics_snapshot", sell_block)
        self.assertIn("$10::jsonb", sell_block)
        self.assertIn("build_economics_snapshot", qr_block)
        self.assertIn("$11::jsonb", qr_block)

    def test_rollback_clears_payout_tx_hash(self):
        source = _OPERATOR_PY.read_text(encoding="utf-8")
        rollback = source.split("async def _rollback_orphan_manual_buy", 1)[1]
        rollback = rollback.split("async def _finalize_manual_buy_paid", 1)[0]
        self.assertIn("payout_tx_hash = NULL", rollback)

    def test_dual_role_operator_is_finance_for_hash(self):
        op = {"operator_role": "client", "operator_roles": ["client", "finance"]}
        self.assertTrue(_operator_has_role(op, "finance"))
        self.assertTrue(_operator_has_role(op, "client"))


if __name__ == "__main__":
    unittest.main()
