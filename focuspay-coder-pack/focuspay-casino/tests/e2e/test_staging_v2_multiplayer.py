"""Disposable staging E2E for the additive casino multiplayer v2 contract."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import asyncpg
import httpx

PLAYER_ONE = 100000001
PLAYER_TWO = 100000002
_PRODUCTION_MARKERS = ("focuspay.org", "153.80.249.77")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise unittest.SkipTest(f"staging E2E requires {name}")
    return value


def _validate_environment() -> tuple[str, str, str]:
    if os.environ.get("ENVIRONMENT", "").lower() != "staging":
        raise unittest.SkipTest("v2 E2E requires staging")
    if os.environ.get("STAGING_E2E") != "1":
        raise unittest.SkipTest("v2 E2E requires explicit STAGING_E2E=1")
    base_url = _required("FOCUSPAY_API_URL")
    database_dsn = _required("DATABASE_DSN")
    token = _required("FOCUSPAY_INTERNAL_TOKEN")
    combined = f"{base_url} {database_dsn}".lower()
    if any(marker in combined for marker in _PRODUCTION_MARKERS):
        raise unittest.SkipTest("production target rejected")
    if urlsplit(base_url).hostname != "backend" or urlsplit(database_dsn).hostname != "postgres":
        raise unittest.SkipTest("only internal disposable compose hosts are allowed")
    return base_url, database_dsn, token


class StagingV2MultiplayerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_url, cls.dsn, cls.token = _validate_environment()
        cls.client_type = importlib.import_module("focuspay_client").FocusPayClient

    async def asyncSetUp(self) -> None:
        self.db = await asyncpg.connect(self.dsn)
        self.client = self.client_type(base_url=self.base_url, internal_token=self.token)

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.db.close()

    def new_id(self, label: str) -> str:
        return f"e2ev2{label}{uuid.uuid4().hex}"[:64]

    async def create(self, label: str, *, max_players: int = 2, bot_count: int = 0, stake: str = "10.00") -> str:
        table_id = self.new_id(label)
        result = await self.client.create_v2_table(
            table_id=table_id,
            game_type="pvp_dice",
            creator_id=PLAYER_ONE,
            stake_rub=stake,
            max_players=max_players,
            bot_count=bot_count,
            expected_state_version=0,
            idempotency_key=f"create-{table_id}",
        )
        self.assertTrue(result["success"])
        return table_id

    async def row(self, table_id: str) -> asyncpg.Record:
        row = await self.db.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1", table_id)
        self.assertIsNotNone(row)
        return row

    async def wait_running(self, table_id: str, *, timeout: float = 20.0) -> asyncpg.Record:
        """Full tables enter ready+countdown; only the v2 closer promotes them to running."""
        row = await self.row(table_id)
        if str(row["status"]) == "ready":
            past = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
            await self.db.execute(
                """UPDATE casino_v2_tables
                   SET game_state = jsonb_set(COALESCE(game_state, '{}'::jsonb), '{starts_at}', $2::jsonb)
                   WHERE table_id=$1 AND status='ready'""",
                table_id,
                json.dumps(past),
            )
        deadline = time.monotonic() + timeout
        last = row
        while time.monotonic() < deadline:
            last = await self.row(table_id)
            if str(last["status"]) == "running":
                return last
            await asyncio.sleep(0.25)
        self.fail(f"{table_id} stayed {last['status']} instead of running after countdown")

    async def assert_released(self, table_id: str, expected_players: int) -> None:
        result = await self.db.fetchrow(
            """SELECT
                (SELECT count(*) FROM casino_v2_table_seats s
                    WHERE s.table_id=t.id AND s.participant_kind='player' AND s.status='seated') AS seated_players,
                (SELECT count(*) FROM casino_v2_house_reservations r WHERE r.table_id=t.id AND r.status='active') AS active_reservation,
                (SELECT count(*) FROM casino_v2_table_seats s
                   JOIN user_cashback_ledger l ON l.order_id='refund-' || s.hold_order_ref
                  WHERE s.table_id=t.id AND s.participant_kind='player' AND l.type='adjustment' AND l.amount_rub=0) AS released_holds
            FROM casino_v2_tables t WHERE t.table_id=$1""",
            table_id,
        )
        self.assertEqual(result["seated_players"], 0)
        self.assertEqual(result["active_reservation"], 0)
        if expected_players:
            self.assertGreaterEqual(result["released_holds"], expected_players)

    async def settle_winner(self, table_id: str, version: int, key: str) -> dict:
        return await self.client.v2_table_operation(
            table_id, "settle", outcome_kind="winner", winner_seat_nos=[1],
            expected_state_version=version, idempotency_key=key,
        )

    async def assert_conflict(self, awaitable) -> None:
        with self.assertRaises(httpx.HTTPStatusError) as context:
            await awaitable
        self.assertEqual(context.exception.response.status_code, 409)

    async def test_schema_and_unstarted_money_release_paths(self) -> None:
        count = await self.db.fetchval(
            """SELECT count(*) FROM information_schema.tables WHERE table_schema='public'
               AND table_name = ANY($1::text[])""",
            ["casino_v2_tables", "casino_v2_table_seats", "casino_v2_house_reservations",
             "casino_v2_settlements", "casino_v2_lifecycle_idempotency",
             "casino_v2_notification_outbox", "casino_v2_house_ledger"],
        )
        self.assertEqual(count, 7)
        indexes = await self.db.fetchval(
            """SELECT count(*) FROM pg_indexes WHERE schemaname='public'
               AND indexname = ANY($1::text[])""",
            ["idx_casino_v2_tables_recovery", "idx_casino_v2_outbox_claim", "idx_casino_v2_house_ledger_table"],
        )
        self.assertEqual(indexes, 3)

        table_id = await self.create("leave", max_players=3, bot_count=1)
        cancelled = await self.client.v2_table_operation(
            table_id, "cancel", telegram_id=PLAYER_ONE, expected_state_version=0, idempotency_key=f"cancel-{table_id}"
        )
        self.assertTrue(cancelled["cancelled"])
        row = await self.row(table_id)
        self.assertEqual(row["status"], "cancelled")
        active_reservation = await self.db.fetchval(
            "SELECT count(*) FROM casino_v2_house_reservations WHERE table_id=$1 AND status='active'",
            int(row["id"]),
        )
        self.assertEqual(active_reservation, 0)

        join_table = await self.create("joinleave", max_players=3, bot_count=0)
        joined = await self.client.v2_table_operation(
            join_table, "seats", telegram_id=PLAYER_TWO, expected_state_version=0, idempotency_key=f"join-{join_table}"
        )
        self.assertEqual(joined["seat_no"], 2)
        version_after_join = int((await self.row(join_table))["state_version"])
        left = await self.client.v2_table_operation(
            join_table, "leave", telegram_id=PLAYER_TWO, expected_state_version=version_after_join, idempotency_key=f"leave-{join_table}"
        )
        self.assertTrue(left["left"])

        expiring = await self.create("expiry", bot_count=1)
        await self.db.execute(
            """UPDATE casino_v2_tables
               SET created_at=now()-interval '25 hours',
                   game_state = jsonb_set(COALESCE(game_state, '{}'::jsonb), '{starts_at}', '"2099-01-01T00:00:00+00:00"'::jsonb)
               WHERE table_id=$1""",
            expiring,
        )
        expired = await self.client.v2_recovery_or_outbox("/v2/tables/expire")
        self.assertIn(expiring, [item["table_id"] for item in expired["expired"]])
        self.assertEqual((await self.row(expiring))["status"], "expired")
        await self.assert_released(expiring, 1)

    async def test_max_six_bot_start_state_persist_and_recovery_lease(self) -> None:
        table_id = await self.create("six", max_players=6, bot_count=5)
        created = await self.row(table_id)
        self.assertEqual(created["status"], "ready")
        self.assertEqual(created["max_seats"], 6)
        seats = await self.db.fetchval("SELECT count(*) FROM casino_v2_table_seats WHERE table_id=$1", created["id"])
        self.assertEqual(seats, 6)
        running = await self.wait_running(table_id)
        self.assertEqual(running["status"], "running")
        await self.assert_conflict(self.client.v2_table_operation(
            table_id, "seats", telegram_id=PLAYER_TWO, expected_state_version=int(running["state_version"]), idempotency_key=f"frozen-{table_id}"
        ))
        persisted = await self.client.v2_table_operation(
            table_id, "persist-state", game_state={"fixture": "persisted"}, expected_state_version=int(running["state_version"]),
            idempotency_key=f"persist-{table_id}"
        )
        self.assertEqual(persisted["table"]["state_version"], int(running["state_version"]) + 1)
        snapshot = await self.client.v2_tables_get("/v2/recovery/snapshot")
        self.assertIn(table_id, [item["table_id"] for item in snapshot["tables"]])
        claimed = await self.client.v2_recovery_or_outbox("/v2/recovery/claim", worker_id="e2ev2recovery", limit=100, lease_seconds=60)
        item = next(item for item in claimed["items"] if item["table"]["table_id"] == table_id)
        self.assertTrue(item["claim_token"])
        completed = await self.client.v2_recovery_or_outbox("/v2/recovery/complete", table_id=table_id, claim_token=item["claim_token"])
        self.assertEqual(completed["table"]["table_id"], table_id)
        table = await self.row(table_id)
        self.assertIsNone(table["recovery_claim_token"])
        self.assertIsNotNone(table["recovery_completed_at"])

    async def test_tie_break_winner_settlement_idempotency_and_outbox_delivery(self) -> None:
        table_id = await self.create("winner", bot_count=1)
        running = await self.wait_running(table_id)
        tie = await self.client.v2_table_operation(
            table_id, "commit-outcome", outcome_kind="tie_break", winner_seat_nos=[1, 2],
            expected_state_version=int(running["state_version"]),
            idempotency_key=f"tie-{table_id}"
        )
        self.assertTrue(tie["tie_break"])
        committed = await self.client.v2_table_operation(
            table_id, "commit-outcome", outcome_kind="winner", winner_seat_nos=[1],
            expected_state_version=int(tie["table"]["state_version"]),
            idempotency_key=f"commit-{table_id}"
        )
        self.assertEqual(committed["table"]["status"], "outcome_committed")
        settled = await self.settle_winner(table_id, int(committed["table"]["state_version"]), f"settle-{table_id}")
        self.assertEqual(settled["pot_rub"], "20.00")
        self.assertEqual(settled["commission_rub"], "1.00")
        replay = await self.settle_winner(table_id, int((await self.row(table_id))["state_version"]), f"settle-replay-{table_id}")
        self.assertTrue(replay["idempotent"])
        counts = await self.db.fetchrow(
            """SELECT
                (SELECT count(*) FROM casino_v2_settlements WHERE table_id=t.id) settlements,
                (SELECT count(*) FROM casino_v2_house_ledger WHERE table_id=t.id) house_ledger,
                (SELECT count(*) FROM casino_v2_notification_outbox WHERE table_id=t.id) outbox
               FROM casino_v2_tables t WHERE t.table_id=$1""", table_id
        )
        self.assertEqual(dict(counts), {"settlements": 1, "house_ledger": 1, "outbox": 1})
        claim = await self.client.v2_recovery_or_outbox("/v2/outbox/claim", worker_id="e2ev2outbox", limit=100, lease_seconds=60)
        message = next(item for item in claim["items"] if item["payload"]["table_id"] == table_id)
        completed = await self.client.v2_recovery_or_outbox("/v2/outbox/complete", outbox_id=message["outbox_id"], claim_token=message["claim_token"])
        self.assertEqual(completed["outbox_id"], message["outbox_id"])
        status = await self.db.fetchval("SELECT status FROM casino_v2_notification_outbox WHERE id=$1", message["outbox_id"])
        self.assertEqual(status, "completed")

    async def test_financial_failure_rolls_back_and_marks_manual_review(self) -> None:
        table_id = await self.create("review", bot_count=1)
        running = await self.wait_running(table_id)
        committed = await self.client.v2_table_operation(
            table_id, "commit-outcome", outcome_kind="winner", winner_seat_nos=[1],
            expected_state_version=int(running["state_version"]), idempotency_key=f"commit-{table_id}",
        )
        await self.db.execute(
            """UPDATE casino_house_accounts account SET reserved_rub=0
               FROM casino_v2_house_reservations reservation
               WHERE reservation.account_id=account.id
                 AND reservation.table_id=(SELECT id FROM casino_v2_tables WHERE table_id=$1)
                 AND reservation.status='active'""",
            table_id,
        )
        await self.assert_conflict(self.settle_winner(table_id, int(committed["table"]["state_version"]), f"settle-{table_id}"))
        result = await self.db.fetchrow(
            """SELECT table_row.status, table_row.recovery_claim_token, table_row.recovery_completed_at,
                      (SELECT count(*) FROM casino_v2_settlements WHERE table_id=table_row.id) AS settlements,
                      (SELECT count(*) FROM casino_v2_notification_outbox WHERE table_id=table_row.id) AS outbox,
                      (SELECT count(*) FROM casino_v2_house_ledger WHERE table_id=table_row.id) AS house_ledger,
                      (SELECT count(*) FROM casino_v2_table_seats seat
                         JOIN user_cashback_ledger ledger ON ledger.order_id='hold-' || seat.hold_order_ref
                        WHERE seat.table_id=table_row.id AND ledger.type='hold') AS retained_holds
               FROM casino_v2_tables table_row WHERE table_row.table_id=$1""",
            table_id,
        )
        self.assertEqual(result["status"], "manual_review")
        self.assertIsNone(result["recovery_claim_token"])
        self.assertIsNotNone(result["recovery_completed_at"])
        self.assertEqual(
            (result["settlements"], result["outbox"], result["house_ledger"], result["retained_holds"]),
            (0, 0, 0, 1),
        )
        claim = await self.client.v2_recovery_or_outbox(
            "/v2/recovery/claim", worker_id="e2ev2manualreview", limit=100, lease_seconds=60,
        )
        self.assertNotIn(table_id, [item["table"]["table_id"] for item in claim["items"]])

    async def test_tie_split_remainder_and_outbox_retry_dead_letter(self) -> None:
        table_id = await self.create("split", max_players=2, stake="10.05")
        joined = await self.client.v2_table_operation(
            table_id, "seats", telegram_id=PLAYER_TWO, expected_state_version=0, idempotency_key=f"join-{table_id}"
        )
        running = await self.wait_running(table_id)
        version_before_commit = int(running["state_version"])
        committed = await self.client.v2_table_operation(
            table_id,
            "commit-outcome",
            outcome_kind="tie_split",
            winner_seat_nos=[1, 2],
            expected_state_version=version_before_commit,
            idempotency_key=f"commit-{table_id}",
        )
        settled = await self.client.v2_table_operation(
            table_id,
            "settle",
            outcome_kind="tie_split",
            winner_seat_nos=[1, 2],
            expected_state_version=int(committed["table"]["state_version"]),
            idempotency_key=f"settle-{table_id}",
        )
        self.assertEqual(
            settled["payouts"],
            [{"seat_no": 1, "amount_rub": "9.55"}, {"seat_no": 2, "amount_rub": "9.54"}],
        )
        outbox_id = await self.db.fetchval(
            "SELECT id FROM casino_v2_notification_outbox WHERE table_id=(SELECT id FROM casino_v2_tables WHERE table_id=$1) ORDER BY id LIMIT 1", table_id
        )
        for attempt in range(10):
            await self.db.execute("UPDATE casino_v2_notification_outbox SET available_at=now() WHERE id=$1", outbox_id)
            claim = await self.client.v2_recovery_or_outbox("/v2/outbox/claim", worker_id=f"e2ev2retry{attempt}", limit=100, lease_seconds=60)
            message = next(item for item in claim["items"] if item["outbox_id"] == outbox_id)
            failed = await self.client.v2_recovery_or_outbox(
                "/v2/outbox/fail", outbox_id=outbox_id, claim_token=message["claim_token"], error="synthetic retry"
            )
        self.assertEqual(failed["status"], "dead")
        status, attempts = await self.db.fetchrow("SELECT status, attempts FROM casino_v2_notification_outbox WHERE id=$1", outbox_id)
        self.assertEqual((status, attempts), ("dead", 10))

    async def test_disposable_contract_disables_real_telegram_and_payments(self) -> None:
        self.assertEqual(os.environ.get("STAGING_DISABLE_BACKGROUND_TASKS"), "true")
        telegram_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        self.assertEqual(telegram_token, "123456:synthetic-test-only-not-a-real-token")
        for name in ("PAYFAST_URL", "PAYFAST_API_URL", "PAYFAST_BASE_URL"):
            value = (os.environ.get(name) or "").strip()
            self.assertTrue(not value or "unavailable-payfast" in value, f"{name} must not target real payments")


if __name__ == "__main__":
    unittest.main()
