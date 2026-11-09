"""API реквизитов выплат: RBAC, бронь, закрытие чека, долив, откаты."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from permissions import PERM_PAYOUT_REQUISITES, PERM_PAYOUT_REQUISITES_CONFIRM, attach_operator_permissions_sync

ROOT = Path(__file__).resolve().parents[1]

MOD = "routers.operator_payout_requisites"


def _mod():
    from routers import operator_payout_requisites as mod

    return mod


def _create_body(**over):
    kwargs = dict(
        method="card",
        requisites="2202200112345678",
        amount_rub=Decimal("10000"),
        bank="Сбербанк",
        holder_name="Иван Иванов",
    )
    kwargs.update(over)
    return _mod().RequisiteCreateBody(**kwargs)


def _finance_op(op_id: int = 5):
    return attach_operator_permissions_sync(
        {
            "id": op_id,
            "username": "fin",
            "display_name": "Финанс",
            "operator_roles": ["finance"],
            "operator_role": "finance",
        }
    )


def _finance_senior_op(op_id: int = 5):
    return attach_operator_permissions_sync(
        {
            "id": op_id,
            "username": "fin-senior",
            "display_name": "Старший финанс",
            "operator_roles": ["finance"],
            "operator_role": "finance",
            "role_grades": {"finance": "senior"},
        }
    )


def _client_op(op_id: int = 6):
    return attach_operator_permissions_sync(
        {
            "id": op_id,
            "username": "cli",
            "display_name": "Клиентский",
            "operator_roles": ["client"],
            "operator_role": "client",
        }
    )


DEADLINE = datetime.now(timezone.utc) + timedelta(hours=3)


def requisite_row(**over):
    row = {
        "id": 1,
        "operator_id": 5,
        "label": "Карта Сбер",
        "direction": "payout",
        "method": "card",
        "requisites": "2202200112345678",
        "bank": "Сбербанк",
        "holder_name": "И. И.",
        "amount_rub": Decimal("10000.00"),
        "cost_pct": Decimal("3.000"),
        "crypto": "usdt",
        "paid_rub": Decimal("0.00"),
        "max_checks": 3,
        "doliv_limit_rub": 500,
        "status": "OPEN",
        "deadline_at": DEADLINE,
        "closed_at": None,
        "close_note": None,
        "confirmed_at": None,
        "confirmed_by": None,
        "source_sell_order_id": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    row.update(over)
    return row


def order_row(order_id="S1", amount="9700.00", status="PENDING", **over):
    row = {
        "order_id": order_id,
        "direction": "sell",
        "status": status,
        "fiat_amount": Decimal(amount),
        "crypto_amount": Decimal("100.00000000"),
        "crypto": "btc",
        "sub_token": "CARDRUB",
        "operator_id": None,
        "finance_operator_id": None,
        "user_id": 111,
    }
    row.update(over)
    return row


def alloc_row(**over):
    row = {
        "id": 11,
        "requisite_id": 1,
        "order_id": "S1",
        "kind": "order",
        "amount_rub": Decimal("9700.00"),
        "status": "RESERVED",
        "receipt_file": None,
        "paid_at": None,
        "note": None,
        "client_confirmed_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    row.update(over)
    return row


class FakeConn:
    """Отвечает по подстроке SQL — иначе порядок запросов делает тесты хрупкими."""

    def __init__(self):
        self.rowmap: list[tuple[str, object]] = []
        self.fetchmap: list[tuple[str, object]] = []
        self.valmap: list[tuple[str, object]] = []
        self.calls: list[tuple[str, tuple]] = []

    def on_row(self, needle, value):
        # Впереди списка, чтобы поздняя регистрация перекрывала базовую.
        self.rowmap.insert(0, (needle, value))
        return self

    def on_fetch(self, needle, value):
        self.fetchmap.insert(0, (needle, value))
        return self

    def on_val(self, needle, value):
        self.valmap.insert(0, (needle, value))
        return self

    def _pick(self, table, sql, args, default):
        for needle, value in table:
            if needle in sql:
                return value
        return default

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self._pick(self.rowmap, sql, args, None)

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self._pick(self.fetchmap, sql, args, [])

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self._pick(self.valmap, sql, args, 0)

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "OK"

    def transaction(self):
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    def sql_containing(self, needle: str) -> list[tuple[str, tuple]]:
        return [c for c in self.calls if needle in c[0]]


def _pool(conn: FakeConn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = ctx

    async def get_pool():
        return pool

    return get_pool


def _base_conn(requisite=None, reserved=0) -> FakeConn:
    conn = FakeConn()
    conn.on_row("FROM operator_shifts", {"id": 900, "operator_id": 5})
    conn.on_row(
        "FROM operator_payout_requisites",
        requisite if requisite is not None else requisite_row(),
    )
    conn.on_val("COALESCE(SUM(amount_rub), 0)", Decimal(str(reserved)))
    conn.on_fetch("FROM orders o", [])
    return conn


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_finance_has_permission_by_default(self):
        self.assertIn(PERM_PAYOUT_REQUISITES, _finance_op()["permissions"])

    def test_client_operator_has_requisites_not_confirm(self):
        self.assertIn(PERM_PAYOUT_REQUISITES, _client_op()["permissions"])
        self.assertNotIn(PERM_PAYOUT_REQUISITES_CONFIRM, _client_op()["permissions"])

    def test_finance_junior_cannot_confirm(self):
        self.assertNotIn(PERM_PAYOUT_REQUISITES_CONFIRM, _finance_op()["permissions"])

    def test_finance_senior_can_confirm(self):
        self.assertIn(PERM_PAYOUT_REQUISITES_CONFIRM, _finance_senior_op()["permissions"])

    async def test_list_forbidden_without_permission(self):
        mod = _mod()
        bare = {"id": 9, "username": "x", "permissions": set()}
        with patch(f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)):
            with self.assertRaises(HTTPException) as ctx:
                await mod.list_payout_requisites(op=bare)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("payout.requisites", str(ctx.exception.detail))

    def test_stale_payin_forecast_without_splits_is_unusable(self):
        mod = _mod()
        self.assertFalse(mod._cached_plan_usable({"kind": "forecast"}, {"direction": "payin"}))
        self.assertTrue(mod._cached_plan_usable({"kind": "forecast", "splits": []}, {"direction": "payin"}))
        self.assertTrue(mod._cached_plan_usable({"orders": []}, {"direction": "payout"}))
        self.assertTrue(
            mod._cached_plan_usable(
                {"orders": [], "doliv_rub": 1700, "closes": True},
                {"direction": "payin", "source_sell_order_id": "S1"},
            )
        )

    async def test_create_forbidden_without_permission(self):
        mod = _mod()
        body = _create_body()
        bare = {"id": 9, "username": "x", "permissions": set()}
        with patch(f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)):
            with self.assertRaises(HTTPException) as ctx:
                await mod.create_payout_requisite(body=body, op=bare)
        self.assertEqual(ctx.exception.status_code, 403)


class CreateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)

    async def test_create_inserts_and_hides_nothing_from_owner(self):
        mod = _mod()
        conn = _base_conn()
        conn.on_row("INSERT INTO operator_payout_requisites", requisite_row())
        body = _create_body(cost_pct=Decimal("3"), window_minutes=180)
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await mod.create_payout_requisite(body=body, op=_finance_op())
        req = out["requisite"]
        self.assertEqual(req["amount_rub"], 10000.0)
        self.assertEqual(req["cost_pct"], 3.0)
        self.assertEqual(req["remaining_rub"], 10000.0)
        self.assertEqual(req["reserved_rub"], 0.0)
        self.assertEqual(req["free_rub"], 10000.0)
        self.assertEqual(req["requisites"], "2202200112345678")
        self.assertEqual(req["requisites_masked"], "···5678")
        insert = conn.sql_containing("INSERT INTO operator_payout_requisites")[0]
        self.assertEqual(insert[1][-2], "OPEN")
        deadline = insert[1][-1]
        self.assertGreater(deadline, datetime.now(timezone.utc) + timedelta(minutes=170))

    def test_negative_cost_pct_allowed(self):
        mod = _mod()
        body = _create_body(method="sbp", requisites="+79990000000", cost_pct=Decimal("-3"))
        self.assertEqual(body.cost_pct, Decimal("-3"))

    def test_default_window_and_doliv(self):
        mod = _mod()
        body = _create_body()
        self.assertEqual(body.window_minutes, 180)
        self.assertEqual(body.doliv_limit_rub, 1000)
        self.assertEqual(_create_body(doliv_limit_rub=2000).doliv_limit_rub, 1000)
        self.assertEqual(body.max_checks, 3)

    def test_bank_and_holder_required(self):
        mod = _mod()
        with self.assertRaises(Exception):
            mod.RequisiteCreateBody(
                method="card",
                requisites="2202200112345678",
                amount_rub=Decimal("10000"),
            )
        with self.assertRaises(Exception):
            _create_body(bank=" ", holder_name="Иван Иванов")
        with self.assertRaises(Exception):
            _create_body(bank="Сбер", holder_name=" И ")
        body = _create_body(bank=" Сбер ", holder_name=" Иван Петров ")
        self.assertEqual(body.bank, "Сбер")
        self.assertEqual(body.holder_name, "Иван Петров")

    def test_bad_method_and_window_rejected(self):
        mod = _mod()
        with self.assertRaises(Exception):
            mod.RequisiteCreateBody(method="crypto", requisites="x123", amount_rub=Decimal("1"))
        with self.assertRaises(Exception):
            mod.RequisiteCreateBody(
                method="card",
                requisites="2202200112345678",
                amount_rub=Decimal("1"),
                window_minutes=5,
            )
        with self.assertRaises(Exception):
            mod.RequisiteCreateBody(
                method="card",
                requisites="2202200112345678",
                amount_rub=Decimal("1"),
                max_checks=9,
            )

    def test_payin_direction_accepted(self):
        mod = _mod()
        body = _create_body(direction="PAYIN")
        self.assertEqual(body.direction, "payin")

    async def test_create_stores_direction_and_forecast_plan_for_payin(self):
        mod = _mod()
        conn = _base_conn(requisite_row(direction="payin"))
        conn.on_row("INSERT INTO operator_payout_requisites", requisite_row(direction="payin", status="QUEUED"))
        body = _create_body(direction="payin")
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await mod.create_payout_requisite(body=body, op=_finance_op())
        self.assertEqual(out["requisite"]["direction"], "payin")
        self.assertEqual(out["requisite"]["status"], "QUEUED")
        self.assertEqual((out["requisite"]["plan"] or {}).get("kind"), "forecast")
        self.assertTrue(conn.sql_containing("INSERT INTO payout_requisite_plans"))
        self.assertTrue(any("lower(o.direction) = 'buy'" in sql for sql, _ in conn.calls))
        self.assertFalse(any("lower(o.direction) = 'sell'" in sql for sql, _ in conn.calls))
        inserts = conn.sql_containing("INSERT INTO operator_payout_requisites")
        self.assertIn("payin", inserts[0][1])
        self.assertEqual(inserts[0][1][-2], "QUEUED")
        self.assertIsNone(out["requisite"]["confirmed_at"])
        self.assertFalse(conn.sql_containing("SET status = 'OPEN'"))

    async def test_create_payin_stays_queued_for_senior_confirm_perm(self):
        mod = _mod()
        conn = _base_conn(requisite_row(direction="payin", status="QUEUED"))
        conn.on_row(
            "INSERT INTO operator_payout_requisites",
            requisite_row(direction="payin", status="QUEUED"),
        )
        body = _create_body(direction="payin")
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await mod.create_payout_requisite(body=body, op=_finance_senior_op())
        self.assertEqual(out["requisite"]["status"], "QUEUED")
        self.assertIsNone(out["requisite"]["confirmed_at"])
        self.assertFalse(conn.sql_containing("SET status = 'OPEN'"))
        self.assertFalse(conn.sql_containing("confirmed_at = now()"))

    async def test_create_payin_forces_queued_if_insert_opens(self):
        mod = _mod()
        opened = requisite_row(
            direction="payin",
            status="OPEN",
            confirmed_at=datetime.now(timezone.utc),
        )
        queued = requisite_row(direction="payin", status="QUEUED", confirmed_at=None)
        conn = _base_conn(queued)
        conn.on_row("INSERT INTO operator_payout_requisites", opened)
        conn.on_row("SET status = 'QUEUED'", queued)
        body = _create_body(direction="payin")
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await mod.create_payout_requisite(body=body, op=_finance_senior_op())
        self.assertEqual(out["requisite"]["status"], "QUEUED")
        self.assertIsNone(out["requisite"]["confirmed_at"])
        self.assertTrue(conn.sql_containing("confirmed_at = NULL"))
        inserts = conn.sql_containing("INSERT INTO operator_payout_requisites")
        self.assertEqual(inserts[0][1][-2], "QUEUED")


class ReserveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)
        self.mod = _mod()

    async def _reserve(self, conn, *, order_ids=("S1",), op=None):
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            return await self.mod.reserve_payout_requisite(
                requisite_id=1,
                body=self.mod.ReserveBody(order_ids=list(order_ids)),
                op=op or _finance_op(),
            )

    async def test_reserve_claims_order_and_creates_allocation(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id = $1 FOR UPDATE", order_row())
        conn.on_row("UPDATE orders", {"order_id": "S1"})
        conn.on_row("INSERT INTO payout_requisite_allocations", alloc_row())
        out = await self._reserve(conn)
        self.assertEqual(out["allocations"][0]["order_id"], "S1")
        self.assertEqual(out["allocations"][0]["status"], "RESERVED")
        claim = conn.sql_containing("SET operator_id = COALESCE(operator_id, $2)")[0]
        self.assertEqual(claim[1], ("S1", 5))
        self.assertTrue(conn.sql_containing("SET is_applied = TRUE"))

    async def test_requires_active_shift(self):
        conn = _base_conn()
        conn.on_row("FROM operator_shifts", None)
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("смену", str(ctx.exception.detail))

    async def test_foreign_requisite_forbidden(self):
        conn = _base_conn(requisite=requisite_row(operator_id=77))
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_closed_requisite_rejected(self):
        conn = _base_conn(requisite=requisite_row(status="CLOSED"))
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_expired_window_rejected(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        conn = _base_conn(requisite=requisite_row(deadline_at=past))
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("истекло", str(ctx.exception.detail))

    async def test_more_checks_than_allowed_rejected(self):
        conn = _base_conn(requisite=requisite_row(max_checks=2))
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn, order_ids=("S1", "S2", "S3"))
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_duplicate_orders_rejected(self):
        conn = _base_conn()
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn, order_ids=("S1", "S1"))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("дубл", str(ctx.exception.detail))

    async def test_buy_order_rejected(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id = $1 FOR UPDATE", order_row(direction="buy"))
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("не SELL", str(ctx.exception.detail))

    async def test_wrong_status_rejected(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id = $1 FOR UPDATE", order_row(status="PAID"))
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_sbp_order_on_card_requisite_rejected(self):
        conn = _base_conn()
        conn.on_row(
            "FROM orders WHERE order_id = $1 FOR UPDATE", order_row(sub_token="SBPRUB")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_amount_over_free_remaining_rejected(self):
        conn = _base_conn(reserved=Decimal("9000.00"))
        conn.on_row("FROM orders WHERE order_id = $1 FOR UPDATE", order_row())
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("остатка", str(ctx.exception.detail))

    async def test_order_taken_by_other_operator_rejected(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id = $1 FOR UPDATE", order_row())
        conn.on_row("UPDATE orders", None)
        with self.assertRaises(HTTPException) as ctx:
            await self._reserve(conn)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("другого оператора", str(ctx.exception.detail))

    async def test_empty_plan_rejected(self):
        conn = _base_conn()
        with patch(f"{MOD}.get_pool", new=_pool(conn)), patch(
            f"{MOD}.latest_plan", new=AsyncMock(return_value={"orders": []})
        ):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.reserve_payout_requisite(
                    requisite_id=1, body=self.mod.ReserveBody(), op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_falls_back_to_stored_plan(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id = $1 FOR UPDATE", order_row())
        conn.on_row("UPDATE orders", {"order_id": "S1"})
        conn.on_row("INSERT INTO payout_requisite_allocations", alloc_row())
        with patch(f"{MOD}.get_pool", new=_pool(conn)), patch(
            f"{MOD}.latest_plan",
            new=AsyncMock(return_value={"orders": [{"order_id": "S1", "amount_rub": 9700.0}]}),
        ):
            out = await self.mod.reserve_payout_requisite(
                requisite_id=1, body=self.mod.ReserveBody(), op=_finance_op()
            )
        self.assertEqual(out["allocations"][0]["order_id"], "S1")


def _pdf_upload():
    up = MagicMock()
    up.filename = "check.pdf"
    up.content_type = "application/pdf"
    up.read = AsyncMock(return_value=b"%PDF-1.4 test")
    return up


class AllocationPaidTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)
        self.mod = _mod()

    def _paid_patches(self, conn):
        return (
            patch(f"{MOD}.get_pool", new=_pool(conn)),
            patch(f"{MOD}.save_doliv_receipt", return_value="doliv-abc.pdf"),
            patch(f"{MOD}._deliver_payout_receipt", new=AsyncMock()),
        )

    async def test_paid_without_file_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.mod.mark_allocation_paid(
                requisite_id=1, allocation_id=11, file=None, op=_finance_op()
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_paid_marks_allocation_without_closing_order(self):
        conn = _base_conn()
        conn.on_row("FROM payout_requisite_allocations", alloc_row())
        conn.on_row("FROM orders WHERE order_id = $1", order_row())
        conn.on_row(
            "UPDATE payout_requisite_allocations",
            alloc_row(status="PAID", paid_at=datetime.now(timezone.utc), receipt_file="doliv-abc.pdf"),
        )
        patches = self._paid_patches(conn)
        with patches[0], patches[1], patches[2]:
            out = await self.mod.mark_allocation_paid(
                requisite_id=1,
                allocation_id=11,
                file=_pdf_upload(),
                op=_finance_op(),
            )
        self.assertEqual(out["allocation"]["status"], "PAID")
        self.assertNotEqual(out["order"]["status"], "PAID")
        self.assertEqual(out["order"]["payout_rail"]["stage"], "paid_awaiting_client")
        bump = conn.sql_containing("SET paid_rub = LEAST(paid_rub + $2, amount_rub)")[0]
        self.assertEqual(bump[1], (1, Decimal("9700.00")))

    async def test_doliv_allocation_cannot_be_closed_as_check(self):
        conn = _base_conn()
        conn.on_row(
            "FROM payout_requisite_allocations", alloc_row(kind="doliv", order_id=None)
        )
        patches = self._paid_patches(conn)
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.mark_allocation_paid(
                    requisite_id=1,
                    allocation_id=11,
                    file=_pdf_upload(),
                    op=_finance_op(),
                )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_already_paid_allocation_rejected(self):
        conn = _base_conn()
        conn.on_row("FROM payout_requisite_allocations", alloc_row(status="PAID"))
        patches = self._paid_patches(conn)
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.mark_allocation_paid(
                    requisite_id=1,
                    allocation_id=11,
                    file=_pdf_upload(),
                    op=_finance_op(),
                )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_reservation_lost_after_check_reports_conflict(self):
        conn = _base_conn()
        conn.on_row("FROM payout_requisite_allocations", alloc_row())
        conn.on_row("FROM orders WHERE order_id = $1", order_row())
        conn.on_row("UPDATE payout_requisite_allocations", None)
        patches = self._paid_patches(conn)
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.mark_allocation_paid(
                    requisite_id=1,
                    allocation_id=11,
                    file=_pdf_upload(),
                    op=_finance_op(),
                )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_paid_handler_does_not_call_sell_paid(self):
        src = (ROOT / "routers" / "operator_payout_requisites.py").read_text()
        paid_fn = src.split("async def mark_allocation_paid")[1].split(
            "async def attach_allocation_receipt"
        )[0]
        self.assertNotIn("execute_sell_paid", paid_fn)


class DolivTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)
        self.mod = _mod()

    async def test_doliv_inside_limit_marks_paid(self):
        conn = _base_conn(requisite=requisite_row(paid_rub=Decimal("9700.00")))
        conn.on_row(
            "INSERT INTO payout_requisite_allocations",
            alloc_row(
                id=12,
                kind="doliv",
                order_id=None,
                amount_rub=Decimal("300.00"),
                status="PAID",
            ),
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.add_doliv(
                requisite_id=1, amount_rub=Decimal("300"), op=_finance_op(), note="добил"
            )
        self.assertEqual(out["allocation"]["kind"], "doliv")
        self.assertEqual(out["allocation"]["status"], "PAID")
        self.assertIsNone(out["allocation"]["order_id"])

    async def test_doliv_above_limit_rejected(self):
        conn = _base_conn()
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.add_doliv(
                    requisite_id=1, amount_rub=Decimal("900"), op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("лимита", str(ctx.exception.detail))

    async def test_doliv_above_free_remaining_rejected(self):
        conn = _base_conn(
            requisite=requisite_row(paid_rub=Decimal("9900.00"), doliv_limit_rub=500)
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.add_doliv(
                    requisite_id=1, amount_rub=Decimal("300"), op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_zero_doliv_rejected(self):
        with patch(f"{MOD}.get_pool", new=_pool(_base_conn())):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.add_doliv(
                    requisite_id=1, amount_rub=Decimal("0"), op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_doliv_rejected_on_manual_payin(self):
        conn = _base_conn(
            requisite=requisite_row(direction="payin", source_sell_order_id=None)
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.add_doliv(
                    requisite_id=1, amount_rub=Decimal("300"), op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("треугольник", str(ctx.exception.detail).lower())

    async def test_doliv_allowed_on_triangle_payin(self):
        conn = _base_conn(
            requisite=requisite_row(
                direction="payin",
                source_sell_order_id="S1",
                doliv_limit_rub=2000,
                paid_rub=Decimal("3300.00"),
                amount_rub=Decimal("5000.00"),
            )
        )
        conn.on_row(
            "INSERT INTO payout_requisite_allocations",
            alloc_row(
                id=12,
                kind="doliv",
                order_id="S1",
                amount_rub=Decimal("300.00"),
                status="PAID",
            ),
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)), patch(
            f"{MOD}.complete_triangle_sell", new=AsyncMock()
        ):
            out = await self.mod.add_doliv(
                requisite_id=1, amount_rub=Decimal("300"), op=_finance_op()
            )
        self.assertEqual(out["allocation"]["kind"], "doliv")
        self.assertEqual(out["allocation"]["order_id"], "S1")
        insert = conn.sql_containing("INSERT INTO payout_requisite_allocations")[0]
        self.assertEqual(insert[1][1], "S1")

    async def test_doliv_rejected_when_triangle_is_at_most_2000(self):
        conn = _base_conn(
            requisite=requisite_row(
                direction="payin",
                source_withdrawal_id=4,
                amount_rub=Decimal("1500.00"),
                doliv_limit_rub=0,
                max_checks=1,
            )
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.add_doliv(
                    requisite_id=1, amount_rub=Decimal("200"), op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("одним чеком", str(ctx.exception.detail))


class MaxChecksTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)
        self.mod = _mod()

    async def test_updates_max_checks(self):
        req = requisite_row(status="OPEN", max_checks=3, direction="payin")
        updated = requisite_row(status="OPEN", max_checks=2, direction="payin")
        conn = _base_conn(requisite=req)
        conn.on_val("status = ANY($2::text[])", 1)
        conn.on_val("status = 'RESERVED'", 0)
        conn.on_row("SET max_checks = $2", updated)
        with patch(f"{MOD}.get_pool", new=_pool(conn)), patch(
            f"{MOD}.plan_for_requisite", new=AsyncMock(return_value=(None, Decimal("0")))
        ), patch(f"{MOD}.store_plan", new=AsyncMock()):
            out = await self.mod.update_payout_requisite_max_checks(
                requisite_id=1,
                body=self.mod.MaxChecksBody(max_checks=2),
                op=_finance_op(),
            )
        self.assertEqual(out["requisite"]["max_checks"], 2)
        self.assertEqual(out["requisite"]["used_checks"], 1)
        self.assertEqual(out["requisite"]["checks_left"], 1)

    async def test_rejects_below_used(self):
        conn = _base_conn(requisite=requisite_row(status="OPEN", max_checks=3, direction="payin"))
        conn.on_val("status = ANY($2::text[])", 3)
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.update_payout_requisite_max_checks(
                    requisite_id=1,
                    body=self.mod.MaxChecksBody(max_checks=2),
                    op=_finance_op(),
                )
        self.assertEqual(ctx.exception.status_code, 400)


class CloseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)
        self.mod = _mod()

    async def test_close_releases_reserved_orders(self):
        conn = _base_conn()
        conn.on_fetch("UPDATE payout_requisite_allocations", [{"order_id": "S1"}])
        conn.on_row(
            "UPDATE operator_payout_requisites",
            requisite_row(status="CLOSED", close_note="готово"),
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.close_payout_requisite(
                requisite_id=1, body=self.mod.CloseBody(note="готово"), op=_finance_op()
            )
        self.assertEqual(out["requisite"]["status"], "CLOSED")
        self.assertEqual(out["released"], 1)
        release = conn.sql_containing("SET operator_id = NULL")[0]
        self.assertEqual(release[1], ("S1", ["PENDING", "OPERATOR_PENDING"], 5))

    async def test_cancel_sets_canceled_status(self):
        conn = _base_conn()
        conn.on_fetch("UPDATE payout_requisite_allocations", [])
        conn.on_row("UPDATE operator_payout_requisites", requisite_row(status="CANCELED"))
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.cancel_payout_requisite(
                requisite_id=1, body=self.mod.CloseBody(), op=_finance_op()
            )
        self.assertEqual(out["requisite"]["status"], "CANCELED")
        self.assertEqual(out["released"], 0)

    async def test_close_queued_conflicts(self):
        conn = _base_conn(requisite=requisite_row(direction="payin", status="QUEUED"))
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.close_payout_requisite(
                    requisite_id=1, body=self.mod.CloseBody(), op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_cancel_queued_allowed(self):
        conn = _base_conn(requisite=requisite_row(direction="payin", status="QUEUED"))
        conn.on_fetch("UPDATE payout_requisite_allocations", [])
        conn.on_row("UPDATE operator_payout_requisites", requisite_row(status="CANCELED"))
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.cancel_payout_requisite(
                requisite_id=1, body=self.mod.CloseBody(), op=_finance_op()
            )
        self.assertEqual(out["requisite"]["status"], "CANCELED")

    async def test_cancel_allocation_returns_order_to_pool(self):
        conn = _base_conn()
        conn.on_row("UPDATE payout_requisite_allocations", alloc_row(status="CANCELED"))
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.cancel_allocation(
                requisite_id=1, allocation_id=11, op=_finance_op()
            )
        self.assertEqual(out["allocation"]["status"], "CANCELED")
        self.assertTrue(conn.sql_containing("SET operator_id = NULL"))

    async def test_cancel_missing_allocation_conflicts(self):
        conn = _base_conn()
        conn.on_row("UPDATE payout_requisite_allocations", None)
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.cancel_allocation(
                    requisite_id=1, allocation_id=11, op=_finance_op()
                )
        self.assertEqual(ctx.exception.status_code, 409)


class MaskingTests(unittest.TestCase):
    def test_mask_keeps_last_four(self):
        mod = _mod()
        self.assertEqual(mod.mask_requisites("2202200112345678"), "···5678")
        self.assertEqual(mod.mask_requisites("1234"), "1234")
        self.assertIsNone(mod.mask_requisites(""))

    def test_cost_rub_follows_paid_volume_and_sign(self):
        mod = _mod()
        self.assertEqual(
            mod._cost_rub(requisite_row(paid_rub=Decimal("10000"), cost_pct=Decimal("3"))),
            Decimal("300.00"),
        )
        self.assertEqual(
            mod._cost_rub(requisite_row(paid_rub=Decimal("10000"), cost_pct=Decimal("-3"))),
            Decimal("-300.00"),
        )
        self.assertEqual(
            mod._cost_rub(requisite_row(paid_rub=Decimal("0"), cost_pct=Decimal("3"))),
            Decimal("0.00"),
        )


class RemainingOutTests(unittest.TestCase):
    def test_free_rub_subtracts_reserved(self):
        mod = _mod()
        out = mod._requisite_out(
            requisite_row(
                amount_rub=Decimal("7000.00"),
                paid_rub=Decimal("0.00"),
                reserved_rub=Decimal("4315.60"),
            )
        )
        self.assertEqual(out["remaining_rub"], 7000.0)
        self.assertAlmostEqual(out["reserved_rub"], 4315.6, places=2)
        self.assertAlmostEqual(out["free_rub"], 2684.4, places=2)

    def test_remaining_is_unsettled_free_excludes_reserve(self):
        mod = _mod()
        out = mod._requisite_out(
            requisite_row(
                amount_rub=Decimal("7000.00"),
                paid_rub=Decimal("1000.00"),
                reserved_rub=Decimal("2000.00"),
            )
        )
        self.assertEqual(out["remaining_rub"], 6000.0)
        self.assertEqual(out["reserved_rub"], 2000.0)
        self.assertEqual(out["free_rub"], 4000.0)

    def test_missing_reserved_defaults_to_zero(self):
        mod = _mod()
        out = mod._requisite_out(requisite_row())
        self.assertEqual(out["reserved_rub"], 0.0)
        self.assertEqual(out["free_rub"], 10000.0)
        self.assertEqual(out["remaining_rub"], 10000.0)


class AttachStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserved_sum_becomes_reserved_rub(self):
        mod = _mod()
        conn = FakeConn()
        conn.on_val("status = ANY($2::text[])", 1)
        conn.on_val("status = 'RESERVED'", 1)
        conn.on_val("COALESCE(SUM(amount_rub), 0)", Decimal("4315.60"))
        out = await mod._attach_check_stats(conn, {"id": 1, "max_checks": 2})
        self.assertEqual(out["used_checks"], 1)
        self.assertTrue(out["has_open_reserve"])
        self.assertAlmostEqual(float(out["reserved_rub"]), 4315.6, places=2)
        payload = mod._requisite_out(requisite_row(amount_rub=Decimal("7000.00"), **out))
        self.assertAlmostEqual(payload["free_rub"], 2684.4, places=2)


class CostLedgerTests(unittest.IsolatedAsyncioTestCase):
    def test_cost_follows_paid_volume_and_sign(self):
        from payout_requisite_cost import cost_rub, ledger_reference

        self.assertEqual(cost_rub(Decimal("10000"), Decimal("3")), Decimal("300.00"))
        self.assertEqual(cost_rub(Decimal("10000"), Decimal("-3")), Decimal("-300.00"))
        self.assertEqual(cost_rub(Decimal("9700"), Decimal("0")), Decimal("0.00"))
        self.assertEqual(ledger_reference(7), "payout-requisite-7")

    async def test_zero_cost_writes_nothing(self):
        from payout_requisite_cost import post_requisite_cost

        conn = MagicMock()
        conn.fetchval = AsyncMock()
        out = await post_requisite_cost(
            conn, requisite_row(paid_rub=Decimal("10000"), cost_pct=Decimal("0"))
        )
        self.assertIsNone(out)
        conn.fetchval.assert_not_awaited()

    async def test_payin_is_not_posted_to_ledger(self):
        from payout_requisite_cost import post_requisite_cost

        conn = MagicMock()
        conn.fetchval = AsyncMock()
        out = await post_requisite_cost(
            conn,
            requisite_row(
                direction="payin",
                paid_rub=Decimal("10000"),
                cost_pct=Decimal("3"),
            ),
        )
        self.assertIsNone(out)
        conn.fetchval.assert_not_awaited()

    async def test_posting_is_idempotent_by_reference(self):
        from payout_requisite_cost import post_requisite_cost

        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=42)
        row = requisite_row(paid_rub=Decimal("10000"), cost_pct=Decimal("3"))
        out = await post_requisite_cost(conn, row)
        self.assertEqual(out, 42)
        self.assertEqual(conn.fetchval.await_count, 1)
        self.assertIn("WHERE reference = $1", conn.fetchval.await_args.args[0])

    async def test_posting_inserts_signed_expense(self):
        from payout_requisite_cost import post_requisite_cost

        conn = MagicMock()
        conn.fetchval = AsyncMock(side_effect=[None, 99])
        row = requisite_row(paid_rub=Decimal("10000"), cost_pct=Decimal("-3"))
        out = await post_requisite_cost(conn, row)
        self.assertEqual(out, 99)
        sql, args = conn.fetchval.await_args.args[0], conn.fetchval.await_args.args[1:]
        self.assertIn("INSERT INTO owner_finance_ledger", sql)
        self.assertEqual(args[0], "expense")
        self.assertEqual(args[1], Decimal("-300.00"))
        self.assertEqual(args[2], "payout_requisite")
        self.assertEqual(args[3], "payout-requisite-1")

    async def test_failure_does_not_break_close(self):
        from payout_requisite_cost import safe_post_requisite_cost

        conn = MagicMock()
        conn.fetchval = AsyncMock(side_effect=RuntimeError("ledger down"))
        row = requisite_row(paid_rub=Decimal("10000"), cost_pct=Decimal("3"))
        self.assertIsNone(await safe_post_requisite_cost(conn, row))

    async def test_close_posts_cost(self):
        mod = _mod()
        conn = _base_conn()
        conn.on_fetch("UPDATE payout_requisite_allocations", [])
        conn.on_row(
            "UPDATE operator_payout_requisites",
            requisite_row(status="CLOSED", paid_rub=Decimal("10000")),
        )
        poster = AsyncMock(return_value=1)
        with patch(f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)), \
            patch(f"{MOD}.get_pool", new=_pool(conn)), \
            patch(f"{MOD}.safe_post_requisite_cost", new=poster):
            await mod.close_payout_requisite(
                requisite_id=1, body=mod.CloseBody(), op=_finance_op()
            )
        poster.assert_awaited_once()

    def test_order_economics_snapshot_left_immutable(self):
        # Стоимость реквизита живёт в журнале, а не в снимке тарифов заявки.
        src = (ROOT / "payout_requisite_cost.py").read_text()
        self.assertIn("owner_finance_ledger", src)
        self.assertNotIn("UPDATE orders", src)
        self.assertNotIn("economics_snapshot =", src)


class PayoffQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def _quote(self, rates, **kw):
        mod = _mod()
        with patch(f"{MOD}.get_need_rates_cached", new=AsyncMock(return_value=rates)):
            return await mod.quote_payout_requisite_payoff(op=_finance_op(), **kw)

    async def test_positive_cost_pays_above_nominal(self):
        out = await self._quote(
            {"usdt": 80.0}, amount_rub=Decimal("10000"), cost_pct=Decimal("1.5"), crypto="usdt"
        )
        self.assertEqual(out["cost_rub"], 150.0)
        self.assertEqual(out["payoff_rub"], 10150.0)
        self.assertEqual(out["crypto_amount"], 126.88)
        self.assertEqual(out["rate_source"], "coingecko")

    async def test_negative_cost_pays_below_nominal(self):
        out = await self._quote(
            {"usdt": 80.0}, amount_rub=Decimal("10000"), cost_pct=Decimal("-2"), crypto="usdt"
        )
        self.assertEqual(out["cost_rub"], -200.0)
        self.assertEqual(out["payoff_rub"], 9800.0)
        self.assertEqual(out["crypto_amount"], 122.5)

    async def test_payin_reverses_crypto_flow(self):
        out = await self._quote(
            {"usdt": 80.0},
            amount_rub=Decimal("10000"),
            cost_pct=Decimal("3"),
            crypto="usdt",
            direction="payin",
        )
        self.assertEqual(out["cost_rub"], 300.0)
        self.assertEqual(out["payoff_rub"], 9700.0)
        self.assertEqual(out["crypto_amount"], 121.25)
        self.assertEqual(out["direction"], "payin")

    async def test_btc_uses_satoshi_precision(self):
        out = await self._quote(
            {"btc": 8_000_000.0}, amount_rub=Decimal("10000"), cost_pct=Decimal("0"), crypto="btc"
        )
        self.assertEqual(out["crypto_amount"], 0.00125)

    async def test_unavailable_rate_is_503(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._quote({}, amount_rub=Decimal("10000"))
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_unknown_coin_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._quote({"usdt": 80.0}, amount_rub=Decimal("10000"), crypto="doge")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_forbidden_without_permission(self):
        mod = _mod()
        bare = {"id": 9, "username": "x", "permissions": set()}
        with patch(f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)):
            with self.assertRaises(HTTPException) as ctx:
                await mod.quote_payout_requisite_payoff(
                    op=bare, amount_rub=Decimal("10000")
                )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_create_stores_selected_crypto(self):
        mod = _mod()
        conn = _base_conn()
        conn.on_row("INSERT INTO operator_payout_requisites", requisite_row(crypto="btc"))
        body = _create_body(crypto="BTC")
        self.assertEqual(body.crypto, "btc")
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await mod.create_payout_requisite(body=body, op=_finance_op())
        self.assertEqual(out["requisite"]["crypto"], "btc")
        inserts = conn.sql_containing("INSERT INTO operator_payout_requisites")
        self.assertIn("btc", inserts[0][1])


class ConfirmQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)
        self.mod = _mod()

    async def test_list_includes_queued(self):
        conn = FakeConn()
        conn.on_fetch("FROM operator_payout_requisites r", [])
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            await self.mod.list_payout_requisites(op=_finance_op())
        args = conn.sql_containing("FROM operator_payout_requisites r")[0][1]
        self.assertIn("QUEUED", args[0])
        self.assertIn("OPEN", args[0])

    async def test_list_pool_orders_only_confirmed_unreserved_sell(self):
        created = datetime.now(timezone.utc)
        conn = FakeConn()
        conn.on_fetch("FROM operator_payout_requisites r", [])
        conn.on_fetch(
            "FROM orders o",
            [
                {
                    "order_id": "S9",
                    "user_id": 1,
                    "fiat_amount": Decimal("5900.00"),
                    "crypto": "btc",
                    "sub_token": None,
                    "created_at": created,
                }
            ],
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.list_payout_requisites(op=_finance_op())
        self.assertEqual(out["pool_orders"][0]["order_id"], "S9")
        self.assertEqual(out["pool_orders"][0]["fiat_amount"], 5900.0)
        self.assertEqual(out["pool_orders"][0]["crypto"], "btc")
        sql, args = conn.sql_containing("FROM orders o")[0]
        self.assertIn("crypto_confirmed_at IS NOT NULL", sql)
        self.assertIn("lower(o.direction) = 'sell'", sql)
        self.assertIn("NOT EXISTS", sql)
        self.assertIn("payout_requisite_allocations", sql)
        self.assertEqual(list(args[0]), ["PENDING", "OPERATOR_PENDING"])
        self.assertIsNone(args[1])
        self.assertIsNone(args[2])
        self.assertEqual(args[3], ["RESERVED", "PAID"])
        self.assertIn("source_sell_order_id", sql)
        self.assertIn("QUEUED", args[4])

    async def test_list_pool_orders_empty_after_no_candidates(self):
        conn = FakeConn()
        conn.on_fetch("FROM operator_payout_requisites r", [])
        conn.on_fetch("FROM orders o", [])
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.list_payout_requisites(op=_finance_op())
        self.assertEqual(out["pool_orders"], [])

    async def test_confirm_forbidden_without_perm(self):
        with self.assertRaises(HTTPException) as ctx:
            await self.mod.confirm_payout_requisite(requisite_id=1, op=_finance_op())
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("payout.requisites.confirm", str(ctx.exception.detail))

    async def test_confirm_opens_queued_payin(self):
        conn = _base_conn(requisite=requisite_row(direction="payin", status="QUEUED"))
        conn.on_row(
            "UPDATE operator_payout_requisites",
            requisite_row(direction="payin", status="OPEN"),
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.confirm_payout_requisite(
                requisite_id=1, op=_finance_senior_op()
            )
        self.assertEqual(out["requisite"]["status"], "OPEN")
        self.assertFalse(out["already_confirmed"])
        update = conn.sql_containing("SET status = 'OPEN'")[0]
        self.assertEqual(update[1][1], 5)

    async def test_confirm_idempotent_when_already_open(self):
        conn = _base_conn(requisite=requisite_row(direction="payin", status="OPEN"))
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.confirm_payout_requisite(
                requisite_id=1, op=_finance_senior_op()
            )
        self.assertTrue(out["already_confirmed"])
        self.assertFalse(conn.sql_containing("SET status = 'OPEN'"))

    async def test_confirm_rejects_payout_direction(self):
        conn = _base_conn(requisite=requisite_row(direction="payout", status="OPEN"))
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.confirm_payout_requisite(
                    requisite_id=1, op=_finance_senior_op()
                )
        self.assertEqual(ctx.exception.status_code, 400)


class FromSellTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)
        self.mod = _mod()

    def _sell(self, **over):
        row = order_row(
            requisites="2202200112345678 Сбер",
            crypto_confirmed_at=datetime.now(timezone.utc),
        )
        row.update(over)
        return row

    def _triangle_row(self, **over):
        row = requisite_row(
            direction="payin",
            status="QUEUED",
            cost_pct=Decimal("0"),
            source_sell_order_id="S1",
            amount_rub=Decimal("9700.00"),
            label="SELL S1",
            method="card",
            requisites="2202200112345678",
        )
        row.update(over)
        return row

    async def test_from_sell_creates_queued_payin_at_zero_cost(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id", self._sell())
        conn.on_row("INSERT INTO operator_payout_requisites", self._triangle_row())
        with (
            patch(f"{MOD}.get_pool", new=_pool(conn)),
            patch("runtime_settings.triangle_sell_bonus_pct", return_value=3),
            patch("runtime_settings.triangle_enabled", return_value=True),
        ):
            out = await self.mod.create_payin_from_sell(order_id="S1", op=_finance_op())
        req = out["requisite"]
        self.assertEqual(req["direction"], "payin")
        self.assertEqual(req["status"], "QUEUED")
        self.assertEqual(req["cost_pct"], 0.0)
        self.assertEqual(req["source_sell_order_id"], "S1")
        self.assertIsNone(req["confirmed_at"])
        inserts = conn.sql_containing("INSERT INTO operator_payout_requisites")
        self.assertTrue(inserts)
        sql, args = inserts[0]
        self.assertIn("source_sell_order_id", sql)
        self.assertIn("'QUEUED'", sql)
        self.assertEqual(args[1], "SELL S1")
        self.assertEqual(args[2], "payin")
        self.assertEqual(args[3], "card")
        self.assertEqual(args[7], Decimal("9991.00"))
        self.assertEqual(args[-1], "S1")

    async def test_from_sell_parses_sbp_8_prefix(self):
        conn = _base_conn()
        conn.on_row(
            "FROM orders WHERE order_id",
            self._sell(sub_token="SBPRUB", requisites="8 999 123-45-67 Тинькофф"),
        )
        conn.on_row(
            "INSERT INTO operator_payout_requisites",
            self._triangle_row(method="sbp", requisites="79991234567", bank="Тинькофф"),
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            await self.mod.create_payin_from_sell(order_id="S1", op=_finance_op())
        _sql, args = conn.sql_containing("INSERT INTO operator_payout_requisites")[0]
        self.assertEqual(args[3], "sbp")
        self.assertEqual(args[4], "79991234567")

    async def test_from_sell_short_phone_returns_structured_400(self):
        conn = _base_conn()
        conn.on_row(
            "FROM orders WHERE order_id",
            self._sell(sub_token="", requisites="+799999999 сбербакнк"),
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.create_payin_from_sell(order_id="S1", op=_finance_op())
        self.assertEqual(ctx.exception.status_code, 400)
        detail = ctx.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail["code"], "unparsed_requisites")
        self.assertIn("телефон", str(detail["message"]).lower())
        self.assertEqual(detail["order_id"], "S1")
        self.assertIn("799999999", detail["requisites"])
        self.assertFalse(conn.sql_containing("INSERT INTO operator_payout_requisites"))

    async def test_from_sell_override_creates_card_and_persists(self):
        conn = _base_conn()
        conn.on_row(
            "FROM orders WHERE order_id",
            self._sell(sub_token="", requisites="+799999999 сбербакнк"),
        )
        conn.on_row(
            "INSERT INTO operator_payout_requisites",
            self._triangle_row(method="sbp", requisites="79001234567", bank="Сбербанк"),
        )
        body = self.mod.FromSellBody(
            method="sbp",
            requisites="79001234567",
            bank="Сбербанк",
            holder_name="клиент",
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.create_payin_from_sell(
                order_id="S1", op=_finance_op(), body=body
            )
        self.assertEqual(out["requisite"]["status"], "QUEUED")
        inserts = conn.sql_containing("INSERT INTO operator_payout_requisites")
        self.assertEqual(inserts[0][1][3], "sbp")
        self.assertEqual(inserts[0][1][4], "79001234567")
        updates = conn.sql_containing("UPDATE orders")
        self.assertTrue(updates)
        self.assertEqual(updates[0][1][1], "79001234567 Сбербанк")
        self.assertEqual(updates[0][1][2], "SBPRUB")

    async def test_from_sell_opens_when_operator_can_confirm(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id", self._sell())
        conn.on_row("INSERT INTO operator_payout_requisites", self._triangle_row())
        opened = self._triangle_row(
            status="OPEN",
            confirmed_at=datetime.now(timezone.utc),
            confirmed_by=5,
        )
        conn.on_row("SET status = 'OPEN'", opened)
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            out = await self.mod.create_payin_from_sell(
                order_id="S1", op=_finance_senior_op()
            )
        self.assertEqual(out["requisite"]["status"], "OPEN")
        self.assertIsNotNone(out["requisite"]["confirmed_at"])
        self.assertTrue(conn.sql_containing("SET status = 'OPEN'"))

    async def test_from_sell_duplicate_live_card_conflicts(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id", self._sell())
        conn.on_val("source_sell_order_id", 9)
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.create_payin_from_sell(order_id="S1", op=_finance_op())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("уже стоит", str(ctx.exception.detail))

    async def test_from_sell_requires_crypto_confirmed(self):
        conn = _base_conn()
        conn.on_row("FROM orders WHERE order_id", self._sell(crypto_confirmed_at=None))
        with patch(f"{MOD}.get_pool", new=_pool(conn)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.create_payin_from_sell(order_id="S1", op=_finance_op())
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_from_sell_forbidden_without_permission(self):
        bare = {"id": 9, "username": "x", "permissions": set()}
        with patch(f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)):
            with self.assertRaises(HTTPException) as ctx:
                await self.mod.create_payin_from_sell(order_id="S1", op=bare)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_client_has_requisites_perm_for_from_sell(self):
        self.assertIn(PERM_PAYOUT_REQUISITES, _client_op()["permissions"])


class WiringTests(unittest.TestCase):
    def test_router_mounted_under_operator_prefix(self):
        main = (ROOT / "main.py").read_text()
        self.assertIn("operator_payout_requisites", main)
        self.assertIn(
            'app.include_router(operator_payout_requisites.router, prefix="/api/operator"',
            main,
        )

    def test_endpoints_declared(self):
        src = (ROOT / "routers" / "operator_payout_requisites.py").read_text()
        for path in (
            '@router.post("/payout-requisites")',
            '@router.get("/payout-requisites")',
            '@router.get("/payout-requisites/quote")',
            '@router.post("/payout-requisites/from-sell/{order_id}")',
            '@router.get("/payout-requisites/{requisite_id}/plan")',
            '@router.post("/payout-requisites/{requisite_id}/reserve")',
            '@router.post("/payout-requisites/{requisite_id}/doliv")',
            '@router.post("/payout-requisites/{requisite_id}/close")',
            '@router.post("/payout-requisites/{requisite_id}/cancel")',
            '@router.post("/payout-requisites/{requisite_id}/confirm")',
            '@router.post("/payout-requisites/{requisite_id}/max-checks")',
        ):
            self.assertIn(path, src)
        self.assertIn("PERM_PAYOUT_REQUISITES", src)
        self.assertIn("PERM_PAYOUT_REQUISITES_CONFIRM", src)


class PayinAllocationJoinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enrich = patch(
            f"{MOD}.enrich_operator_permissions", new=AsyncMock(side_effect=lambda o: o)
        )
        self.enrich.start()
        self.addCleanup(self.enrich.stop)

    def test_allocation_out_sell_without_order_join(self):
        out = _mod()._allocation_out(alloc_row())
        self.assertFalse(out["has_buyer_receipt"])
        self.assertFalse(out["has_receipt"])
        self.assertIsNone(out["order_status"])
        self.assertFalse(out["receipt_ops_pending"])
        self.assertFalse(out["client_confirmed"])
        self.assertIsNone(out["order_requisites"])

    def test_allocation_out_payin_buyer_pdf(self):
        out = _mod()._allocation_out(
            alloc_row(
                kind="payin",
                order_id="B1",
                receipt_file=None,
                order_receipt_file="buyer.pdf",
                order_status="AWAITING_CHECK",
                order_fiat_amount=Decimal("15000"),
                order_crypto="usdt",
                payment_snapshot={"receipt_ops_pending": True},
                order_user_id=8443902979,
                buyer_username="absoluteop",
                buyer_first_name="3",
            )
        )
        self.assertTrue(out["has_buyer_receipt"])
        self.assertFalse(out["has_receipt"])
        self.assertEqual(out["order_status"], "AWAITING_CHECK")
        self.assertEqual(out["order_fiat_amount"], 15000.0)
        self.assertTrue(out["receipt_ops_pending"])
        self.assertIsNone(out["user_id"])
        self.assertIsNone(out["buyer_username"])

    def test_allocations_sql_joins_orders(self):
        src = (ROOT / "routers" / "operator_payout_requisites.py").read_text()
        self.assertIn("LEFT JOIN orders o ON o.order_id = a.order_id", src)
        self.assertIn("LEFT JOIN bot_users bu ON bu.user_id = o.user_id", src)
        self.assertIn("order_receipt_file", src)
        self.assertIn("has_buyer_receipt", src)
        self.assertIn("order_user_id", src)
        self.assertIn("buyer_username", src)
        self.assertIn("order_wallet", src)

    async def test_get_exposes_buyer_receipt_on_payin_allocation(self):
        mod = _mod()
        conn = _base_conn(requisite_row(direction="payin"))
        conn.on_fetch(
            "FROM payout_requisite_allocations",
            [
                alloc_row(
                    kind="payin",
                    order_id="B1",
                    receipt_file=None,
                    order_receipt_file="buyer.pdf",
                    order_status="AWAITING_CHECK",
                    order_fiat_amount=Decimal("18415"),
                    order_crypto="usdt",
                    payment_snapshot={"receipt_ops_pending": True},
                )
            ],
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)), patch(
            f"{MOD}._plan_for_owned", new=AsyncMock(return_value=None)
        ):
            out = await mod.get_payout_requisite(1, op=_finance_op())
        alloc = out["requisite"]["allocations"][0]
        self.assertEqual(alloc["order_id"], "B1")
        self.assertTrue(alloc["has_buyer_receipt"])
        self.assertFalse(alloc["has_receipt"])
        self.assertEqual(alloc["order_status"], "AWAITING_CHECK")
        self.assertTrue(alloc["receipt_ops_pending"])

    def test_allocation_out_hides_client_requisites_unless_revealed(self):
        row = alloc_row(
            order_requisites="2202200112345678",
            order_sub_token="CARDRUB",
            order_user_id=8443902979,
            buyer_username="absoluteop",
            buyer_first_name="3",
            order_crypto_amount=Decimal("0.00029"),
            order_wallet="bc1q4ddwlwnp6qpuhnd0qyl5c2dr97le0m9y98xw9a",
        )
        hidden = _mod()._allocation_out(row)
        self.assertIsNone(hidden["order_requisites"])
        self.assertIsNone(hidden["user_id"])
        self.assertIsNone(hidden["buyer_username"])
        self.assertIsNone(hidden["buyer_first_name"])
        self.assertIsNone(hidden["order_crypto_amount"])
        self.assertIsNone(hidden["order_wallet"])
        shown = _mod()._allocation_out(row, reveal_order=True)
        self.assertEqual(shown["order_requisites"], "2202200112345678")
        self.assertEqual(shown["order_sub_token"], "CARDRUB")
        self.assertEqual(shown["user_id"], 8443902979)
        self.assertEqual(shown["buyer_username"], "absoluteop")
        self.assertEqual(shown["buyer_first_name"], "3")
        self.assertEqual(shown["order_crypto_amount"], 0.00029)
        self.assertEqual(shown["order_wallet"], "bc1q4ddwlwnp6qpuhnd0qyl5c2dr97le0m9y98xw9a")

    async def test_get_shows_client_requisites_to_owner_only(self):
        mod = _mod()
        conn = _base_conn()
        conn.on_fetch(
            "FROM payout_requisite_allocations",
            [
                alloc_row(
                    order_requisites="2202200112345678",
                    order_sub_token="SBPRUB",
                    order_user_id=8443902979,
                    buyer_username="absoluteop",
                    buyer_first_name="3",
                )
            ],
        )
        with patch(f"{MOD}.get_pool", new=_pool(conn)), patch(
            f"{MOD}._plan_for_owned", new=AsyncMock(return_value=None)
        ):
            mine = await mod.get_payout_requisite(1, op=_finance_op())
            other = await mod.get_payout_requisite(1, op=_finance_op(9))
        mine_alloc = mine["requisite"]["allocations"][0]
        other_alloc = other["requisite"]["allocations"][0]
        self.assertEqual(mine_alloc["order_requisites"], "2202200112345678")
        self.assertEqual(mine_alloc["user_id"], 8443902979)
        self.assertEqual(mine_alloc["buyer_username"], "absoluteop")
        self.assertIsNone(other_alloc["order_requisites"])
        self.assertIsNone(other_alloc["user_id"])
        self.assertIsNone(other_alloc["buyer_username"])

    async def test_attach_receipt_resets_client_confirm_and_resends(self):
        mod = _mod()
        conn = _base_conn()
        conn.on_row(
            "UPDATE payout_requisite_allocations",
            alloc_row(status="PAID", receipt_file="new.pdf", client_confirmed_at=None),
        )
        conn.on_row("FROM orders WHERE order_id = $1", order_row())
        deliver = AsyncMock()
        with patch(f"{MOD}.get_pool", new=_pool(conn)), patch(
            f"{MOD}.save_doliv_receipt", return_value="new.pdf"
        ), patch(f"{MOD}._deliver_payout_receipt", new=deliver):
            await mod.attach_allocation_receipt(
                1, 11, file=_pdf_upload(), op=_finance_op()
            )
        update_sql = conn.sql_containing("client_confirmed_at = NULL")[0][0]
        self.assertIn("receipt_file = $3", update_sql)
        deliver.assert_awaited_once()
        self.assertFalse(deliver.await_args.kwargs["fallback_text"])

    def test_paid_endpoint_requires_multipart_file(self):
        src = (ROOT / "routers" / "operator_payout_requisites.py").read_text()
        paid_fn = src.split("async def mark_allocation_paid")[1].split(
            "async def attach_allocation_receipt"
        )[0]
        self.assertIn("Приложите PDF или фото чека", src)
        self.assertNotIn("execute_sell_paid", paid_fn)
        self.assertIn("client_confirmed_at", src)


if __name__ == "__main__":
    unittest.main()
