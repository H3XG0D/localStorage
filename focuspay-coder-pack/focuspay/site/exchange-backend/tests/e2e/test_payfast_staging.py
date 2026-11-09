from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "site" / "exchange-backend"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from test_support.e2e_payfast.runner import (  # noqa: E402
    DSN_VARIABLE,
    OPT_IN_FLAG,
    E2EConfig,
    E2EConfigurationError,
    assert_payment_schema,
    callback_receiver,
    deal_snapshot,
    deny_external_network,
    hmac_headers,
    isolated_backend_import_directory,
    loopback_url,
    payfast_review_count,
    principal_ledger_count,
    raw_json,
    seed_payfast_e2e_fixture,
    start_real_app,
)
from test_support.fake_payfast_http import FakePayFastHttp  # noqa: E402


if os.environ.get(OPT_IN_FLAG) != "1":
    raise unittest.SkipTest(f"opt-in only: set {OPT_IN_FLAG}=1")
if importlib.util.find_spec("asyncpg") is None:
    raise unittest.SkipTest("dependency blocker: asyncpg is unavailable in this test environment")


class PayFastStagingE2E(unittest.IsolatedAsyncioTestCase):
    """True HTTP contracts against a synthetic, explicitly supplied disposable DB."""

    api_key = "e2e-payfast-api-key"
    api_secret = "e2e-payfast-api-secret"
    internal_secret = "e2e-payfast-internal-secret"

    async def asyncSetUp(self) -> None:
        self.config = E2EConfig.from_environment()
        self._backend_import_directory = isolated_backend_import_directory()
        self._backend_import_directory.__enter__()
        import asyncpg

        self.conn = await asyncpg.connect(self.config.dsn)
        await assert_payment_schema(self.conn)
        unique = uuid.uuid4().hex
        self.api_key = f"e2e-payfast-{unique}"
        self.api_secret = f"e2e-secret-{unique}"
        self.exchanger_id = await seed_payfast_e2e_fixture(
            self.conn, api_key=self.api_key, api_secret=self.api_secret
        )
        self.fake_context = FakePayFastHttp()
        self.fake = self.fake_context.__enter__()
        self._loop = asyncio.get_running_loop()
        self.callback_context = callback_receiver(self._handle_fake_callback)
        self.callback = self.callback_context.__enter__()

        import config

        self.settings_patch = patch.multiple(
            config.settings,
            database_dsn=self.config.dsn,
            merchant_base_url=self.fake.base_url,
            merchant_api_key=self.fake.api_key,
            merchant_secret_key=self.fake.secret_key,
            merchant_callback_url=self.callback.url,
            internal_api_secret=self.internal_secret,
            webhook_secret="",
            telegram_bot_token="",
        )
        self.settings_patch.start()
        from db import init_db

        await init_db(self.config.dsn)
        self.app, self.public = await start_real_app()
        from httpx import ASGITransport, AsyncClient

        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://127.0.0.1")

    async def asyncTearDown(self) -> None:
        if hasattr(self, "client"):
            await self.client.aclose()
        if "db" in sys.modules:
            from db import close_db

            await close_db()
        if hasattr(self, "settings_patch"):
            self.settings_patch.stop()
        if hasattr(self, "callback_context"):
            self.callback_context.__exit__(None, None, None)
        if hasattr(self, "fake_context"):
            self.fake_context.__exit__(None, None, None)
        if hasattr(self, "conn"):
            await self.conn.close()
        if hasattr(self, "_backend_import_directory"):
            self._backend_import_directory.__exit__(None, None, None)

    def _handle_fake_callback(self, raw: bytes) -> int:
        try:
            payload = json.loads(raw.decode("utf-8"))
            merchant_ref = str(payload["client_transaction_id"])
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return 400
        future = asyncio.run_coroutine_threadsafe(
            self.settled(merchant_ref, payload), self._loop
        )
        try:
            status, _result = future.result(timeout=5)
        except Exception:
            return 500
        return status

    async def signed_post(self, path: str, payload: dict) -> tuple[int, dict]:
        body = raw_json(payload)
        response = await self.client.post(path, content=body, headers=hmac_headers(self.api_key, self.api_secret, body))
        return response.status_code, response.json()

    async def settled(self, merchant_ref: str, webhook_body: dict | None = None) -> tuple[int, dict]:
        response = await self.client.post(
            "/api/internal/external/deals/payfast-settled-by-ref",
            json={"merchant_ref": merchant_ref, "webhook_body": webhook_body},
            headers={"X-Internal-Token": self.internal_secret},
        )
        return response.status_code, response.json()

    async def create_deal(self, suffix: str) -> tuple[int, dict]:
        with deny_external_network():
            status, body = await self.signed_post(
                "/api/exchanger/v1/deals",
                {
                    "amount_rub": 1000,
                    "crypto": "usdt",
                    "sub_token": "SBPRUB",
                    "client_transaction_id": f"e2e-{suffix}",
                    "fingerprint": "e2e-synthetic",
                    "callback_url": self.callback.url,
                },
            )
        self.assertEqual(status, 201, body)
        return int(body["deal_id"]), body

    async def ready_for_settlement(self, suffix: str) -> tuple[int, str, str]:
        deal_id, body = await self.create_deal(suffix)
        merchant_uuid = body["payment"]["merchant_uuid"]
        client_transaction_id = f"e2e-{suffix}"
        status, paid = await self.signed_post(f"/api/exchanger/v1/deals/{deal_id}/paid", {})
        self.assertEqual(status, 200, paid)
        with deny_external_network():
            status, receipt = await self.signed_post(
                f"/api/exchanger/v1/deals/{deal_id}/receipt",
                {"file": "http://127.0.0.1:1/synthetic-receipt.pdf"},
            )
        self.assertEqual(status, 200, receipt)
        return deal_id, merchant_uuid, client_transaction_id

    async def deliver_callback(self, merchant_uuid: str, *, repeats: int = 1, **overrides: object) -> list[int]:
        with deny_external_network():
            return await asyncio.to_thread(
                self.fake.deliver_callback,
                self.callback.url,
                merchant_uuid,
                repeats=repeats,
                **overrides,
            )

    async def test_create_payin_persists_separate_merchant_uuid_and_local_id(self) -> None:
        deal_id, body = await self.create_deal("create")
        merchant_uuid = body["payment"]["merchant_uuid"]
        row = await deal_snapshot(self.conn, deal_id)

        self.assertEqual(row["status"], "awaiting_receipt")
        self.assertEqual(row["client_transaction_id"], "e2e-create")
        self.assertEqual(row["merchant_order_id"], row["client_transaction_id"])
        self.assertEqual(self.fake.requests[0].payload["client_transaction_id"], row["client_transaction_id"])
        self.assertNotEqual(merchant_uuid, row["client_transaction_id"])
        self.assertEqual(row["payment_snapshot"]["merchant_uuid"], merchant_uuid)
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 0)
        self.assertEqual(self.fake.requests[0].path, "/create_order_payin")

    async def test_delayed_bill_rechecks_and_never_credits_before_authoritative_paid_state(self) -> None:
        self.fake.delay_next_created_bill()
        deal_id, body = await self.create_deal("delayed-bill")
        merchant_uuid = body["payment"]["merchant_uuid"]
        self.assertTrue(body["payment"]["bill"])
        self.assertEqual(sum(r.path == "/create_order_payin" for r in self.fake.requests), 1)
        self.assertEqual(sum(r.path == "/get_order" for r in self.fake.requests), 1)
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 0)
        self.assertEqual(self.fake.order(merchant_uuid)["status"], "ACCEPTED")

    async def test_callback_is_signal_then_authoritative_get_order_confirms_once(self) -> None:
        deal_id, merchant_uuid, _ = await self.ready_for_settlement("callback")
        self.fake.set_order_state(merchant_uuid, status="ACCEPTED", status_file=None)
        callbacks_before = len(self.callback.requests)

        statuses = await self.deliver_callback(merchant_uuid)
        self.assertEqual(statuses, [200])
        self.assertEqual(len(self.callback.requests), callbacks_before + 1)
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 0)

        self.fake.set_order_state(merchant_uuid, status="PAID", status_file=0)
        statuses = await self.deliver_callback(merchant_uuid)
        self.assertEqual(statuses, [200])
        self.assertEqual(len(self.callback.requests), callbacks_before + 2)
        self.assertNotEqual((await deal_snapshot(self.conn, deal_id))["status"], "confirmed")
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 0)

        self.fake.set_order_state(merchant_uuid, status="SUCCSES", status_file=0)
        statuses = await self.deliver_callback(merchant_uuid)
        self.assertEqual(statuses, [200])
        self.assertEqual(len(self.callback.requests), callbacks_before + 3)
        self.assertEqual((await deal_snapshot(self.conn, deal_id))["status"], "confirmed")
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 1)
        self.assertGreaterEqual(sum(r.path == "/get_order" for r in self.fake.requests), 2)

    async def test_duplicate_callback_is_ledger_idempotent(self) -> None:
        deal_id, merchant_uuid, _ = await self.ready_for_settlement("duplicate")
        self.fake.set_order_state(merchant_uuid, status="SUCCSES", status_file=0)
        statuses = await self.deliver_callback(merchant_uuid, repeats=2)
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(len(self.callback.requests), 3)
        row = await deal_snapshot(self.conn, deal_id)
        self.assertEqual(row["status"], "confirmed")
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 1)

    async def test_unknown_merchant_uuid_never_credits_and_records_review(self) -> None:
        status, unknown = await self.settled("missing-merchant-uuid")
        self.assertEqual(status, 200, unknown)
        self.assertEqual(unknown, {"skipped": True, "reason": "deal_not_found"})
        self.assertEqual(
            await payfast_review_count(
                self.conn,
                merchant_ref="missing-merchant-uuid",
                incident_type="unknown_callback",
            ),
            1,
        )

    async def test_callback_uuid_amount_or_payload_mismatch_never_credits_and_records_review(self) -> None:
        cases = (
            ("uuid", {"uuid": "wrong-merchant-uuid"}),
            ("client", {"client_transaction_id": "wrong-client-transaction-id"}),
            ("amount", {"amount": 1001}),
            ("nested-amount", {"data_order": {"amount": 1001}}),
        )
        for suffix, overrides in cases:
            with self.subTest(suffix=suffix):
                deal_id, merchant_uuid, _ = await self.ready_for_settlement(f"mismatch-{suffix}")
                statuses = await self.deliver_callback(merchant_uuid, **overrides)
                self.assertEqual(statuses, [200])
                self.assertEqual((await deal_snapshot(self.conn, deal_id))["status"], "pending")
                self.assertEqual(await principal_ledger_count(self.conn, deal_id), 0)
                if suffix == "client":
                    self.assertEqual(
                        await payfast_review_count(
                            self.conn,
                            merchant_ref="wrong-client-transaction-id",
                            incident_type="unknown_callback",
                        ),
                        1,
                    )
                else:
                    self.assertEqual(
                        await payfast_review_count(
                            self.conn, deal_id=deal_id, incident_type="callback_mismatch"
                        ),
                        1,
                    )

    async def test_retryable_receipt_failure_keeps_ledger_and_does_not_fetch_receipt_url(self) -> None:
        deal_id, body = await self.create_deal("retry")
        merchant_uuid = body["payment"]["merchant_uuid"]
        status, _ = await self.signed_post(f"/api/exchanger/v1/deals/{deal_id}/paid", {})
        self.assertEqual(status, 200)
        self.fake.reject_next_receipt(merchant_uuid)
        with deny_external_network():
            status, rejected = await self.signed_post(
                f"/api/exchanger/v1/deals/{deal_id}/receipt",
                {"file": "http://127.0.0.1:1/receipt-never-fetched.pdf"},
            )
        self.assertEqual(status, 503, rejected)
        row = await deal_snapshot(self.conn, deal_id)
        self.assertEqual(row["status"], "awaiting_receipt")
        self.assertIsNone(row["receipt_submitted_at"])
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 0)
        self.assertEqual(self.fake.order(merchant_uuid)["extra_info"]["file"], None)

    async def test_receipt_rejected_permanent_records_review_outcome(self) -> None:
        deal_id, body = await self.create_deal("permanent-receipt")
        merchant_uuid = body["payment"]["merchant_uuid"]
        status, _ = await self.signed_post(f"/api/exchanger/v1/deals/{deal_id}/paid", {})
        self.assertEqual(status, 200)
        self.fake.queue_receipt_failure(
            merchant_uuid,
            status=400,
            body={"status_pending": "error", "error": "receipt rejected"},
        )
        status, rejected = await self.signed_post(
            f"/api/exchanger/v1/deals/{deal_id}/receipt",
            {"file": "http://127.0.0.1:1/permanent-receipt.pdf"},
        )
        self.assertEqual(status, 400, rejected)
        row = await deal_snapshot(self.conn, deal_id)
        self.assertEqual(row["status"], "awaiting_receipt")
        self.assertIsNone(row["receipt_submitted_at"])
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 0)
        self.assertEqual(
            await payfast_review_count(
                self.conn, deal_id=deal_id, incident_type="receipt_rejected_permanent"
            ),
            1,
        )

    async def test_post_completion_provider_error_keeps_ledger_status_and_records_review(self) -> None:
        deal_id, merchant_uuid, _ = await self.ready_for_settlement("provider-error")
        self.fake.set_order_state(merchant_uuid, status="SUCCSES", status_file=0)
        status, settled = await self.settled(merchant_uuid)
        self.assertEqual(status, 200, settled)
        self.assertTrue(settled["confirmed"])
        self.assertEqual((await deal_snapshot(self.conn, deal_id))["status"], "confirmed")
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 1)
        statuses = await self.deliver_callback(
            merchant_uuid,
            data_order={"status": "ERROR", "uuid_system": merchant_uuid},
        )
        self.assertEqual(statuses, [200])
        self.assertEqual((await deal_snapshot(self.conn, deal_id))["status"], "confirmed")
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 1)
        self.assertEqual(
            await payfast_review_count(
                self.conn, deal_id=deal_id, incident_type="post_completion_provider_error"
            ),
            1,
        )

    async def test_idempotent_recovery_and_reconcile_keep_single_ledger_entry(self) -> None:
        deal_id, merchant_uuid, _ = await self.ready_for_settlement("reconcile")
        self.fake.set_order_state(merchant_uuid, status="SUCCSES", status_file=0)
        await self.conn.execute(
            "UPDATE external_deals SET receipt_submitted_at = now() - interval '2 minutes' WHERE id = $1",
            deal_id,
        )
        from external_deal_payin import (
            get_external_deals_for_payfast_reconcile,
            try_auto_confirm_external_deal_on_payfast,
        )

        candidates = await get_external_deals_for_payfast_reconcile(self.conn, min_age_sec=90)
        self.assertIn(deal_id, {int(row["id"]) for row in candidates})
        with deny_external_network():
            first = await try_auto_confirm_external_deal_on_payfast(self.conn, deal_id)
            second = await try_auto_confirm_external_deal_on_payfast(self.conn, deal_id)
        self.assertTrue(first["confirmed"])
        self.assertEqual(second["reason"], "already_confirmed")
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 1)
        statuses = await self.deliver_callback(merchant_uuid, repeats=2)
        self.assertEqual(statuses, [200, 200])
        self.assertEqual((await deal_snapshot(self.conn, deal_id))["status"], "confirmed")
        self.assertEqual(await principal_ledger_count(self.conn, deal_id), 1)

    async def test_loopback_guard_fails_closed(self) -> None:
        with self.assertRaises(E2EConfigurationError):
            loopback_url("https://example.invalid/receipt.pdf")


if __name__ == "__main__":
    unittest.main()
