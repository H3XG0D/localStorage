from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import contextlib
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from casino_finance import SettlementRequest, canonical_casino_settings


async def _dependency_stub(*args, **kwargs):
    raise AssertionError("Database dependency must be patched in unit tests")


sys.modules.setdefault("db", types.SimpleNamespace(get_pool=_dependency_stub))
import routers.internal_casino as internal_casino
# internal_casino already captured get_pool; do not leak the dependency stub to
# unrelated tests collected in the same pytest process.
if isinstance(sys.modules.get("db"), types.SimpleNamespace):
    sys.modules.pop("db", None)
from routers.internal_casino import (
    CasinoGameCreateRequest,
    CasinoGameJoinRequest,
    CasinoDmPvpCreateRequest,
    InvitationOutboxCompleteRequest,
    CasinoGameIdRequest,
    CasinoGameOutcomeRequest,
    CasinoGameStateRequest,
    ClaimRequest,
    DepositCreditRequest,
    OutboxFailRequest,
    GameChatBindingPendingRequest,
    active_game_chat_binding_with_conn,
    create_pvp_from_dm_with_conn,
    create_or_resume_game_with_conn,
    enqueue_web_duel_invitation_with_conn,
    join_and_hold_game_with_conn,
    claim_pvp_invitation_outbox_with_conn,
    complete_pvp_invitation_outbox_with_conn,
    fail_pvp_invitation_outbox_with_conn,
    create_pending_game_chat_binding_with_conn,
    claim_outbox_with_conn,
    commit_game_outcome_with_conn,
    credit_deposit_with_conn,
    persist_game_state_with_conn,
    release_game_with_conn,
    settle_committed_outcome_with_conn,
    settle_game_with_conn,
    prepare_cub_with_conn,
    PrepareCubRequest,
    CubPlayRequest,
    CubOpenRequest,
    CubResolveRequest,
    CardsDealRequest,
    CardsPrepareRequest,
    CardsRevealRequest,
    open_cub_with_conn,
    pending_cub_with_conn,
    resolve_cub_with_conn,
    prepare_cards_with_conn,
    deal_cards_with_conn,
    reveal_cards_with_conn,
    V2TableCreateRequest,
    V2TableStartRequest,
    V2TableSettleRequest,
    V2TableAddBotRequest,
    V2TableJoinRequest,
    V2TableLeaveRequest,
    V2CardsDealRequest,
    _seat_v2_bots_with_conn,
    add_v2_bot_with_conn,
    join_v2_table_with_conn,
    create_v2_table_with_conn,
    active_v2_tables_with_conn,
    recovery_snapshot_v2_with_conn,
    _v2_table_response_with_conn,
    start_v2_table_with_conn,
    settle_v2_table_with_conn,
)
from routers.internal_casino import (
    _credit_amount_from_deposit,
    _telegram_id_from_deposit_transaction_id,
)


class HouseRngCommitTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_persists_commit_that_matches_revealed_seed(self):
        conn = types.SimpleNamespace(execute=AsyncMock())
        result = await prepare_cub_with_conn(conn, PrepareCubRequest(telegram_id=777))
        self.assertTrue(result["success"])
        self.assertEqual(len(result["rng_commit"]), 64)
        query, game_id, commit, telegram_id, seed = conn.execute.await_args.args
        self.assertIn("casino_house_rng_commits", query)
        self.assertEqual(telegram_id, 777)
        self.assertEqual(game_id, result["game_id"])
        self.assertEqual(commit, internal_casino._house_rng_commit(seed, game_id))

    def test_web_client_user_id_can_prepare_and_play_cub(self):
        PrepareCubRequest(telegram_id=-3)
        CubPlayRequest(game_id="cub-web", telegram_id=-3, stake_rub=Decimal("100"))
        with self.assertRaises(ValidationError):
            PrepareCubRequest(telegram_id=0)
        with self.assertRaises(ValidationError):
            CubPlayRequest(game_id="cub-web", telegram_id=0, stake_rub=Decimal("100"))

    def test_commit_cannot_be_reproduced_with_another_game_id(self):
        seed = "a" * 64
        self.assertNotEqual(
            internal_casino._house_rng_commit(seed, "game-a"),
            internal_casino._house_rng_commit(seed, "game-b"),
        )

    def test_new_format_credits_target_not_full_payment(self):
        tx = "casino-dep-777-c100000-abc123"
        self.assertEqual(_telegram_id_from_deposit_transaction_id(tx), 777)
        # Оплачено 1210 (1000 + 21%), на баланс — целевые 1000.
        self.assertEqual(
            _credit_amount_from_deposit(tx, Decimal("1210.00")), Decimal("1000.00")
        )

    def test_legacy_format_credits_full_payment(self):
        tx = "casino-dep-777-abc123"
        self.assertEqual(_telegram_id_from_deposit_transaction_id(tx), 777)
        self.assertEqual(
            _credit_amount_from_deposit(tx, Decimal("1000.00")), Decimal("1000.00")
        )

    def test_credit_exceeding_payment_is_rejected(self):
        tx = "casino-dep-777-c200000-abc123"
        with self.assertRaises(HTTPException):
            _credit_amount_from_deposit(tx, Decimal("1210.00"))

    def test_invalid_transaction_id_is_rejected(self):
        with self.assertRaises(HTTPException):
            _telegram_id_from_deposit_transaction_id("not-a-casino-deposit")




class DmPvpRequestTests(unittest.IsolatedAsyncioTestCase):
    def test_request_accepts_client_rolls_alias_and_emits_rounds(self):
        request = CasinoDmPvpCreateRequest.model_validate({
            "game_id": "dm-game-1", "game_type": "pvp_dice", "creator_id": 7,
            "stake_rub": "100", "rolls": 3,
        })
        self.assertEqual(request.rounds, 3)
        self.assertEqual(request.model_dump()["rounds"], 3)
        with self.assertRaises(ValidationError):
            CasinoDmPvpCreateRequest.model_validate({
                "game_id": "dm-game-1", "game_type": "baccara", "creator_id": 7,
                "stake_rub": "100",
            })

    async def test_create_from_dm_fails_before_holding_without_binding(self):
        conn = types.SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(side_effect=[None, None]))
        body = CasinoDmPvpCreateRequest(game_id="dm-game-1", game_type="pvp_dice", creator_id=7, stake_rub="100")
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ):
            with self.assertRaises(HTTPException) as raised:
                await create_pvp_from_dm_with_conn(conn, body)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(conn.execute.await_count, 1)
        self.assertIn("741921", conn.execute.await_args.args[0])

    async def test_create_from_dm_rejects_idempotency_replay_with_different_rounds(self):
        existing = {
            "game_id": "dm-game-1", "game_type": "pvp_dice", "creator_id": 7,
            "bet_rub": Decimal("100"), "game_data": {"pvp": {"rounds": 2}},
        }
        conn = types.SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(return_value=existing))
        body = CasinoDmPvpCreateRequest(
            game_id="dm-game-1", game_type="pvp_dice", creator_id=7, stake_rub="100", rounds=3,
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ):
            with self.assertRaises(HTTPException) as raised:
                await create_pvp_from_dm_with_conn(conn, body)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Existing game conflicts")

    async def test_invitation_claim_and_complete_return_delivery_contract(self):
        now = datetime(2026, 8, 27, tzinfo=timezone.utc)
        claimed = {"id": 5, "game_id": "dm-game-1", "chat_id": -100123, "payload": json.dumps({"rounds": 2}), "attempts": 1, "claimed_at": now}
        completed_outbox = {"id": 5, "game_id": "dm-game-1", "telegram_message_id": 42, "completed_at": now}
        completed_game = {"game_id": "dm-game-1"}
        conn = types.SimpleNamespace(
            fetch=AsyncMock(return_value=[claimed]),
            fetchrow=AsyncMock(side_effect=[completed_outbox, completed_game]),
        )
        result = await claim_pvp_invitation_outbox_with_conn(conn, ClaimRequest(worker_id="bot"))
        self.assertEqual(result["items"][0]["chat_id"], -100123)
        self.assertEqual(result["items"][0]["payload"]["rounds"], 2)
        self.assertIn("SKIP LOCKED", conn.fetch.await_args.args[0])
        completed = await complete_pvp_invitation_outbox_with_conn(conn, InvitationOutboxCompleteRequest(
            outbox_id=5, claim_token=result["items"][0]["claim_token"], telegram_message_id=42,
        ))
        self.assertEqual(completed["telegram_message_id"], 42)
        outbox_query, *outbox_args = conn.fetchrow.await_args_list[0].args
        game_query, *game_args = conn.fetchrow.await_args_list[1].args
        self.assertIn("SET status = 'completed'", outbox_query)
        self.assertEqual(outbox_args, [5, result["items"][0]["claim_token"], 42])
        self.assertIn("UPDATE casino_games", game_query)
        self.assertIn("game_state = jsonb_build_object", game_query)
        self.assertIn("state_version = state_version + 1", game_query)
        self.assertEqual(game_args, ["dm-game-1", 42])

    def test_completion_snapshot_sql_maps_game_type_and_rounds(self):
        # The snapshot is built in SQL, so protect each CASE branch directly.
        source = Path(internal_casino.__file__).read_text()
        cases = [
            ("pvp_dice", 1, "cub"), ("pvp_dice", 2, "2cub"),
            ("pvp_darts", 1, "darts"), ("pvp_darts", 2, "2darts"),
            ("pvp_bowling", 1, "boul"), ("pvp_bowling", 2, "2boul"),
            ("pvp_football", 1, "fut"), ("pvp_football", 2, "2fut"),
            ("pvp_basketball", 1, "basket"), ("pvp_basketball", 2, "2basket"),
            ("baccara", 0, "baccara"), ("blackjack", 0, "blackjack"),
        ]
        for game_type, rounds, snapshot_type in cases:
            branch = (
                f"WHEN game_type = '{game_type}' "
                f"AND COALESCE((game_data #>> '{{pvp,rounds}}')::integer, 1) = 2 THEN '{snapshot_type}'"
                if rounds == 2
                else f"WHEN game_type = '{game_type}' THEN '{snapshot_type}'"
            )
            with self.subTest(game_type=game_type, rounds=rounds):
                self.assertIn(branch, source)

    async def test_complete_invitation_endpoint_wraps_outbox_and_snapshot_in_transaction(self):
        class Transaction:
            def __init__(self):
                self.enter = AsyncMock(return_value=None)
                self.exit = AsyncMock(return_value=False)

            async def __aenter__(self):
                return await self.enter()

            async def __aexit__(self, *args):
                return await self.exit(*args)

        class Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                return False

        transaction = Transaction()
        conn = types.SimpleNamespace(transaction=lambda: transaction)
        pool = types.SimpleNamespace(acquire=lambda: Acquire())

        async def get_pool():
            return pool

        with patch.object(internal_casino, "_verify_internal_token"), \
                patch.object(internal_casino, "get_pool", get_pool), \
                patch.object(internal_casino, "complete_pvp_invitation_outbox_with_conn", new=AsyncMock(return_value={"success": True})) as complete:
            result = await internal_casino.complete_pvp_invitation(
                InvitationOutboxCompleteRequest(outbox_id=5, claim_token="claim", telegram_message_id=42),
                x_internal_token="internal",
            )

        self.assertEqual(result, {"success": True})
        transaction.enter.assert_awaited_once()
        transaction.exit.assert_awaited_once_with(None, None, None)
        complete.assert_awaited_once_with(conn, unittest.mock.ANY)



class GameChatBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_binding_is_strict_and_normalizes_title(self):
        request = GameChatBindingPendingRequest.model_validate(
            {
                "chat_id": -100123,
                "chat_type": "supergroup",
                "chat_title": "  Games  ",
                "telegram_url": " https://t.me/+abcdefghijklmnop ",
                "requested_by_telegram_id": 7,
            }
        )
        self.assertEqual(request.chat_title, "Games")
        self.assertEqual(request.telegram_url, "https://t.me/+abcdefghijklmnop")
        with self.assertRaises(ValidationError):
            GameChatBindingPendingRequest.model_validate(
                {
                    "chat_id": -100123,
                    "chat_type": "supergroup",
                    "telegram_url": "https://t.me.evil.example/games",
                    "requested_by_telegram_id": 7,
                }
            )
        with self.assertRaises(ValidationError):
            GameChatBindingPendingRequest.model_validate(
                {
                    "chat_id": 7,
                    "chat_type": "channel",
                    "requested_by_telegram_id": 7,
                }
            )

    async def test_pending_binding_upserts_without_activating(self):
        now = datetime(2026, 8, 22, tzinfo=timezone.utc)
        row = {
            "id": 3, "chat_id": -100123, "chat_type": "supergroup",
            "chat_title": "Games", "telegram_url": "https://t.me/games", "status": "pending", "requested_by_telegram_id": 7,
            "created_at": now, "updated_at": now,
        }
        conn = types.SimpleNamespace(fetchrow=AsyncMock(return_value=row))
        result = await create_pending_game_chat_binding_with_conn(
            conn,
            GameChatBindingPendingRequest(
                chat_id=-100123, chat_type="supergroup", chat_title="Games",
                telegram_url="https://t.me/games", requested_by_telegram_id=7
            ),
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["binding"]["status"], "pending")
        self.assertIn("ON CONFLICT (chat_id)", conn.fetchrow.await_args.args[0])
        self.assertIn("status = 'active' THEN 'active'", conn.fetchrow.await_args.args[0])
        self.assertIn("telegram_url", conn.fetchrow.await_args.args[0])

    async def test_active_binding_returns_only_active_row(self):
        conn = types.SimpleNamespace(fetchrow=AsyncMock(return_value=None))
        result = await active_game_chat_binding_with_conn(conn)
        self.assertEqual(result, {"success": True, "binding": None})
        self.assertIn("WHERE status = 'active'", conn.fetchrow.await_args.args[0])


FINISHED_GAME = {
    "id": 41,
    "game_id": "game-1",
    "game_type": "pvp_dice",
    "creator_id": 1001,
    "opponent_id": 1002,
    "bet_rub": Decimal("100.00"),
    "settlement_base_rub": Decimal("100.00"),
    "commission_rub": Decimal("15.00"),
    "payout_rub": Decimal("185.00"),
    "winner_id": 1001,
    "creator_hold_id": "casino-game-1-creator",
    "opponent_hold_id": "casino-game-1-opponent",
    "status": "finished",
    "finished_at": datetime(2026, 8, 21, tzinfo=timezone.utc),
}


def valid_request(**overrides):
    payload = {
        "game_id": "game-1",
        "game_type": "pvp_dice",
        "creator_id": 1001,
        "opponent_id": 1002,
        "winner_id": 1001,
        "creator_hold_id": "casino-game-1-creator",
        "opponent_hold_id": "casino-game-1-opponent",
        "stake_rub": "100.00",
    }
    payload.update(overrides)
    return SettlementRequest.model_validate(payload)


class RetryConn:
    def __init__(self):
        self.execute = AsyncMock()
        self.fetchrow = AsyncMock(return_value=FINISHED_GAME)
        self.fetch = AsyncMock()
        self.fetchval = AsyncMock()


class RetryIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_finished_retry_returns_persisted_result_without_financial_writes(self):
        conn = RetryConn()

        result = await settle_game_with_conn(conn, valid_request())

        self.assertTrue(result["success"])
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["game_id"], "game-1")
        self.assertEqual(result["commission_rub"], "15.00")
        self.assertEqual(result["payout_rub"], "185.00")
        self.assertEqual(conn.execute.await_count, 1)
        self.assertIn("pg_advisory_xact_lock", conn.execute.await_args.args[0])
        conn.fetch.assert_not_awaited()
        conn.fetchval.assert_not_awaited()
    async def test_finished_retry_rejects_a_conflicting_payload_before_returning_cached_result(self):
        for field, value in (
            ("winner_id", 1002),
            ("creator_hold_id", "casino-game-1-other-creator"),
            ("opponent_hold_id", "casino-game-1-other-opponent"),
            ("stake_rub", "101.00"),
        ):
            with self.subTest(field=field):
                conn = RetryConn()
                with self.assertRaises(HTTPException) as raised:
                    await settle_game_with_conn(conn, valid_request(**{field: value}))

                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(conn.execute.await_count, 1)
                conn.fetch.assert_not_awaited()


class DepositCreditConn:
    def __init__(self, *, deal=None, audit=None, legacy=None, ledger=None, inserted_ledger=None):
        self.deal = deal if deal is not None else {
            "id": 321,
            "exchanger_id": 77,
            "status": "confirmed",
            "client_transaction_id": "casino-dep-123456789-secure_nonce",
            "amount_rub": Decimal("150.25"),
            "sub_token": "SBPRUB",
        }
        self.audit = audit
        self.legacy = legacy
        self.ledger = ledger
        self.inserted_ledger = inserted_ledger
        self.execute = AsyncMock()
        self.fetch = AsyncMock(return_value=[])
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _fetchrow(self, query, *args):
        if "FROM external_deals" in query:
            return self.deal
        if "FROM casino_settings" in query and "wagering_percent" in query:
            # Порог отыгрыша берётся из настроек; в тесте — дефолт (нет строки).
            return None
        if "FROM casino_deposit_credits" in query:
            return self.audit
        if "FROM user_cashback_ledger" in query and "AND type = 'accrual'" in query:
            return self.legacy
        if "INSERT INTO user_cashback_ledger" in query:
            return self.inserted_ledger
        if "SELECT user_id, amount_rub FROM user_cashback_ledger" in query:
            return self.ledger
        raise AssertionError(f"Unexpected query: {query}")


class DepositCreditTests(unittest.IsolatedAsyncioTestCase):
    def _request(self):
        return DepositCreditRequest(deal_id=321)

    async def test_credits_confirmed_deal_from_configured_exchanger(self):
        conn = DepositCreditConn(
            inserted_ledger={"user_id": 123456789, "amount_rub": Decimal("150.25")}
        )

        with patch.object(internal_casino.settings, "casino_exchanger_id", 77):
            result = await credit_deposit_with_conn(conn, self._request())

        self.assertEqual(
            result,
            {
                "success": True,
                "idempotent": False,
                "deal_id": 321,
                "telegram_id": 123456789,
                "amount_rub": "150.25",
                "status": "credited",
            },
        )
        self.assertEqual(conn.execute.await_count, 4)
        self.assertIn("pg_advisory_xact_lock", conn.execute.await_args_list[0].args[0])
        self.assertIn("casino-user", conn.execute.await_args_list[1].args[0])
        self.assertIn("INSERT INTO casino_deposit_credits", conn.execute.await_args_list[2].args[0])
        self.assertEqual(conn.execute.await_args_list[2].args[7], "fiat")
        # Депозит зачислен по номиналу и заперт к выводу до отыгрыша.
        self.assertIn("INSERT INTO casino_wagering_locks", conn.execute.await_args_list[3].args[0])

    async def test_crypto_sub_token_sets_crypto_rail(self):
        conn = DepositCreditConn(
            deal={
                "id": 321,
                "exchanger_id": 77,
                "status": "confirmed",
                "client_transaction_id": "casino-dep-123456789-secure_nonce",
                "amount_rub": Decimal("150.25"),
                "sub_token": "USDT",
            },
            inserted_ledger={"user_id": 123456789, "amount_rub": Decimal("150.25")},
        )
        with patch.object(internal_casino.settings, "casino_exchanger_id", 77):
            await credit_deposit_with_conn(conn, self._request())
        self.assertEqual(conn.execute.await_args_list[2].args[7], "crypto")

    async def test_existing_matching_audit_row_is_idempotent_without_ledger_write(self):
        conn = DepositCreditConn(
            audit={
                "deal_id": 321,
                "exchanger_id": 77,
                "telegram_id": 123456789,
                "amount_rub": Decimal("150.25"),
                "ledger_order_id": "casino-deposit-existing",
                "status": "credited",
            }
        )

        with patch.object(internal_casino.settings, "casino_exchanger_id", 77):
            result = await credit_deposit_with_conn(conn, self._request())

        self.assertTrue(result["idempotent"])
        self.assertEqual(result["status"], "credited")
        self.assertEqual(conn.execute.await_count, 2)
        self.assertFalse(
            any(
                "INSERT INTO user_cashback_ledger" in call.args[0]
                for call in conn.fetchrow.await_args_list
            )
        )

    async def test_fails_closed_when_casino_exchanger_is_not_configured(self):
        conn = DepositCreditConn()

        with patch.object(internal_casino.settings, "casino_exchanger_id", 0):
            with self.assertRaises(HTTPException) as raised:
                await credit_deposit_with_conn(conn, self._request())

        self.assertEqual(raised.exception.status_code, 503)
        conn.execute.assert_not_awaited()
        conn.fetchrow.assert_not_awaited()

    async def test_rejects_deal_from_another_exchanger(self):
        conn = DepositCreditConn(deal={
            "id": 321,
            "exchanger_id": 78,
            "status": "confirmed",
            "client_transaction_id": "casino-dep-123456789-secure_nonce",
            "amount_rub": Decimal("150.25"),
        })

        with patch.object(internal_casino.settings, "casino_exchanger_id", 77):
            with self.assertRaises(HTTPException) as raised:
                await credit_deposit_with_conn(conn, self._request())

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(conn.execute.await_count, 1)

    async def test_rejects_unconfirmed_or_malformed_deal_before_crediting(self):
        for deal in (
            {
                "id": 321,
                "exchanger_id": 77,
                "status": "pending",
                "client_transaction_id": "casino-dep-123456789-secure_nonce",
                "amount_rub": Decimal("150.25"),
            },
            {
                "id": 321,
                "exchanger_id": 77,
                "status": "confirmed",
                "client_transaction_id": "casino-dep-123456789",
                "amount_rub": Decimal("150.25"),
            },
        ):
            with self.subTest(deal=deal):
                conn = DepositCreditConn(deal=deal)
                with patch.object(internal_casino.settings, "casino_exchanger_id", 77):
                    with self.assertRaises(HTTPException) as raised:
                        await credit_deposit_with_conn(conn, self._request())
                self.assertEqual(raised.exception.status_code, 409)
                self.assertFalse(
                    any(
                        "INSERT INTO user_cashback_ledger" in call.args[0]
                        for call in conn.fetchrow.await_args_list
                    )
                )

    async def test_matching_legacy_credit_is_reconciled_without_second_credit(self):
        conn = DepositCreditConn(
            legacy={"user_id": 123456789, "amount_rub": Decimal("150.25")}
        )

        with patch.object(internal_casino.settings, "casino_exchanger_id", 77):
            result = await credit_deposit_with_conn(conn, self._request())

        self.assertEqual(result["status"], "legacy_reconciled")
        self.assertFalse(result["idempotent"])
        self.assertEqual(conn.execute.await_count, 3)
        self.assertIn("INSERT INTO casino_deposit_credits", conn.execute.await_args_list[-1].args[0])
        self.assertFalse(
            any(
                "INSERT INTO user_cashback_ledger" in call.args[0]
                for call in conn.fetchrow.await_args_list
            )
        )

    async def test_rejects_conflicting_existing_ledger_row(self):
        conn = DepositCreditConn(
            inserted_ledger=None,
            ledger={"user_id": 999, "amount_rub": Decimal("150.25")},
        )

        with patch.object(internal_casino.settings, "casino_exchanger_id", 77):
            with self.assertRaises(HTTPException) as raised:
                await credit_deposit_with_conn(conn, self._request())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(conn.execute.await_count, 2)


class _CancelConn:
    """Conn для эндпоинта отмены: external_deals + UPDATE в статус cancelled."""

    def __init__(self, deal):
        self._deal = dict(deal) if deal else None
        self.execute = AsyncMock(side_effect=self._execute)

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        return _Tx()

    async def fetchrow(self, query, *args):
        if "FROM external_deals" in query:
            return self._deal
        raise AssertionError(f"Unexpected fetchrow: {query}")

    async def _execute(self, query, *args):
        if "UPDATE external_deals SET status = 'cancelled'" in query and self._deal:
            self._deal["status"] = "cancelled"
        return "OK"


class _CancelPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Acq:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Acq()


class DepositCancelEndpointTests(unittest.IsolatedAsyncioTestCase):
    """POST /internal/casino/deposits/{deal_id}/cancel — только неоплаченную заявку."""

    async def _run(self, conn, *, deal_id=321, telegram_id=123456789):
        pool = _CancelPool(conn)

        async def _pool():
            return pool

        with patch.object(internal_casino, "_verify_internal_token", lambda *a, **k: None), \
                patch.object(internal_casino, "get_pool", _pool):
            return await internal_casino.cancel_deposit(
                deal_id=deal_id, telegram_id=telegram_id, x_internal_token="sek"
            )

    async def test_cancels_unpaid_casino_deposit(self):
        conn = _CancelConn(
            {
                "id": 321,
                "client_transaction_id": "casino-dep-123456789-c100000-nonce1",
                "status": "awaiting_receipt",
            }
        )
        result = await self._run(conn)
        self.assertEqual(result, {"success": True, "deal_id": 321, "status": "cancelled"})
        self.assertEqual(conn._deal["status"], "cancelled")

    async def test_paid_deposit_cannot_be_cancelled(self):
        conn = _CancelConn(
            {
                "id": 321,
                "client_transaction_id": "casino-dep-123456789-c100000-nonce1",
                "status": "confirmed",
            }
        )
        with self.assertRaises(HTTPException) as raised:
            await self._run(conn)
        self.assertEqual(raised.exception.status_code, 409)
        # UPDATE в cancelled не выполнялся — оплаченную заявку не трогаем.
        self.assertFalse(
            any(
                "UPDATE external_deals SET status = 'cancelled'" in call.args[0]
                for call in conn.execute.await_args_list
            )
        )

    async def test_rejects_deposit_of_another_player(self):
        conn = _CancelConn(
            {
                "id": 321,
                "client_transaction_id": "casino-dep-999999-c100000-nonce1",
                "status": "awaiting_receipt",
            }
        )
        with self.assertRaises(HTTPException) as raised:
            await self._run(conn)
        self.assertEqual(raised.exception.status_code, 403)

    async def test_non_casino_deal_is_not_found(self):
        conn = _CancelConn(
            {
                "id": 321,
                "client_transaction_id": "order-777-abc",
                "status": "awaiting_receipt",
            }
        )
        with self.assertRaises(HTTPException) as raised:
            await self._run(conn)
        self.assertEqual(raised.exception.status_code, 404)


class CasinoSettingsContractTests(unittest.TestCase):
    def test_internal_settings_include_minimum_creator_withdrawal(self):
        settings = canonical_casino_settings([])

        self.assertEqual(settings.min_withdrawal_rub, Decimal("100.00"))
        self.assertEqual(settings.public_dict()["min_withdrawal_rub"], 100.0)

    def test_mapping_and_json_string_preserve_explicit_disabled_raffle(self):
        for enabled_games in (
            {"pvp_dice": True, "raffle": False},
            json.dumps({"pvp_dice": True, "raffle": False}),
        ):
            settings = canonical_casino_settings([
                {"key": "enabled_games", "value": enabled_games},
            ])
            self.assertTrue(settings.enabled_games["pvp_dice"])
            self.assertFalse(settings.enabled_games["raffle"])

    def test_json_string_decodes_multiple_game_flags(self):
        settings = canonical_casino_settings([
            {"key": "enabled_games", "value": json.dumps({"raffle": False, "cub": True})},
        ])

        self.assertFalse(settings.enabled_games["raffle"])
        self.assertTrue(settings.enabled_games["cub"])
        self.assertFalse(settings.enabled_games["pvp_dice"])

    def test_mapping_and_json_string_normalize_numeric_settings_equally(self):
        mapping_rows = [
            {"key": "commission_rate", "value": {"percent": 20}},
            {"key": "min_bet_rub", "value": {"amount": 25}},
        ]
        json_rows = [
            {"key": row["key"], "value": json.dumps(row["value"])}
            for row in mapping_rows
        ]

        self.assertEqual(
            canonical_casino_settings(json_rows),
            canonical_casino_settings(mapping_rows),
        )

    def test_invalid_enabled_games_fail_closed(self):
        for value in (None, "not-json", "[]", "false", 42):
            with self.subTest(value=value):
                settings = canonical_casino_settings([
                    {"key": "enabled_games", "value": value},
                ])

                self.assertTrue(settings.enabled_games)
                self.assertTrue(all(not enabled for enabled in settings.enabled_games.values()))

    def test_missing_raffle_does_not_enable_games(self):
        settings = canonical_casino_settings([
            {"key": "enabled_games", "value": {"pvp_dice": True}},
        ])

        self.assertTrue(settings.enabled_games["pvp_dice"])
        self.assertFalse(settings.enabled_games["raffle"])


class CasinoGameResponseContractTests(unittest.TestCase):
    def test_jsonb_game_state_is_decoded_from_asyncpg_string(self):
        row = {
            "game_id": "game-1", "game_type": "pvp_dice", "creator_id": 1,
            "opponent_id": None, "game_data": "{}", "bet_rub": Decimal("10.00"),
            "creator_hold_id": "hold-1", "opponent_hold_id": None, "status": "waiting",
            "state_version": 0, "game_state": '{"phase":"waiting"}', "outcome": None,
            "created_at": None, "started_at": None, "outcome_committed_at": None, "finished_at": None,
        }

        self.assertEqual(internal_casino._game_response(row)["game_state"], {"phase": "waiting"})


def test_settlement_request_rejects_raffle_and_unknown_fields():
    with pytest.raises(ValidationError):
        valid_request(game_type="raffle")
    with pytest.raises(ValidationError):
        valid_request(caller_commission="15.00")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("game_id", ""),
        ("winner_id", 9999),
        ("opponent_id", 1001),
        ("stake_rub", "0"),
        ("stake_rub", "NaN"),
    ],
)
def test_settlement_request_rejects_invalid_identity_and_money(field, value):
    with pytest.raises(ValidationError):
        valid_request(**{field: value})


def test_durable_lifecycle_models_are_strict_and_raffle_is_fail_closed():
    with pytest.raises(ValidationError):
        CasinoGameCreateRequest.model_validate({
            "game_id": "g-1", "game_type": "raffle", "creator_id": 1, "stake_rub": "10.00",
        })
    with pytest.raises(ValidationError):
        CasinoGameStateRequest.model_validate({
            "game_id": "g-1", "expected_state_version": 0, "game_state": {}, "extra": True,
        })
    with pytest.raises(ValidationError):
        ClaimRequest(worker_id="worker", limit=101)
    with pytest.raises(ValidationError):
        OutboxFailRequest(outbox_id=1, claim_token="claim", error="   ")
    legacy = OutboxFailRequest(outbox_id=1, claim_token="claim", error="send failed")
    assert legacy.error_kind == "temporary"
    assert legacy.retry_after_seconds is None
    with pytest.raises(ValidationError):
        OutboxFailRequest(
            outbox_id=1, claim_token="claim", error="rate limit",
            error_kind="rate_limited", retry_after_seconds=0,
        )


class NotificationBackoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_result_is_a_separate_durable_outbox_event(self):
        table = {
            "id": 77,
            "table_id": "table-public",
            "game_type": "baccara",
            "creator_id": 1001,
            "stake_rub": Decimal("10.00"),
            "max_seats": 2,
            "status": "finished",
            "state_version": 9,
            "started_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "game_state": {"hands": {"1": ["A♠", "8♥"]}},
            "game_chat_id": -100123,
        }
        conn = types.SimpleNamespace(
            fetch=AsyncMock(return_value=[{
                "seat_no": 1, "participant_kind": "player", "telegram_id": 1001,
                "profile_key": None, "display_name": None,
            }]),
            execute=AsyncMock(),
        )

        await internal_casino._enqueue_v2_public_outbox(
            conn, table, event_type="public_settled", payload={"outcome_kind": "winner"},
        )

        query, event_key, table_pk, recipient_id, event_type, raw_payload = conn.execute.await_args.args
        self.assertIn("casino_v2_notification_outbox", query)
        self.assertEqual((event_key, table_pk, recipient_id, event_type), (
            "v2:table-public:public_settled", 77, 1001, "public_settled",
        ))
        payload = json.loads(raw_payload)
        self.assertEqual(payload["game_chat_id"], -100123)
        self.assertEqual(payload["table"]["roster"][0]["telegram_id"], 1001)

    async def test_rate_limit_does_not_consume_attempt_and_honours_retry_after(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)
        conn = types.SimpleNamespace(fetchrow=AsyncMock(return_value={
            "id": 7, "status": "pending", "attempts": 3, "available_at": now,
        }))
        body = OutboxFailRequest(
            outbox_id=7, claim_token="claim", error="429",
            error_kind="rate_limited", retry_after_seconds=37,
        )

        result = await internal_casino.fail_outbox_with_conn(conn, body)

        query, *args = conn.fetchrow.await_args.args
        self.assertIn("attempts - 1", query)
        self.assertIn("72 hours", query)
        self.assertEqual(args[-2:], ["rate_limited", 37])
        self.assertEqual(result["attempts"], 3)

    async def test_v2_failure_uses_same_delivery_policy(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)
        conn = types.SimpleNamespace(fetchrow=AsyncMock(return_value={
            "id": 8, "status": "pending", "attempts": 2, "available_at": now,
        }))
        body = internal_casino.V2OutboxFailRequest(
            outbox_id=8, claim_token="claim", error="network",
        )

        result = await internal_casino.fail_v2_outbox_with_conn(conn, body)

        query, *args = conn.fetchrow.await_args.args
        self.assertIn("72 hours", query)
        self.assertEqual(args[-2:], ["temporary", None])
        self.assertEqual(result["status"], "pending")

    async def test_real_start_resumes_only_a_bounded_recipient_batch(self):
        conn = types.SimpleNamespace(fetch=AsyncMock(side_effect=[
            [{"id": 31}, {"id": 30}],
            [{"id": 12}],
        ]))

        result = await internal_casino.resume_blocked_notifications_with_conn(
            conn,
            internal_casino.NotificationResumeRequest(telegram_id=555, limit=3),
        )

        self.assertEqual(result["resumed"], 3)
        self.assertEqual(result["v2_outbox_ids"], [31, 30])
        self.assertEqual(result["legacy_outbox_ids"], [12])
        first_args = conn.fetch.await_args_list[0].args
        second_args = conn.fetch.await_args_list[1].args
        first_query, first_recipient, first_limit, first_excluded = first_args
        second_query, second_recipient, second_limit = second_args
        self.assertIn("last_error_kind='dm_unavailable'", first_query)
        self.assertIn("last_error_kind='dm_unavailable'", second_query)
        self.assertIn("event_type = ANY", first_query)
        self.assertEqual(
            sorted(first_excluded),
            sorted(internal_casino.V2_NON_RESUMABLE_EVENT_TYPES),
        )
        self.assertEqual((first_recipient, first_limit), (555, 3))
        self.assertEqual((second_recipient, second_limit), (555, 1))


class ActivePvpGamesSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_only_recoverable_pvp_games_without_mutating_them(self):
        row = {
            **ACTIVE_LIFECYCLE_GAME,
            "game_data": {"counterparty_kind": "player"},
            "counterparty_kind": "player",
        }
        conn = types.SimpleNamespace(fetch=AsyncMock(return_value=[row]))

        result = await internal_casino.active_pvp_games_with_conn(conn)

        self.assertEqual(result["games"][0]["game_id"], "game-lifecycle")
        self.assertEqual(result["games"][0]["status"], "active")
        self.assertEqual(result["games"][0]["game_state"], {})
        conn.fetch.assert_awaited_once()
        self.assertIn("status IN ('waiting', 'active')", conn.fetch.await_args.args[0])
        self.assertIn("pvp_dice", conn.fetch.await_args.args[0])
        self.assertIn("baccara", conn.fetch.await_args.args[0])
        self.assertIn("blackjack", conn.fetch.await_args.args[0])


class WebDuelInvitationTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_pins_chat_and_inserts_card_invitation(self):
        binding = {
            "id": 9,
            "chat_id": -100123,
            "updated_at": datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc),
        }
        intent = {"id": 44, "status": "pending", "telegram_message_id": None}
        conn = types.SimpleNamespace(
            execute=AsyncMock(),
            fetchrow=AsyncMock(side_effect=[None, binding, {"game_id": "web-abc"}, intent]),
        )

        result = await enqueue_web_duel_invitation_with_conn(
            conn,
            game_id="web-abc",
            game_type="baccara",
            creator_id=940002,
            stake_rub=Decimal("100.00"),
        )

        self.assertEqual(result["outbox_id"], 44)
        self.assertEqual(result["status"], "pending")
        self.assertIn("741921", conn.execute.await_args.args[0])
        insert_query, event_key, game_id, chat_id, payload_json = conn.fetchrow.await_args_list[3].args
        self.assertIn("INSERT INTO casino_pvp_invitation_outbox", insert_query)
        self.assertEqual(game_id, "web-abc")
        self.assertEqual(chat_id, -100123)
        payload = json.loads(payload_json)
        self.assertEqual(payload["game_type"], "baccara")
        self.assertEqual(payload["rounds"], 0)
        self.assertEqual(payload["origin"], "web")
        self.assertEqual(payload["creator_id"], 940002)
        pin_query, *_pin_args = conn.fetchrow.await_args_list[2].args
        self.assertIn("game_chat_id", pin_query)

    async def test_enqueue_skips_without_active_binding(self):
        conn = types.SimpleNamespace(
            execute=AsyncMock(),
            fetchrow=AsyncMock(side_effect=[None, None]),
        )
        result = await enqueue_web_duel_invitation_with_conn(
            conn,
            game_id="web-abc",
            game_type="baccara",
            creator_id=940002,
            stake_rub=Decimal("100.00"),
        )
        self.assertIsNone(result)
        self.assertEqual(conn.fetchrow.await_count, 2)

    async def test_dead_web_invitation_does_not_cancel_site_game(self):
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        conn = types.SimpleNamespace(
            fetchrow=AsyncMock(return_value={
                "id": 5, "game_id": "web-abc", "status": "dead", "attempts": 10,
                "available_at": now,
                "payload": {"origin": "web", "game_type": "baccara"},
            }),
        )
        with patch.object(internal_casino, "_cancel_unpublished_pvp_invitation_game_with_conn", new=AsyncMock()) as cancel:
            result = await fail_pvp_invitation_outbox_with_conn(
                conn,
                OutboxFailRequest(outbox_id=5, claim_token="claim", error="send failed"),
            )
        self.assertEqual(result["status"], "dead")
        cancel.assert_not_awaited()


class LifecycleConn:
    def __init__(self, game):
        self.game = game
        self.execute = AsyncMock()
        self.fetch = AsyncMock()
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _fetchrow(self, query, *args):
        if "FROM casino_games WHERE game_id" in query and "FOR UPDATE" in query:
            return self.game
        if "UPDATE casino_games SET game_state" in query:
            if args[1] != self.game["state_version"]:
                return None
            updated = {**self.game, "game_state": {"roll": 6}, "state_version": self.game["state_version"] + 1}
            self.game = updated
            return updated
        if "SET winner_id" in query:
            if args[1] != self.game["state_version"]:
                return None
            updated = {
                **self.game, "winner_id": args[2], "outcome": json.loads(args[3]),
                "status": "outcome_committed", "state_version": self.game["state_version"] + 1,
                "outcome_committed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
            }

            self.game = updated
            return updated
        raise AssertionError(f"Unexpected query: {query}")


ACTIVE_LIFECYCLE_GAME = {
    "game_id": "game-lifecycle", "game_type": "pvp_dice", "creator_id": 1001,
    "opponent_id": 1002, "bet_rub": Decimal("10.00"), "winner_id": None,
    "creator_hold_id": "casino-game-lifecycle-creator", "opponent_hold_id": "casino-game-lifecycle-opponent",
    "status": "active", "state_version": 3, "game_state": {}, "outcome": None,
    "created_at": datetime(2026, 8, 22, tzinfo=timezone.utc), "started_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
    "outcome_committed_at": None, "finished_at": None,
}


class DurableLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_persist_state_uses_optimistic_version_and_no_financial_calls(self):
        conn = LifecycleConn(ACTIVE_LIFECYCLE_GAME.copy())
        body = CasinoGameStateRequest(game_id="game-lifecycle", expected_state_version=3, game_state={"roll": 6})

        result = await persist_game_state_with_conn(conn, body)

        self.assertFalse(result["idempotent"])
        self.assertEqual(result["game"]["state_version"], 4)
        self.assertEqual(result["game"]["game_state"], {"roll": 6})
        self.assertTrue(any("state_version = $2" in call.args[0] for call in conn.fetchrow.await_args_list))

    async def test_commit_outcome_only_accepts_game_player_and_persists_outcome(self):
        conn = LifecycleConn(ACTIVE_LIFECYCLE_GAME.copy())
        body = CasinoGameOutcomeRequest(
            game_id="game-lifecycle", winner_id=1001, expected_state_version=3, outcome={"kind": "winner", "roll": 6},
        )

        with patch.object(internal_casino, "commission_rate_for_player", new=AsyncMock(return_value=Decimal("0.05"))), \
                patch.object(internal_casino, "commission_profile_for_player", new=AsyncMock(return_value=("wagering_complete", Decimal("0.05")))):
            result = await commit_game_outcome_with_conn(conn, body)

        self.assertEqual(result["game"]["status"], "outcome_committed")
        self.assertEqual(result["game"]["outcome"], {"kind": "winner", "roll": 6})
        self.assertFalse(any("INSERT INTO casino_notification_outbox" in call.args[0] for call in conn.execute.await_args_list))

    async def test_commit_outcome_rejects_non_player_before_update(self):
        conn = LifecycleConn(ACTIVE_LIFECYCLE_GAME.copy())
        body = CasinoGameOutcomeRequest(
            game_id="game-lifecycle", winner_id=9999, expected_state_version=3, outcome={"kind": "winner", "roll": 6},
        )

        with self.assertRaises(HTTPException) as raised:
            await commit_game_outcome_with_conn(conn, body)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(any("SET winner_id" in call.args[0] for call in conn.fetchrow.await_args_list))

    def test_non_winner_outcome_forbids_winner_id(self):
        with self.assertRaises(ValidationError):
            CasinoGameOutcomeRequest(
                game_id="game-lifecycle", winner_id=1001, expected_state_version=3,
                outcome={"kind": "draw"},
            )

    async def test_waiting_state_snapshot_uses_the_same_cas_path(self):
        waiting_game = {**ACTIVE_LIFECYCLE_GAME, "status": "waiting", "opponent_id": None,
                        "opponent_hold_id": None, "state_version": 0}
        conn = LifecycleConn(waiting_game)

        result = await persist_game_state_with_conn(
            conn,
            CasinoGameStateRequest(game_id="game-lifecycle", expected_state_version=0, game_state={"phase": "waiting"}),
        )

        self.assertEqual(result["game"]["state_version"], 1)
        update_query = next(call.args[0] for call in conn.fetchrow.await_args_list if "UPDATE casino_games SET game_state" in call.args[0])
        self.assertIn("status IN ('waiting', 'active')", update_query)

    async def test_non_winner_outcome_commits_without_winner(self):
        conn = LifecycleConn(ACTIVE_LIFECYCLE_GAME.copy())

        with patch.object(internal_casino, "commission_rate_for_player", new=AsyncMock(return_value=Decimal("0.05"))), \
                patch.object(internal_casino, "commission_profile_for_player", new=AsyncMock(return_value=("wagering_complete", Decimal("0.05")))):
            result = await commit_game_outcome_with_conn(
                conn,
                CasinoGameOutcomeRequest(
                    game_id="game-lifecycle", winner_id=None, expected_state_version=3,
                    outcome={"kind": "draw", "proof": {"rolls": [6, 6]}},
                ),
            )

        self.assertEqual(result["game"]["status"], "outcome_committed")
        self.assertIsNone(result["game"].get("winner_id"))
    async def test_waiting_cancel_commits_without_an_opponent_or_winner(self):
        waiting_game = {**ACTIVE_LIFECYCLE_GAME, "status": "waiting", "opponent_id": None, "opponent_hold_id": None}
        conn = LifecycleConn(waiting_game)

        with patch.object(internal_casino, "load_casino_settings", new=AsyncMock(return_value=canonical_casino_settings([]))), \
                patch.object(internal_casino, "commission_rate_for_player", new=AsyncMock(return_value=Decimal("0.05"))), \
                patch.object(internal_casino, "commission_profile_for_player", new=AsyncMock(return_value=("wagering_complete", Decimal("0.05")))):
            result = await commit_game_outcome_with_conn(
                conn,
                CasinoGameOutcomeRequest(
                    game_id="game-lifecycle", winner_id=None, expected_state_version=3,
                    outcome={"kind": "cancel"},
                ),
            )

        self.assertEqual(result["game"]["status"], "outcome_committed")
        update_call = next(call for call in conn.fetchrow.await_args_list if "SET winner_id" in call.args[0])
        self.assertIn("pricing_snapshot", update_call.args[0])
        self.assertEqual(update_call.args[3], None)


class SettingsWiredIntoGameplayTests(unittest.IsolatedAsyncioTestCase):
    def _dice_settings(self, **rows):
        base = [
            {"key": "enabled_games", "value": {"pvp_dice": True}},
            {"key": "min_bet_rub", "value": {"amount": 10}},
            {"key": "max_bet_rub", "value": {"amount": 100000}},
        ]
        return canonical_casino_settings(base + [{"key": k, "value": v} for k, v in rows.items()])

    async def test_create_refuses_retired_sport_game_types(self):
        body = CasinoGameCreateRequest.model_construct(
            game_id="retired",
            game_type="pvp_darts",
            creator_id=7,
            stake_rub=Decimal("10.00"),
        )
        conn = types.SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock())
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()) as lock_game:
            with self.assertRaises(HTTPException) as raised:
                await create_or_resume_game_with_conn(conn, body)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Эта игра больше не доступна")
        lock_game.assert_not_awaited()

    def test_create_request_rejects_retired_sport_literals(self):
        for game_type in ("pvp_darts", "pvp_bowling", "pvp_football", "pvp_basketball"):
            with self.subTest(game_type=game_type):
                with self.assertRaises(ValidationError):
                    CasinoGameCreateRequest(
                        game_id="retired", game_type=game_type, creator_id=7, stake_rub="10",
                    )

    async def test_create_rejects_stake_above_per_game_max(self):
        conn = types.SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(return_value=None))
        body = CasinoGameCreateRequest(
            game_id="g-limits", game_type="pvp_dice", creator_id=7, stake_rub="100",
        )
        settings = self._dice_settings(per_game_limits={"pvp_dice": {"min": 10, "max": 50}})
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(
            internal_casino, "load_casino_settings", new=AsyncMock(return_value=settings)
        ), patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()) as reserve:
            with self.assertRaises(HTTPException) as raised:
                await create_or_resume_game_with_conn(conn, body)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertTrue(str(raised.exception.detail).startswith("Ставка вне лимита"))
        reserve.assert_not_awaited()

    async def test_join_rejects_stake_above_per_game_max(self):
        game = {
            "game_id": "g-limits", "game_type": "pvp_dice", "creator_id": 1,
            "opponent_id": None, "bet_rub": Decimal("100.00"), "status": "waiting",
            "creator_hold_id": "h1", "opponent_hold_id": None,
        }
        conn = types.SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(return_value=game))
        settings = self._dice_settings(per_game_limits={"pvp_dice": {"min": 10, "max": 50}})
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(
            internal_casino, "load_casino_settings", new=AsyncMock(return_value=settings)
        ), patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()) as reserve:
            with self.assertRaises(HTTPException) as raised:
                await join_and_hold_game_with_conn(
                    conn, CasinoGameJoinRequest(game_id="g-limits", opponent_id=2)
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertTrue(str(raised.exception.detail).startswith("Ставка вне лимита"))
        reserve.assert_not_awaited()

    async def test_join_rejects_creator(self):
        game = {
            "game_id": "g-own", "game_type": "pvp_dice", "creator_id": 10,
            "opponent_id": None, "bet_rub": Decimal("50.00"), "status": "waiting",
            "creator_hold_id": "h1", "opponent_hold_id": None,
        }
        conn = types.SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(return_value=game))
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ) as lock_users:
            with self.assertRaises(HTTPException) as raised:
                await join_and_hold_game_with_conn(
                    conn, CasinoGameJoinRequest(game_id="g-own", opponent_id=10)
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Creator cannot join own game")
        lock_users.assert_not_awaited()

    async def test_join_activates_pvp_dice_deadline_and_outbox(self):
        started = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        waiting = {
            "game_id": "g-join", "game_type": "pvp_dice", "creator_id": 10,
            "opponent_id": None, "bet_rub": Decimal("50.00"), "status": "waiting",
            "state_version": 2, "creator_hold_id": "h1", "opponent_hold_id": None,
            "counterparty_kind": "player",
            "game_state": {"chat_id": -100123, "game_type": "cub", "creator_rolls": [], "opponent_rolls": []},
            "game_data": {"pvp": {"rounds": 1}},
            "created_at": started, "started_at": None, "outcome": None,
            "outcome_committed_at": None, "finished_at": None,
            "game_chat_id": -100123, "game_chat_binding_id": 1, "game_chat_binding_revision": 1,
        }
        joined = {
            **waiting, "opponent_id": 20, "status": "active",
            "opponent_hold_id": "casino-g-join-opponent", "started_at": started,
        }

        async def fetchrow(query, *args):
            if "FROM casino_games WHERE game_id" in query:
                return waiting
            if "SET opponent_id" in query:
                return joined
            if "game_data = game_data ||" in query:
                state = json.loads(args[1])
                patch_data = json.loads(args[2])
                return {
                    **joined,
                    "game_state": state,
                    "game_data": {**joined["game_data"], **patch_data},
                    "state_version": 3,
                }
            raise AssertionError(query)

        conn = types.SimpleNamespace(execute=AsyncMock(), fetchrow=AsyncMock(side_effect=fetchrow))
        settings = self._dice_settings()
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(
            internal_casino, "load_casino_settings", new=AsyncMock(return_value=settings)
        ), patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()):
            result = await join_and_hold_game_with_conn(
                conn, CasinoGameJoinRequest(game_id="g-join", opponent_id=20)
            )
        self.assertFalse(result["idempotent"])
        self.assertTrue(result["game"]["game_state"]["roll_deadline_at"])
        activate = next(
            call for call in conn.fetchrow.await_args_list if "game_data = game_data ||" in call.args[0]
        )
        self.assertIn("roll_deadline_at", json.loads(activate.args[2]))
        self.assertIn("pvp_dice_hmac", activate.args[3])
        events = [
            call.args[2]
            for call in conn.execute.await_args_list
            if "casino_notification_outbox" in call.args[0]
        ]
        self.assertEqual(events.count("pvp_roll_prompt"), 0)
        self.assertEqual(events.count("pvp_roll_prompt_group"), 1)

    async def test_commit_outcome_snapshot_includes_commission_cap(self):
        conn = LifecycleConn(ACTIVE_LIFECYCLE_GAME.copy())
        settings = self._dice_settings(
            commission_cap_rub={"amount": 7},
            commission_min_rub={"amount": 1},
        )
        with patch.object(
            internal_casino, "load_casino_settings", new=AsyncMock(return_value=settings)
        ), patch.object(
            internal_casino, "commission_rate_for_player", new=AsyncMock(return_value=Decimal("15"))
        ), patch.object(
            internal_casino,
            "commission_profile_for_player",
            new=AsyncMock(return_value=("wagering_active", None)),
        ):
            await commit_game_outcome_with_conn(
                conn,
                CasinoGameOutcomeRequest(
                    game_id="game-lifecycle", winner_id=1001, expected_state_version=3,
                    outcome={"kind": "winner", "roll": 6},
                ),
            )
        update_call = next(
            call for call in conn.fetchrow.await_args_list if "SET winner_id" in call.args[0]
        )
        snapshot = json.loads(update_call.args[5])
        self.assertEqual(snapshot["commission_cap_rub"], "7.00")
        self.assertEqual(snapshot["commission_min_rub"], "1.00")


class ReleaseLifecycleConn:
    def __init__(self, game, holds):
        self.game = game
        self.holds = holds
        self.execute = AsyncMock()
        self.fetch = AsyncMock(return_value=holds)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _fetchrow(self, query, *args):
        if "FROM casino_games WHERE game_id" in query and "FOR UPDATE" in query:
            return self.game
        if "SET status = 'manual_review'" in query:
            self.game = {**self.game, "status": "manual_review"}
            return self.game
        if "SET status = 'cancelled'" in query:
            self.game = {**self.game, "status": "cancelled"}
            return self.game
        raise AssertionError(f"Unexpected query: {query}")


class ReleaseLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_release_requires_committed_non_winner_outcome(self):
        conn = ReleaseLifecycleConn(ACTIVE_LIFECYCLE_GAME.copy(), [])

        result = await release_game_with_conn(conn, internal_casino.CasinoGameReleaseRequest(game_id="game-lifecycle"))

        self.assertTrue(result["manual_review"])
        self.assertEqual(result["game"]["status"], "manual_review")
        conn.fetch.assert_not_awaited()

    async def test_release_marks_manual_review_when_active_holds_do_not_match_contract(self):
        committed_game = {
            **ACTIVE_LIFECYCLE_GAME,
            "status": "outcome_committed",
            "outcome": {"kind": "draw"},
            "outcome_committed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
        }
        conn = ReleaseLifecycleConn(committed_game, [{
            "hold_id": "casino-game-lifecycle-creator", "telegram_id": 1001,
            "game_id": "game-lifecycle", "amount_rub": Decimal("10.00"),
            "ledger_order_ref": "casino-hold-creator", "status": "active",
        }])

        result = await release_game_with_conn(conn, internal_casino.CasinoGameReleaseRequest(game_id="game-lifecycle"))

        self.assertTrue(result["manual_review"])
        self.assertEqual(result["game"]["status"], "manual_review")
        self.assertFalse(any("released_at" in call.args[0] for call in conn.execute.await_args_list))
    async def test_release_committed_non_winner_marks_manual_review_when_holds_are_missing(self):
        committed_game = {
            **ACTIVE_LIFECYCLE_GAME,
            "status": "outcome_committed",
            "outcome": {"kind": "cancel"},
            "outcome_committed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
        }
        conn = ReleaseLifecycleConn(committed_game, [])

        result = await release_game_with_conn(conn, internal_casino.CasinoGameReleaseRequest(game_id="game-lifecycle"))

        self.assertTrue(result["manual_review"])
        self.assertEqual(result["game"]["status"], "manual_review")
        conn.fetch.assert_awaited_once()

    async def test_settle_committed_non_winner_releases_exact_waiting_creator_hold(self):
        committed_waiting = {
            **ACTIVE_LIFECYCLE_GAME,
            "status": "outcome_committed", "opponent_id": None, "opponent_hold_id": None,
            "outcome": {"kind": "timeout"},
            "outcome_committed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
        }
        creator_hold = {
            "hold_id": "casino-game-lifecycle-creator", "telegram_id": 1001,
            "game_id": "game-lifecycle", "amount_rub": Decimal("10.00"),
            "ledger_order_ref": "casino-hold-creator", "status": "active",
        }
        conn = ReleaseLifecycleConn(committed_waiting, [creator_hold])

        with patch.object(internal_casino, "release_unified_hold", new=AsyncMock()) as release:
            result = await settle_committed_outcome_with_conn(conn, CasinoGameIdRequest(game_id="game-lifecycle"))

        self.assertTrue(result["success"])
        self.assertEqual(result["game"]["status"], "cancelled")
        self.assertEqual(result["state_version"], 3)
        release.assert_awaited_once_with(
            conn, user_id=1001, order_ref="casino-hold-creator", amount_rub=Decimal("10.00"),
            note="Casino outcome refunded: game-lifecycle",
        )

    async def test_settle_committed_non_winner_marks_manual_review_before_any_release(self):
        committed_game = {
            **ACTIVE_LIFECYCLE_GAME,
            "status": "outcome_committed", "outcome": {"kind": "draw"},
            "outcome_committed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
        }
        conn = ReleaseLifecycleConn(committed_game, [{
            "hold_id": "unexpected", "telegram_id": 1001, "game_id": "game-lifecycle",
            "amount_rub": Decimal("10.00"), "ledger_order_ref": "unexpected-ref", "status": "active",
        }])

        with patch.object(internal_casino, "release_unified_hold", new=AsyncMock()) as release:
            result = await settle_committed_outcome_with_conn(conn, CasinoGameIdRequest(game_id="game-lifecycle"))

        self.assertTrue(result["manual_review"])
        release.assert_not_awaited()
        self.assertFalse(any("released_at" in call.args[0] for call in conn.execute.await_args_list))


PVP_ROBOT_GAME = {
    "id": 91,
    "game_id": "game-robot",
    "game_type": "pvp_dice",
    "creator_id": 1001,
    "opponent_id": None,
    "bet_rub": Decimal("10.00"),
    "winner_id": None,
    "creator_hold_id": "casino-game-robot-creator",
    "opponent_hold_id": None,
    "counterparty_kind": "pvp_robot",
    "house_account_id": 8,
    "robot_profile_id": 2,
    "status": "outcome_committed",
    "state_version": 4,
    "game_state": {},
    "outcome": {"kind": "house_win"},
    "game_data": {
        "pricing_snapshot": {
            "allocation_model": "stake_percent_v2",
            "commission_profile": "wagering_active",
            "commission_rate": "15.00",
            "creator_cut_percent": "3.00",
            "referral_l1_percent": "2.00",
            "referral_l2_percent": "2.00",
            "commission_cap_rub": "1.00",
            "commission_min_rub": "0.00",
        }
    },
    "created_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
    "started_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
    "outcome_committed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
    "finished_at": None,
    "game_chat_binding_id": None,
    "game_chat_id": None,
    "game_chat_binding_revision": None,
}


class RobotSettlementConn:
    def __init__(self, game):
        self.game = game
        self.execute = AsyncMock()
        self.fetch = AsyncMock()
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _fetchrow(self, query, *args):
        if "FROM casino_games WHERE game_id" in query and "FOR UPDATE" in query:
            return self.game
        if "FROM casino_balance_holds WHERE hold_id" in query:
            return {
                "hold_id": self.game["creator_hold_id"],
                "telegram_id": self.game["creator_id"],
                "game_id": self.game["game_id"],
                "amount_rub": self.game["bet_rub"],
                "ledger_order_ref": "casino-hold-robot",
                "status": "active",
            }
        if "FROM casino_house_reservations" in query and "FOR UPDATE" in query:
            return {"id": 17, "amount_rub": Decimal("20.00"), "status": "active"}
        if "UPDATE casino_house_accounts" in query:
            return {"balance_rub": Decimal("5010.00"), "reserved_rub": Decimal("0.00")}
        if "UPDATE casino_games SET status" in query and "outcome_committed" in query:
            updated = {**self.game, "status": args[1], "finished_at": datetime(2026, 8, 22, tzinfo=timezone.utc)}
            self.game = updated
            return updated
        raise AssertionError(f"Unexpected query: {query}")


class PvpRobotSettlementTests(unittest.IsolatedAsyncioTestCase):
    def test_game_for_update_selects_numeric_pk(self):
        source = internal_casino._game_for_update.__code__.co_consts
        self.assertTrue(any(isinstance(item, str) and "SELECT id, game_id" in item for item in source))

    async def _settle(self, kind: str):
        game = {**PVP_ROBOT_GAME, "outcome": {"kind": kind}}
        if kind == "winner":
            game["winner_id"] = 1001
        conn = RobotSettlementConn(game)
        recorded = AsyncMock()
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()) as confirm, patch.object(
            internal_casino, "_credit_winner", new=AsyncMock()
        ) as credit, patch.object(
            internal_casino, "_resolve_active_creator_account", new=AsyncMock(return_value=None)
        ), patch.object(
            internal_casino, "_resolve_loser_referrals", new=AsyncMock(return_value=(None, None))
        ), patch.object(internal_casino, "_record_commissions", new=recorded), patch.object(
            internal_casino, "_enqueue_notification", new=AsyncMock()
        ):
            result = await settle_committed_outcome_with_conn(conn, CasinoGameIdRequest(game_id="game-robot"))
        return result, recorded, confirm, credit

    async def test_house_win_settles_without_500_and_records_commission(self):
        result, recorded, confirm, credit = await self._settle("house_win")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "finished")
        self.assertEqual(result["payout_rub"], "0.00")
        self.assertEqual(result["commission_rub"], "0.00")
        recorded.assert_awaited_once()
        self.assertEqual(recorded.await_args.kwargs["game_pk"], 91)
        confirm.assert_awaited_once()
        credit.assert_not_awaited()

    async def test_player_win_settles_and_credits_creator(self):
        result, recorded, confirm, credit = await self._settle("winner")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "finished")
        self.assertNotEqual(result["payout_rub"], "0.00")
        self.assertNotEqual(result["commission_rub"], "0.00")
        recorded.assert_awaited_once()
        self.assertEqual(recorded.await_args.kwargs["game_pk"], 91)
        confirm.assert_awaited_once()
        credit.assert_awaited_once()


class ProfileEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_uses_weekly_wager_for_tier_and_eligible_losses_for_cashback(self):
        from casino_tier_config import tier_config_from_settings

        class Conn:
            def __init__(self):
                self.fetchval = AsyncMock(return_value=Decimal("10.00"))
                self.fetchrow = AsyncMock(side_effect=[
                    {"first_name": "Анна", "username": "anna"},
                    {"week_start": datetime(2026, 8, 24, tzinfo=timezone.utc).date(), "wager_rub": Decimal("5000.00"), "loss_rub": Decimal("100.00")},
                    {"week_start": datetime(2026, 8, 17, tzinfo=timezone.utc).date(), "net_loss_rub": Decimal("20.00"), "cashback_rub": Decimal("1.00"), "cashback_percent": None, "status": "accrued"},
                ])

        conn = Conn()
        pool = _CancelPool(conn)

        async def _pool():
            return pool

        with patch.object(internal_casino, "_verify_internal_token", lambda *a, **k: None), \
                patch.object(internal_casino, "get_pool", _pool), \
                patch.object(internal_casino, "unified_available", new=AsyncMock(return_value=Decimal("110.00"))), \
                patch.object(internal_casino, "wagering_progress", new=AsyncMock(return_value={"remaining_rub": Decimal("2.00")})), \
                patch.object(internal_casino, "load_tier_config", new=AsyncMock(return_value=tier_config_from_settings({
                    "cashback_volume_tiers": [
                        {"min_wager_rub": 0, "percent": 2},
                        {"min_wager_rub": 5000, "percent": 7},
                    ],
                }))), \
                patch.object(internal_casino, "commission_profile_for_player", new=AsyncMock(return_value=("wagering_complete", Decimal("0.05")))), \
                patch.object(internal_casino, "clan_brief_for_user", new=AsyncMock(return_value=None)):
            result = await internal_casino.get_player_profile(telegram_id=77, x_internal_token="token")

        self.assertEqual(result["available_rub"], "100.00")
        self.assertEqual(result["identity"], {"first_name": "Анна", "username": "anna"})
        self.assertEqual(result["current_week"]["tier"], "7.00")
        self.assertEqual(result["current_week"]["estimated_cashback_rub"], "7.00")
        self.assertEqual(result["prior_cashback"]["cashback_percent"], "0.00")
        weekly_query = conn.fetchrow.await_args_list[1].args[0]
        self.assertIn("game_type = ANY($2::text[])", weekly_query)
        self.assertIn("game_type = ANY($3::text[])", weekly_query)
        self.assertIn("AT TIME ZONE 'Europe/Moscow'", weekly_query)
        self.assertIn("week_start < $2::date", conn.fetchrow.await_args_list[2].args[0])
        self.assertEqual(conn.fetchrow.await_args_list[2].args[2], internal_casino.datetime.now(internal_casino._CASINO_TIMEZONE).date() - timedelta(days=internal_casino.datetime.now(internal_casino._CASINO_TIMEZONE).weekday()))


class ProfileAvatarEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_avatar_prefers_uploaded_casino_file(self):
        custom = Path("/tmp/casino-custom.jpg")
        fetch = AsyncMock()
        cosmetics = types.SimpleNamespace(
            resolve_cosmetics_avatar_path=lambda user_id: custom if user_id == 77 else None,
        )
        avatars = types.SimpleNamespace(
            resolve_bot_user_avatar_path=lambda _user_id: Path("/tmp/tg.png"),
            fetch_and_cache_bot_user_avatar=fetch,
        )
        with patch.dict(sys.modules, {"bot_user_avatars": avatars, "casino_player_cosmetics": cosmetics}), \
                patch.object(internal_casino, "_verify_internal_token"):
            response = await internal_casino.get_player_avatar(77, x_internal_token="internal-token")
        fetch.assert_not_awaited()
        self.assertEqual(response.path, custom)
        self.assertEqual(response.media_type, "image/jpeg")

    async def test_avatar_returns_cached_image_without_telegram_fetch(self):
        path = Path("/tmp/casino-avatar.png")
        fetch = AsyncMock()
        avatars = types.SimpleNamespace(
            BOT_USER_AVATAR_DIR=Path("/tmp"),
            resolve_bot_user_avatar_path=lambda user_id: path if user_id == 77 else None,
            fetch_and_cache_bot_user_avatar=fetch,
        )
        with patch.dict(sys.modules, {"bot_user_avatars": avatars}), \
                patch.object(internal_casino, "_verify_internal_token") as verify:
            response = await internal_casino.get_player_avatar(77, x_internal_token="internal-token")

        verify.assert_called_once_with("internal-token")
        fetch.assert_not_awaited()
        self.assertEqual(response.path, path)
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.headers["cache-control"], "private, max-age=86400")

    async def test_avatar_fetches_cache_miss_and_returns_not_found(self):
        path = Path("/tmp/casino-avatar.webp")
        avatars = types.SimpleNamespace(
            BOT_USER_AVATAR_DIR=Path("/tmp"),
            resolve_bot_user_avatar_path=lambda _user_id: None,
            fetch_and_cache_bot_user_avatar=AsyncMock(side_effect=[path, None]),
        )
        with patch.dict(sys.modules, {"bot_user_avatars": avatars}), \
                patch.object(internal_casino, "_verify_internal_token"):
            response = await internal_casino.get_player_avatar(77, x_internal_token="internal-token")
            with self.assertRaises(HTTPException) as error:
                await internal_casino.get_player_avatar(78, x_internal_token="internal-token")

        self.assertEqual(response.path, path)
        self.assertEqual(response.media_type, "image/webp")
        self.assertEqual(error.exception.status_code, 404)

    async def test_avatar_checks_internal_token_before_reading_cache(self):
        avatars = types.SimpleNamespace(
            resolve_bot_user_avatar_path=lambda _user_id: self.fail("avatar cache must not be read"),
            fetch_and_cache_bot_user_avatar=AsyncMock(),
        )
        with patch.dict(sys.modules, {"bot_user_avatars": avatars}), \
                patch.object(internal_casino, "_verify_internal_token", side_effect=HTTPException(status_code=403)):
            with self.assertRaises(HTTPException) as error:
                await internal_casino.get_player_avatar(77, x_internal_token="bad-token")

        self.assertEqual(error.exception.status_code, 403)


class OutboxClaimConn:
    def __init__(self):
        self.fetch = AsyncMock(return_value=[{
            "id": 7, "event_type": "outcome_committed", "game_id": "game-lifecycle", "recipient_id": 1001,
            "payload": {"game_id": "game-lifecycle"}, "attempts": 1,
            "claimed_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
        }])


class OutboxInsertConn:
    def __init__(self):
        self.execute = AsyncMock()
        self.fetch = AsyncMock(return_value=[])


class OutboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_settlement_includes_recipient_wagering_snapshot(self):
        conn = OutboxInsertConn()
        progress = {
            1001: {
                "locked_rub": Decimal("150.25"),
                "required_rub": Decimal("31.55"),
                "done_rub": Decimal("10.00"),
                "remaining_rub": Decimal("21.55"),
            },
            1002: {
                "locked_rub": Decimal("0.00"),
                "required_rub": Decimal("0.00"),
                "done_rub": Decimal("0.00"),
                "remaining_rub": Decimal("0.00"),
            },
        }

        async def load_progress(_conn, recipient_id):
            return progress[recipient_id]

        with patch.object(internal_casino, "wagering_progress", side_effect=load_progress):
            await internal_casino._enqueue_notification(
                conn,
                game_id="game-lifecycle",
                event_type="game_settled",
                payload={"creator_id": 1001, "opponent_id": 1002, "winner_id": 1001},
            )

        self.assertEqual(conn.execute.await_count, 2)
        for call in conn.execute.await_args_list:
            recipient_id = call.args[4]
            payload = json.loads(call.args[5])
            self.assertEqual(payload["chat_id"], recipient_id)
            self.assertEqual(payload["wagering"], {key: str(value) for key, value in progress[recipient_id].items()})

    async def test_release_does_not_query_wagering(self):
        conn = OutboxInsertConn()

        with patch.object(internal_casino, "wagering_progress", new=AsyncMock()) as progress:
            await internal_casino._enqueue_notification(
                conn,
                game_id="game-lifecycle",
                event_type="game_released",
                payload={"creator_id": 1001},
            )

        progress.assert_not_awaited()

    async def test_settlement_text_is_personal_russian_not_english_stub(self):
        conn = OutboxInsertConn()

        with patch.object(internal_casino, "wagering_progress", new=AsyncMock(return_value={
            "locked_rub": Decimal("0"), "required_rub": Decimal("0"),
            "done_rub": Decimal("0"), "remaining_rub": Decimal("0"),
        })), patch.object(internal_casino, "unified_available", new=AsyncMock(return_value=50.5)):
            await internal_casino._enqueue_notification(
                conn,
                game_id="game-lifecycle",
                event_type="game_settled",
                payload={
                    "creator_id": 1001, "opponent_id": 1002, "winner_id": 1001,
                    "game_type": "pvp_dice", "payout_rub": "19.00", "stake_rub": "10.00",
                },
            )

        by_recipient = {call.args[4]: json.loads(call.args[5]) for call in conn.execute.await_args_list}
        win = by_recipient[1001]
        lose = by_recipient[1002]
        self.assertEqual(win["result"], "win")
        self.assertEqual(lose["result"], "lose")
        self.assertEqual(win["your_payout_rub"], "19.00")
        self.assertEqual(lose["your_payout_rub"], "0.00")
        self.assertEqual(win["available_rub"], "50.50")
        self.assertIn("победили", win["text"])
        self.assertIn("проиграли", lose["text"])
        self.assertIn("Баланс: 50.50 ₽", win["text"])
        self.assertNotIn("Casino game", win["text"])
        self.assertNotIn("Casino game", lose["text"])


class V2TableContractTests(unittest.TestCase):
    def test_v2_house_ledger_migration_is_additive_and_table_linked(self):
        migration = Path(__file__).parents[1] / "migrations" / "add_casino_v2_house_ledger.sql"
        sql = migration.read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS casino_v2_house_ledger", sql)
        self.assertIn("table_id BIGINT NOT NULL REFERENCES casino_v2_tables", sql)
        self.assertIn("operation_key VARCHAR(160) NOT NULL UNIQUE", sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS casino_house_ledger", sql)

    def test_models_are_strict_and_enforce_v2_bounds(self):
        request = V2TableCreateRequest.model_validate({
            "table_id": "  table-1  ", "game_type": "pvp_dice", "creator_id": 1,
            "stake_rub": "10.00", "max_seats": 2, "idempotency_key": "test-create",
        })
        self.assertEqual(request.table_id, "table-1")
        self.assertEqual(request.draw_policy, "tie_break")
        self.assertEqual(request.rounds, 1)
        for invalid in (
            {"table_id": "t", "game_type": "pvp_dice", "creator_id": 1, "stake_rub": "10", "max_seats": 1},
            {"table_id": "t", "game_type": "pvp_dice", "creator_id": 1, "stake_rub": "10", "max_seats": 7},
            {"table_id": "t", "game_type": "pvp_dice", "creator_id": 1, "stake_rub": "10", "max_seats": 2, "extra": True},
        ):
            with self.assertRaises(ValidationError):
                V2TableCreateRequest.model_validate(invalid)
        with self.assertRaises(ValidationError):
            V2TableStartRequest(bot_profile_ids=[1, 1])
        with self.assertRaises(ValidationError):
            V2TableCreateRequest.model_validate({
                "table_id": "t", "game_type": "pvp_dice", "creator_id": 1, "stake_rub": "10", "max_seats": 2,
                "bot_count": 6, "idempotency_key": "too-many-bots",
            })
        # API permits capacity up to five bots; the external UI may constrain this to three.
        self.assertEqual(V2TableCreateRequest(table_id="t-5", game_type="pvp_dice", creator_id=1, stake_rub="10", max_seats=6, bot_count=5, idempotency_key="bot-five").bot_count, 5)
        web = V2TableCreateRequest(
            table_id="web-bj", game_type="blackjack", creator_id=-7, stake_rub="100",
            max_seats=4, bot_count=0, expected_state_version=0, idempotency_key="web-create",
        )
        self.assertEqual(web.creator_id, -7)
        self.assertEqual(V2TableJoinRequest(telegram_id=-7, expected_state_version=0, idempotency_key="web-join").telegram_id, -7)
        self.assertEqual(V2TableStartRequest(creator_id=-7, expected_state_version=1, idempotency_key="web-start").creator_id, -7)
        self.assertEqual(V2TableLeaveRequest(telegram_id=-7, expected_state_version=1, idempotency_key="web-leave").telegram_id, -7)
        with self.assertRaises(ValidationError):
            V2TableCreateRequest.model_validate({
                "table_id": "t", "game_type": "blackjack", "creator_id": 0, "stake_rub": "100",
                "max_seats": 4, "idempotency_key": "zero-id",
            })
        ids_sql = (Path(__file__).parents[1] / "migrations" / "add_casino_v2_web_client_ids.sql").read_text()
        self.assertIn("CHECK (creator_id <> 0)", ids_sql)
        self.assertIn("telegram_id IS NULL OR telegram_id <> 0", ids_sql)
        outbox_sql = (Path(__file__).parents[1] / "migrations" / "add_casino_v2_outbox_web_client_ids.sql").read_text()
        self.assertIn("casino_v2_notification_outbox", outbox_sql)
        self.assertIn("recipient_id <> 0", outbox_sql)
        with self.assertRaises(ValidationError):
            V2TableSettleRequest(expected_state_version=0, outcome_kind="winner", winner_seat_nos=[1, 2])
        with self.assertRaises(ValidationError):
            V2TableSettleRequest(expected_state_version=0, outcome_kind="tie_split", winner_seat_nos=[1])
        with self.assertRaises(ValidationError):
            V2TableCreateRequest.model_validate({
                "table_id": "t", "game_type": "pvp_dice", "creator_id": 1, "stake_rub": "10", "max_seats": 2,
                "idempotency_key": "bad-draw", "draw_policy": "reroll",
            })
        chat_sql = (Path(__file__).parents[1] / "migrations" / "add_casino_v2_table_chat.sql").read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS game_chat_id", chat_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS game_chat_binding_id", chat_sql)
        deal = V2CardsDealRequest(telegram_id=1, hand_size=2, seat_no=3, shoe_side="seat3_tb1")
        self.assertEqual(deal.seat_no, 3)
        self.assertEqual(deal.shoe_side, "seat3_tb1")


class V2RosterResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_roster_exposes_only_safe_player_and_bot_fields(self):
        table = {
            "id": 10, "table_id": "safe-roster", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("10.00"), "max_seats": 4, "status": "open", "state_version": 2,
            "game_state": {"bot_count": 1},
        }
        conn = types.SimpleNamespace(fetch=AsyncMock(return_value=[
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "profile_key": None, "display_name": None,
             "hold_order_ref": "secret-player-hold"},
            {"seat_no": 2, "participant_kind": "bot", "telegram_id": None, "profile_key": "house-dice", "display_name": "Dice Bot",
             "robot_profile_id": 7, "account_id": 3},
        ]))

        result = await _v2_table_response_with_conn(conn, table)

        self.assertEqual(result["max_players"], 4)
        self.assertEqual(result["bot_count"], 1)
        self.assertEqual(result["free_seats"], [3, 4])
        self.assertEqual(result["roster"], [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100},
            {"seat_no": 2, "participant_kind": "bot", "bot": {"profile_key": "house-dice", "display_name": "Dice Bot"}},
        ])
        self.assertNotIn("hold_order_ref", str(result))
        self.assertNotIn("account_id", str(result))
        self.assertNotIn("robot_profile_id", str(result))
        self.assertIn("settled", conn.fetch.await_args.args[0])
        self.assertIn("seated", conn.fetch.await_args.args[0])

    async def test_finished_settled_seats_stay_on_roster(self):
        table = {
            "id": 11, "table_id": "finished-roster", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 3, "status": "finished", "state_version": 8,
            "game_state": {"seat_nos": [1, 2, 3]},
        }
        conn = types.SimpleNamespace(fetch=AsyncMock(return_value=[
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "profile_key": None, "display_name": None},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 200, "profile_key": None, "display_name": None},
            {"seat_no": 3, "participant_kind": "player", "telegram_id": 300, "profile_key": None, "display_name": None},
        ]))
        result = await _v2_table_response_with_conn(conn, table)
        self.assertEqual([seat["seat_no"] for seat in result["roster"]], [1, 2, 3])
        self.assertEqual(result["free_seats"], [])

    async def test_active_and_recovery_snapshots_include_roster(self):
        table = {
            "id": 10, "table_id": "snapshot-roster", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("10.00"), "max_seats": 2, "status": "running", "state_version": 1, "game_state": {},
        }
        conn = types.SimpleNamespace(fetch=AsyncMock(side_effect=[
            [table],
            [{"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "profile_key": None, "display_name": None}],
            [table],
            [{"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "profile_key": None, "display_name": None}],
        ]))

        active = await active_v2_tables_with_conn(conn)
        recovery = await recovery_snapshot_v2_with_conn(conn)

        self.assertEqual(active["tables"][0]["roster"][0]["telegram_id"], 100)
        self.assertEqual(recovery["tables"][0]["free_seats"], [2])


class V2JoinAutoStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_join_auto_starts_open_table_with_bots(self):
        table = {
            "id": 10, "table_id": "auto-start", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("10.00"), "max_seats": 3, "status": "open", "state_version": 4, "started_at": None,
            "game_state": {"bot_count": 1},
        }
        joined_table = {**table, "status": "ready", "state_version": 5, "started_at": None}
        existing_seats = [
            {"id": 1, "seat_no": 1, "participant_kind": "player", "telegram_id": 100, "status": "seated"},
            {"id": 2, "seat_no": 2, "participant_kind": "bot", "telegram_id": None, "status": "seated"},
        ]
        roster = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "profile_key": None, "display_name": None},
            {"seat_no": 2, "participant_kind": "bot", "telegram_id": None, "profile_key": "bot", "display_name": "Bot"},
            {"seat_no": 3, "participant_kind": "player", "telegram_id": 200, "profile_key": None, "display_name": None},
        ]
        conn = types.SimpleNamespace(
            execute=AsyncMock(),
            fetch=AsyncMock(side_effect=[existing_seats, roster]),
            fetchrow=AsyncMock(side_effect=[table, None, joined_table]),
        )
        body = internal_casino.V2TableJoinRequest(telegram_id=200, expected_state_version=4, idempotency_key="join-final")

        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), \
                patch.object(internal_casino, "lock_casino_users", new=AsyncMock()), \
                patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()), \
                patch.object(
                    internal_casino,
                    "load_casino_settings",
                    new=AsyncMock(
                        return_value=canonical_casino_settings(
                            [
                                {"key": "enabled_games", "value": {"pvp_dice": True}},
                                {"key": "min_bet_rub", "value": {"amount": 10}},
                                {"key": "max_bet_rub", "value": {"amount": 100000}},
                            ]
                        )
                    ),
                ), \
                patch.object(internal_casino, "_record_v2_idempotency_with_conn", new=AsyncMock(side_effect=lambda _conn, _table, _op, _body, response: response)):
            result = await join_v2_table_with_conn(conn, "auto-start", body)

        self.assertTrue(result["auto_started"])
        self.assertEqual(result["table"]["status"], "ready")
        self.assertEqual(result["table"]["state_version"], 5)
        update_query, _, version, is_full, _state = conn.fetchrow.await_args_list[2].args
        self.assertIn("CASE WHEN $3 THEN 'ready'", update_query)
        self.assertEqual((version, is_full), (4, True))


class V2CreateAutoStartTests(unittest.IsolatedAsyncioTestCase):
    def _settings(self):
        return canonical_casino_settings(
            [
                {"key": "enabled_games", "value": {"pvp_dice": True}},
                {"key": "min_bet_rub", "value": {"amount": 10}},
                {"key": "max_bet_rub", "value": {"amount": 100000}},
            ]
        )

    async def test_create_starts_when_bots_fill_remaining_seats(self):
        inserted = {
            "id": 11, "table_id": "create-full", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 2, "status": "open", "state_version": 0,
            "game_state": {"bot_count": 1},
        }
        started = {**inserted, "status": "ready", "state_version": 1, "started_at": None}
        conn = types.SimpleNamespace(
            execute=AsyncMock(),
            fetchrow=AsyncMock(side_effect=[None, inserted, started]),
        )
        body = V2TableCreateRequest(
            table_id="create-full", game_type="pvp_dice", creator_id=100, stake_rub="100",
            max_players=2, bot_count=1, expected_state_version=0, idempotency_key="create-full",
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()), patch.object(
            internal_casino, "load_casino_settings", new=AsyncMock(return_value=self._settings())
        ), patch.object(internal_casino, "_seat_v2_bots_with_conn", new=AsyncMock()), patch.object(
            internal_casino, "_v2_table_response_with_conn", new=AsyncMock(side_effect=lambda _conn, row: {"status": row["status"], "state_version": row["state_version"]})
        ), patch.object(
            internal_casino, "_record_v2_idempotency_with_conn", new=AsyncMock(side_effect=lambda _conn, _table, _op, _body, response: response)
        ):
            result = await create_v2_table_with_conn(conn, body)

        self.assertTrue(result["auto_started"])
        self.assertEqual(result["table"]["status"], "ready")
        start_query = conn.fetchrow.await_args_list[2].args[0]
        self.assertIn("status='ready'", start_query)

    async def test_create_stays_open_when_human_seats_remain(self):
        inserted = {
            "id": 12, "table_id": "create-open", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 3, "status": "open", "state_version": 0,
            "game_state": {"bot_count": 1},
        }
        conn = types.SimpleNamespace(
            execute=AsyncMock(),
            fetchrow=AsyncMock(side_effect=[None, inserted]),
        )
        body = V2TableCreateRequest(
            table_id="create-open", game_type="pvp_dice", creator_id=100, stake_rub="100",
            max_players=3, bot_count=1, expected_state_version=0, idempotency_key="create-open",
        )
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()), patch.object(
            internal_casino, "load_casino_settings", new=AsyncMock(return_value=self._settings())
        ), patch.object(internal_casino, "_seat_v2_bots_with_conn", new=AsyncMock()), patch.object(
            internal_casino, "_v2_table_response_with_conn", new=AsyncMock(return_value={"status": "open"})
        ), patch.object(
            internal_casino, "_record_v2_idempotency_with_conn", new=AsyncMock(side_effect=lambda _conn, _table, _op, _body, response: response)
        ):
            result = await create_v2_table_with_conn(conn, body)

        self.assertFalse(result["auto_started"])
        self.assertEqual(len(conn.fetchrow.await_args_list), 2)


class _V2Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _V2SettleConn:
    def __init__(self, table, seats, reservation=None):
        self.table = table
        self.seats = seats
        self.reservation = reservation
        self.execute = AsyncMock()
        self.fetch = AsyncMock(return_value=seats)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    def transaction(self):
        return _V2Savepoint()

    async def _fetchrow(self, query, *args):
        if "FROM casino_v2_tables" in query:
            return self.table
        if "FROM casino_v2_house_reservations" in query:
            return self.reservation
        if "UPDATE casino_house_accounts" in query:
            return {"id": 3, "balance_rub": Decimal("1000.00")}
        if "UPDATE casino_v2_tables SET status='settling'" in query:
            return {**self.table, "status": "settling", "state_version": self.table["state_version"] + 1}
        if "UPDATE casino_v2_tables SET status='finished'" in query:
            return {**self.table, "status": "finished", "state_version": self.table["state_version"] + 2}
        return None


class _V2EndpointTransaction:
    def __init__(self, conn):
        self.conn = conn
        self.snapshot = None

    async def __aenter__(self):
        self.snapshot = dict(self.conn.state)
        self.snapshot["game_state"] = dict(self.conn.state.get("game_state") or {})
        return self

    async def __aexit__(self, exc_type, *_args):
        if exc_type:
            self.conn.state.clear()
            self.conn.state.update(self.snapshot)
            self.conn.rollbacks += 1
        else:
            self.conn.commits += 1
        return False


class _V2EndpointSettleConn:
    def __init__(self, state, seats):
        self.state = state
        self.seats = seats
        self.rollbacks = 0
        self.commits = 0
        self.execute = AsyncMock()

    def transaction(self):
        return _V2EndpointTransaction(self)

    async def fetch(self, query, *_args):
        if "casino_v2_table_seats" in query:
            return self.seats
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        if "SET status='settling'" in query:
            self.state["status"] = "settling"
            self.state["state_version"] += 1
            return dict(self.state)
        if "SET status='manual_review'" in query:
            self.state["status"] = "manual_review"
            self.state["recovery_claim_token"] = None
            self.state["recovery_claimed_at"] = None
            self.state["recovery_completed_at"] = "now"
            self.state["game_state"] = {
                **self.state.get("game_state", {}),
                "manual_review_reason": args[1],
            }
            return {"id": self.state["id"]}
        if "FROM casino_v2_tables" in query:
            return dict(self.state)
        if "casino_v2_lifecycle_idempotency" in query:
            return None
        if "casino_v2_house_reservations" in query:
            return None
        if "UPDATE casino_house_accounts" in query:
            return {"id": 3, "balance_rub": Decimal("1000.00")}
        raise AssertionError(query)


class _V2EndpointPool:
    def __init__(self, *connections):
        self.connections = list(connections)

    def acquire(self):
        conn = self.connections.pop(0)

        class _Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_args):
                return False

        return _Acquire()


class V2SettlementTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_seating_enforces_each_profile_concurrency_limit(self):
        table = {"id": 10, "table_id": "t-bot-concurrency", "game_type": "pvp_dice", "stake_rub": Decimal("10.00")}
        profiles = [{"id": 7, "account_id": 3, "max_concurrent_games": 1, "max_exposure_rub": Decimal("0.00"),
                     "balance_rub": Decimal("100.00"), "reserved_rub": Decimal("0.00")}]
        conn = types.SimpleNamespace(
            fetch=AsyncMock(side_effect=[profiles, [{"robot_profile_id": 7, "concurrent_games": 1, "exposure_rub": Decimal("0.00")}]]),
            fetchrow=AsyncMock(), execute=AsyncMock(),
        )
        with self.assertRaisesRegex(HTTPException, "concurrency limit"):
            await _seat_v2_bots_with_conn(conn, table, 1)
        conn.fetchrow.assert_not_awaited()
        conn.execute.assert_not_awaited()

    async def test_bot_seating_enforces_each_profile_exposure_limit(self):
        table = {"id": 10, "table_id": "t-bot-limit", "game_type": "pvp_dice", "stake_rub": Decimal("10.00")}
        profiles = [{"id": 7, "account_id": 3, "max_concurrent_games": 2, "max_exposure_rub": Decimal("15.00"),
                     "balance_rub": Decimal("100.00"), "reserved_rub": Decimal("0.00")}]
        conn = types.SimpleNamespace(
            fetch=AsyncMock(side_effect=[profiles, [{"robot_profile_id": 7, "concurrent_games": 1, "exposure_rub": Decimal("10.00")}]]),
            fetchrow=AsyncMock(), execute=AsyncMock(),
        )
        with self.assertRaisesRegex(HTTPException, "exposure limit"):
            await _seat_v2_bots_with_conn(conn, table, 1)
        conn.fetchrow.assert_not_awaited()
        conn.execute.assert_not_awaited()

    async def test_one_pvp_robot_profile_can_fill_several_seats(self):
        table = {
            "id": 10, "table_id": "t-reuse", "game_type": "pvp_dice", "stake_rub": Decimal("10.00"),
            "max_seats": 4, "status": "open",
        }
        profile = {
            "id": 7, "account_id": 3, "max_concurrent_games": 4, "max_exposure_rub": Decimal("0.00"),
            "balance_rub": Decimal("1000.00"), "reserved_rub": Decimal("0.00"),
        }
        conn = types.SimpleNamespace(
            fetch=AsyncMock(side_effect=[[profile], [], [{"seat_no": 1}]]),
            fetchrow=AsyncMock(side_effect=[{"id": 3}, None]),
            execute=AsyncMock(),
        )
        await _seat_v2_bots_with_conn(conn, table, 3)
        seat_inserts = [
            call for call in conn.execute.await_args_list
            if call.args and "INSERT INTO casino_v2_table_seats" in str(call.args[0])
        ]
        self.assertEqual(len(seat_inserts), 3)
        self.assertEqual([call.args[2] for call in seat_inserts], [2, 3, 4])
        self.assertEqual({call.args[3] for call in seat_inserts}, {7})
        reserve = next(
            call for call in conn.execute.await_args_list
            if call.args and "INSERT INTO casino_v2_house_reservations" in str(call.args[0])
        )
        self.assertEqual(reserve.args[4], Decimal("30.00"))

    async def test_add_bot_updates_existing_reservation_and_auto_starts_when_full(self):
        table = {
            "id": 10, "table_id": "add-1", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("100.00"), "max_seats": 2, "status": "open", "state_version": 1,
            "game_state": {"bot_count": 0},
        }
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "status": "seated"},
        ]
        started = {**table, "status": "ready", "state_version": 2, "game_state": {"bot_count": 1}}
        conn = types.SimpleNamespace(
            fetch=AsyncMock(return_value=seats),
            fetchrow=AsyncMock(side_effect=[table, None, started]),
            execute=AsyncMock(),
        )
        body = V2TableAddBotRequest(telegram_id=100, expected_state_version=1, idempotency_key="add-full")
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "_seat_v2_bots_with_conn", new=AsyncMock()
        ) as seat, patch.object(
            internal_casino, "_v2_table_response_with_conn", new=AsyncMock(return_value={"table_id": "add-1"})
        ):
            result = await add_v2_bot_with_conn(conn, "add-1", body)
        self.assertTrue(result["auto_started"])
        seat.assert_awaited_once()
        self.assertEqual(seat.await_args.args[2], 1)
        update_sql = conn.fetchrow.await_args_list[-1].args[0]
        self.assertIn("CASE WHEN $3 THEN 'ready'", update_sql)
        self.assertTrue(conn.fetchrow.await_args_list[-1].args[3])

    async def test_add_bot_rejects_viewer_who_is_not_seated(self):
        table = {
            "id": 11, "table_id": "add-2", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("50.00"), "max_seats": 4, "status": "open", "state_version": 0,
            "game_state": {},
        }
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "status": "seated"},
        ]
        conn = types.SimpleNamespace(
            fetch=AsyncMock(return_value=seats),
            fetchrow=AsyncMock(side_effect=[table, None]),
            execute=AsyncMock(),
        )
        body = V2TableAddBotRequest(telegram_id=200, expected_state_version=0, idempotency_key="stranger")
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), self.assertRaises(HTTPException) as raised:
            await add_v2_bot_with_conn(conn, "add-2", body)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("not seated", raised.exception.detail)

    async def test_tie_split_charges_full_pot_and_assigns_residual_by_seat(self):
        table = {"id": 10, "table_id": "t-1", "game_type": "pvp_dice", "creator_id": 100,
                 "stake_rub": Decimal("10.01"), "max_seats": 3, "status": "outcome_committed", "state_version": 0, "game_state": {}, "outcome": {"kind": "tie_split", "winner_seat_nos": [1, 3]}}
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-1"},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 200, "hold_order_ref": "hold-2"},
            {"seat_no": 3, "participant_kind": "player", "telegram_id": 300, "hold_order_ref": "hold-3"},
        ]
        conn = _V2SettleConn(table, seats)
        request = V2TableSettleRequest(expected_state_version=0, outcome_kind="tie_split", winner_seat_nos=[3, 1], idempotency_key="test-tie-split")
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), \
                patch.object(internal_casino, "lock_casino_users", new=AsyncMock()), \
                patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()) as confirm, \
                patch.object(internal_casino, "_credit_winner", new=AsyncMock()) as credit:
            result = await settle_v2_table_with_conn(conn, "t-1", request)
        self.assertEqual(result["pot_rub"], "30.03")
        self.assertEqual(result["commission_rub"], "1.50")
        self.assertEqual(result["payouts"], [{"seat_no": 1, "amount_rub": "14.27"}, {"seat_no": 3, "amount_rub": "14.26"}])
        self.assertEqual(confirm.await_count, 3)
        self.assertEqual(credit.await_args_list[0].kwargs["payout_rub"], Decimal("14.27"))
        self.assertEqual(credit.await_args_list[1].kwargs["payout_rub"], Decimal("14.26"))

    async def test_v2_outbox_payload_is_personal_with_result_and_balance(self):
        table = {"id": 10, "table_id": "t-1", "game_type": "pvp_dice", "creator_id": 100,
                 "stake_rub": Decimal("10.01"), "max_seats": 3, "status": "outcome_committed", "state_version": 0, "game_state": {}, "outcome": {"kind": "tie_split", "winner_seat_nos": [1, 3]}}
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-1"},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 200, "hold_order_ref": "hold-2"},
            {"seat_no": 3, "participant_kind": "player", "telegram_id": 300, "hold_order_ref": "hold-3"},
        ]
        conn = _V2SettleConn(table, seats)
        request = V2TableSettleRequest(expected_state_version=0, outcome_kind="tie_split", winner_seat_nos=[3, 1], idempotency_key="test-personal-outbox")

        async def available(_conn, user_id):
            return {100: 10.0, 200: 20.0, 300: 30.0}[user_id]

        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), \
                patch.object(internal_casino, "lock_casino_users", new=AsyncMock()), \
                patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()), \
                patch.object(internal_casino, "_credit_winner", new=AsyncMock()), \
                patch.object(internal_casino, "unified_available", new=AsyncMock(side_effect=available)):
            await settle_v2_table_with_conn(conn, "t-1", request)

        outbox = [
            json.loads(call.args[4])
            for call in conn.execute.await_args_list
            if "casino_v2_notification_outbox" in call.args[0]
        ]
        ties = [row for row in outbox if row["result"] == "tie"]
        loses = [row for row in outbox if row["result"] == "lose"]
        self.assertEqual(len(outbox), 3)
        self.assertEqual(len(ties), 2)
        self.assertEqual(len(loses), 1)
        self.assertEqual(loses[0]["your_payout_rub"], "0.00")
        self.assertEqual(loses[0]["available_rub"], "20.00")
        self.assertIn("result", loses[0])
        self.assertIn("available_rub", ties[0])
        self.assertIn("Ничья", ties[0]["text"])
        self.assertIn("проиграли", loses[0]["text"])

    async def test_tie_break_only_changes_state_without_financial_operations(self):
        table = {"id": 10, "table_id": "t-2", "game_type": "pvp_dice", "creator_id": 100,
                 "stake_rub": Decimal("10.00"), "max_seats": 2, "status": "running", "state_version": 4, "game_state": {}}
        conn = _V2SettleConn(table, [])
        request = V2TableSettleRequest(expected_state_version=4, outcome_kind="tie_break", winner_seat_nos=[1, 2], idempotency_key="test-tie-break")
        async def tie_break_update(query, *args):
            if "FROM casino_v2_tables" in query:
                return table
            if "status='tie_break_running'" in query:
                return {**table, "status": "tie_break_running", "state_version": 5}
            return None
        conn.fetchrow = AsyncMock(side_effect=tie_break_update)
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), \
                patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()) as confirm, \
                patch.object(internal_casino, "_credit_winner", new=AsyncMock()) as credit:
            result = await settle_v2_table_with_conn(conn, "t-2", request)
        self.assertTrue(result["tie_break"])
        confirm.assert_not_awaited()
        credit.assert_not_awaited()
        # V2 responses always carry the recovery-safe roster, even for tie-break transitions.
        conn.fetch.assert_awaited_once()
        conn.execute.assert_not_awaited()

    async def test_settlement_endpoint_persists_manual_review_after_outer_rollback(self):
        state = {
            "id": 10, "table_id": "t-outer-rollback", "game_type": "pvp_dice", "creator_id": 100,
            "stake_rub": Decimal("10.00"), "max_seats": 2, "status": "outcome_committed", "state_version": 0,
            "game_state": {}, "outcome": {"kind": "winner", "winner_seat_nos": [1]},
            "recovery_claim_token": "worker:10", "recovery_claimed_at": "claimed",
            "recovery_completed_at": None,
        }
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-1"},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 200, "hold_order_ref": "hold-2"},
        ]
        settlement_conn = _V2EndpointSettleConn(state, seats)
        compensation_conn = _V2EndpointSettleConn(state, seats)
        pool = _V2EndpointPool(settlement_conn, compensation_conn)
        request = V2TableSettleRequest(
            expected_state_version=0,
            outcome_kind="winner",
            winner_seat_nos=[1],
            idempotency_key="outer-rollback",
        )
        with patch.object(internal_casino, "get_pool", new=AsyncMock(return_value=pool)), \
                patch.object(internal_casino, "_verify_internal_token"), \
                patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), \
                patch.object(internal_casino, "lock_casino_users", new=AsyncMock()), \
                patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock(side_effect=RuntimeError("ledger unavailable"))), \
                patch.object(internal_casino, "_credit_winner", new=AsyncMock()) as credit:
            with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
                await internal_casino.settle_v2_table("t-outer-rollback", request, "internal")

        self.assertEqual(settlement_conn.rollbacks, 2)
        self.assertEqual(settlement_conn.commits, 0)
        self.assertEqual(compensation_conn.commits, 1)
        self.assertEqual(state["status"], "manual_review")
        self.assertIn("settlement financial exception: RuntimeError: ledger unavailable", state["game_state"]["manual_review_reason"])
        self.assertIsNone(state["recovery_claim_token"])
        self.assertIsNone(state["recovery_claimed_at"])
        self.assertEqual(credit.await_count, 0)
        self.assertEqual(settlement_conn.execute.await_count, 0)
        self.assertEqual(compensation_conn.execute.await_count, 0)
        self.assertNotIn(state["status"], {"running", "tie_break_running", "outcome_committed", "settling"})

    async def test_settlement_financial_error_marks_manual_review_and_reraises(self):
        table = {"id": 10, "table_id": "t-financial-error", "game_type": "pvp_dice", "creator_id": 100,
                 "stake_rub": Decimal("10.00"), "max_seats": 2, "status": "outcome_committed", "state_version": 0,
                 "game_state": {}, "outcome": {"kind": "winner", "winner_seat_nos": [1]}}
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-1"},
            {"seat_no": 2, "participant_kind": "player", "telegram_id": 200, "hold_order_ref": "hold-2"},
        ]
        conn = _V2SettleConn(table, seats)

        async def fetchrow(query, *args):
            if "FROM casino_v2_tables" in query:
                return table
            if "status='settling'" in query:
                return {**table, "status": "settling", "state_version": 1}
            if "SET status='manual_review'" in query:
                return {**table, "status": "manual_review"}
            return None

        conn.fetchrow = AsyncMock(side_effect=fetchrow)
        request = V2TableSettleRequest(expected_state_version=0, outcome_kind="winner", winner_seat_nos=[1], idempotency_key="financial-error")
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), \
                patch.object(internal_casino, "lock_casino_users", new=AsyncMock()), \
                patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock(side_effect=RuntimeError("ledger unavailable"))):
            with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
                await settle_v2_table_with_conn(conn, "t-financial-error", request)
        self.assertFalse(any("SET status='manual_review'" in call.args[0] for call in conn.fetchrow.await_args_list))

    async def test_bot_table_without_house_reservation_fails_closed(self):
        table = {"id": 10, "table_id": "t-3", "game_type": "pvp_dice", "creator_id": 100,
                 "stake_rub": Decimal("10.00"), "max_seats": 2, "status": "outcome_committed", "state_version": 0, "game_state": {}, "outcome": {"kind": "winner", "winner_seat_nos": [1]}}
        seats = [
            {"seat_no": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "hold-1"},
            {"seat_no": 2, "participant_kind": "bot", "telegram_id": None, "hold_order_ref": None},
        ]
        conn = _V2SettleConn(table, seats)
        request = V2TableSettleRequest(expected_state_version=0, outcome_kind="winner", winner_seat_nos=[1], idempotency_key="test-bot-fail")
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), \
                patch.object(internal_casino, "lock_casino_users", new=AsyncMock()), \
                patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()), \
                patch.object(internal_casino, "_credit_winner", new=AsyncMock()):
            with self.assertRaises(internal_casino.V2SettlementFinancialFailure) as raised:
                await settle_v2_table_with_conn(conn, "t-3", request)
        self.assertIsInstance(raised.exception.cause, HTTPException)
        self.assertEqual(raised.exception.cause.status_code, 409)

    async def test_enqueue_deduplicates_each_terminal_event_by_recipient(self):
        conn = OutboxInsertConn()

        await internal_casino._enqueue_notification(
            conn,
            game_id="game-lifecycle",
            event_type="game_settled",
            payload={"creator_id": 1001, "opponent_id": 1002, "winner_id": 1001},
        )

        self.assertEqual(conn.execute.await_count, 2)
        for call in conn.execute.await_args_list:
            self.assertIn("ON CONFLICT (game_id, event_type, recipient_id) DO NOTHING", call.args[0])
            self.assertEqual(call.args[1], f"casino:game-lifecycle:game_settled:{call.args[4]}")

    async def test_claim_uses_skip_locked_and_returns_opaque_claim_token(self):
        conn = OutboxClaimConn()

        result = await claim_outbox_with_conn(conn, ClaimRequest(worker_id="casino-bot", limit=1, lease_seconds=60))

        self.assertEqual(result["items"][0]["outbox_id"], 7)
        self.assertEqual(result["items"][0]["recipient_id"], 1001)
        self.assertTrue(result["items"][0]["claim_token"].startswith("casino-bot:"))
        self.assertIn("FOR UPDATE SKIP LOCKED", conn.fetch.await_args.args[0])


class V2CancelledOutboxTests(unittest.IsolatedAsyncioTestCase):
    def test_cancel_html_says_stake_returned_without_payout_line(self):
        text = internal_casino.format_personal_result_html(
            result="cancel",
            game_type="baccara",
            game_id="5a2f9bb1-dead-beef",
            payout_rub=0,
            available_rub="250.00",
        )
        self.assertIn("Игра отменена, ставка возвращена", text)
        self.assertIn("Baccara", text)
        self.assertIn("стол #5A2F9BB1", text)
        self.assertNotIn("Выплата:", text)
        self.assertIn("Баланс: 250.00 ₽", text)

    async def test_enqueue_cancelled_skips_bots_and_web_ids(self):
        table = {
            "id": 10,
            "table_id": "t-cancel",
            "game_type": "baccara",
            "stake_rub": Decimal("100.00"),
        }
        seats = [
            {"participant_kind": "player", "telegram_id": 100},
            {"participant_kind": "player", "telegram_id": 100},
            {"participant_kind": "bot", "telegram_id": None},
            {"participant_kind": "player", "telegram_id": -3},
            {"participant_kind": "player", "telegram_id": 200},
        ]
        conn = types.SimpleNamespace(execute=AsyncMock())

        async def available(_conn, user_id):
            return {100: 150.0, 200: 80.0}[user_id]

        with patch.object(internal_casino, "unified_available", new=AsyncMock(side_effect=available)):
            await internal_casino._enqueue_v2_cancelled_outbox(conn, table, seats)

        inserts = [
            call for call in conn.execute.await_args_list
            if "casino_v2_notification_outbox" in call.args[0]
        ]
        self.assertEqual(len(inserts), 2)
        self.assertEqual([call.args[3] for call in inserts], [100, 200])
        self.assertIn("'cancelled'", inserts[0].args[0])
        self.assertIn("ON CONFLICT(table_id,event_type,recipient_id) DO NOTHING", inserts[0].args[0])
        self.assertEqual(inserts[0].args[1], "v2:t-cancel:cancelled:100")
        payload = json.loads(inserts[0].args[4])
        self.assertEqual(payload["result"], "cancel")
        self.assertEqual(payload["available_rub"], "150.00")
        self.assertIn("ставка возвращена", payload["text"])
        self.assertNotIn("Выплата:", payload["text"])

    async def test_expire_unstarted_enqueues_cancelled_after_refund(self):
        table = {
            "id": 10, "table_id": "t-exp", "game_type": "baccara",
            "stake_rub": Decimal("100.00"), "status": "open",
        }
        seats = [
            {"id": 1, "participant_kind": "player", "telegram_id": 100, "hold_order_ref": "h1"},
            {"id": 2, "participant_kind": "bot", "telegram_id": None, "hold_order_ref": None},
        ]
        expired = {**table, "status": "expired"}
        conn = types.SimpleNamespace(
            fetch=AsyncMock(return_value=seats),
            fetchrow=AsyncMock(side_effect=[None, expired]),
            execute=AsyncMock(),
        )
        with patch.object(internal_casino, "lock_casino_users", new=AsyncMock()), \
                patch.object(internal_casino, "release_unified_hold", new=AsyncMock()) as release, \
                patch.object(internal_casino, "_enqueue_v2_cancelled_outbox", new=AsyncMock()) as enqueue, \
                patch.object(internal_casino, "_v2_table_response_with_conn", new=AsyncMock(return_value={"ok": True})):
            await internal_casino._expire_locked_v2_unstarted(conn, table)
        release.assert_awaited_once()
        enqueue.assert_awaited_once()
        self.assertIs(enqueue.await_args.args[1], expired)
        self.assertEqual(enqueue.await_args.args[2], seats)


CUB_POLICY = {
    "id": 3,
    "payout_multiplier": Decimal("2"),
    "win_probability": Decimal("0.5"),
    "terms": {},
}
CUB_PROFILE = {
    "id": 2,
    "account_id": 8,
    "min_bet_rub": Decimal("10"),
    "max_bet_rub": Decimal("100000"),
    "max_exposure_rub": Decimal("0"),
    "account_key": "main",
    "balance_rub": Decimal("5000"),
    "reserved_rub": Decimal("0"),
    "account_active": True,
}
CUB_PRICING = {
    "allocation_model": "stake_percent_v2",
    "commission_profile": "wagering_active",
    "commission_rate": "15.00",
    "creator_cut_percent": "3.00",
    "referral_l1_percent": "2.00",
    "referral_l2_percent": "2.00",
    "commission_cap_rub": "1.00",
    "commission_min_rub": "0.00",
}
WAITING_CUB = {
    "id": 42,
    "game_id": "cub-dice-1",
    "game_type": "cub",
    "creator_id": 777,
    "bet_rub": Decimal("100.00"),
    "commission_rub": Decimal("0"),
    "payout_rub": Decimal("0"),
    "winner_id": None,
    "creator_hold_id": "casino-cub-dice-1-player",
    "status": "waiting",
    "counterparty_kind": "house_robot",
    "house_account_id": 8,
    "outcome": None,
    "game_data": {
        "phase": "waiting_player_roll",
        "source": "telegram_dice",
        "reserved_payout_rub": "199.00",
        "house_policy_snapshot": {
            "policy_id": 3,
            "payout_multiplier": "2.00",
            "win_probability": "0.5",
        },
        "pricing_snapshot": CUB_PRICING,
    },
}


def _cub_settings(**rows):
    base = [
        {"key": "enabled_games", "value": {"cub": True}},
        {"key": "min_bet_rub", "value": {"amount": 10}},
        {"key": "max_bet_rub", "value": {"amount": 100000}},
        {"key": "commission_cap_rub", "value": {"amount": 1}},
        {"key": "commission_min_rub", "value": {"amount": 0}},
        {"key": "max_profit_pct_per_round", "value": {"percent": 0}},
    ]
    return canonical_casino_settings(base + [{"key": k, "value": v} for k, v in rows.items()])


class CubOpenConn:
    def __init__(self, existing=None, reservation_ok=True):
        self.existing = existing
        self.reservation_ok = reservation_ok
        self.inserted_game_data = None
        self.execute = AsyncMock()
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _fetchrow(self, query, *args):
        if "FROM casino_games" in query and "status = 'waiting'" in query:
            return self.existing
        if "FROM casino_house_policies" in query:
            return CUB_POLICY
        if "FROM casino_robot_profiles" in query:
            return CUB_PROFILE
        if "INSERT INTO casino_games" in query:
            self.inserted_game_data = json.loads(args[-1])
            self.assert_waiting_insert(query)
            return {"id": 42}
        if "UPDATE casino_house_accounts" in query and "reserved_rub = reserved_rub + $2" in query:
            if not self.reservation_ok:
                return None
            return {"balance_rub": Decimal("5000"), "reserved_rub": Decimal("199")}
        raise AssertionError(f"Unexpected fetchrow: {query}")

    def assert_waiting_insert(self, query):
        if "'waiting'" not in query and '"waiting"' not in query:
            raise AssertionError("open cub must insert status waiting")


class CubResolveConn:
    def __init__(self, game):
        self.game = dict(game)
        self.game["game_data"] = json.loads(json.dumps(game["game_data"]))
        self.ledger_inserts = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)

    async def _execute(self, query, *args):
        if "INSERT INTO casino_house_ledger" in query:
            self.ledger_inserts.append(args)
        return "UPDATE 1"

    async def _fetchrow(self, query, *args):
        if "FROM casino_games WHERE game_id" in query:
            return self.game
        if "FROM casino_house_reservations" in query:
            return {"amount_rub": Decimal("199.00"), "account_id": 8}
        if "UPDATE casino_house_accounts" in query and "balance_rub = balance_rub + $2" in query:
            return {"balance_rub": Decimal("4901.00"), "reserved_rub": Decimal("0.00")}
        if "UPDATE casino_games" in query and "status = 'finished'" in query:
            updated = {
                **self.game,
                "status": "finished",
                "winner_id": args[1],
                "outcome": json.loads(args[2]),
                "commission_rub": args[3],
                "payout_rub": args[4],
                "game_data": json.loads(args[5]),
            }
            self.game = updated
            return updated
        raise AssertionError(f"Unexpected fetchrow: {query}")


class CubTelegramDiceTests(unittest.IsolatedAsyncioTestCase):
    def _enter_open(self, stack):
        stack.enter_context(patch.object(internal_casino, "lock_casino_users", new=AsyncMock()))
        stack.enter_context(patch.object(internal_casino, "lock_casino_game", new=AsyncMock()))
        reserve_mock = stack.enter_context(patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()))
        confirm_mock = stack.enter_context(patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()))
        stack.enter_context(
            patch.object(internal_casino, "load_casino_settings", new=AsyncMock(return_value=_cub_settings()))
        )
        stack.enter_context(
            patch.object(internal_casino, "commission_rate_for_player", new=AsyncMock(return_value=Decimal("15")))
        )
        stack.enter_context(
            patch.object(
                internal_casino,
                "commission_profile_for_player",
                new=AsyncMock(return_value=("wagering_active", None)),
            )
        )
        return reserve_mock, confirm_mock

    def _resolve_patches(self):
        return (
            patch.object(internal_casino, "lock_casino_game", new=AsyncMock()),
            patch.object(internal_casino, "lock_casino_users", new=AsyncMock()),
            patch.object(internal_casino, "confirm_unified_hold", new=AsyncMock()),
            patch.object(internal_casino, "_credit_winner", new=AsyncMock()),
            patch.object(internal_casino, "_resolve_active_creator_account", new=AsyncMock(return_value=None)),
            patch.object(internal_casino, "_resolve_loser_referrals", new=AsyncMock(return_value=(None, None))),
            patch.object(internal_casino, "_record_commissions", new=AsyncMock()),
        )

    async def test_open_holds_without_hmac_or_ledger(self):
        conn = CubOpenConn()
        body = CubOpenRequest(telegram_id=777, stake_rub="100")
        with contextlib.ExitStack() as stack:
            reserve, confirm = self._enter_open(stack)
            result = await open_cub_with_conn(conn, body)

        self.assertTrue(result["success"])
        self.assertFalse(result["already_open"])
        self.assertEqual(result["status"], "waiting_player_roll")
        self.assertEqual(result["stake_rub"], "100.00")
        self.assertNotIn("rng", result)
        reserve.assert_awaited_once()
        confirm.assert_not_awaited()
        self.assertEqual(conn.inserted_game_data["source"], "telegram_dice")
        self.assertEqual(conn.inserted_game_data["phase"], "waiting_player_roll")
        self.assertNotIn("rng_audit", conn.inserted_game_data)
        self.assertFalse(
            any("INSERT INTO casino_house_ledger" in call.args[0] for call in conn.execute.await_args_list)
        )
        hold_query = conn.execute.await_args_list[0].args[0]
        self.assertIn("casino_balance_holds", hold_query)

    async def test_open_returns_existing_waiting_round(self):
        conn = CubOpenConn(existing={"game_id": "cub-dice-1", "bet_rub": Decimal("100.00")})
        with contextlib.ExitStack() as stack:
            reserve, _confirm = self._enter_open(stack)
            result = await open_cub_with_conn(conn, CubOpenRequest(telegram_id=777, stake_rub="100"))
        self.assertTrue(result["already_open"])
        self.assertEqual(result["game_id"], "cub-dice-1")
        reserve.assert_not_awaited()

    async def test_open_rejects_second_stake_while_waiting(self):
        conn = CubOpenConn(existing={"game_id": "cub-dice-1", "bet_rub": Decimal("100.00")})
        with contextlib.ExitStack() as stack:
            self._enter_open(stack)
            with self.assertRaises(HTTPException) as raised:
                await open_cub_with_conn(conn, CubOpenRequest(telegram_id=777, stake_rub="50"))
        self.assertEqual(raised.exception.status_code, 409)

    async def test_tie_does_not_write_ledger(self):
        conn = CubResolveConn(WAITING_CUB)
        patches = self._resolve_patches()
        with patches[0], patches[1], patches[2] as confirm, patches[3] as credit, patches[4], patches[5], patches[6]:
            result = await resolve_cub_with_conn(
                conn,
                CubResolveRequest(game_id="cub-dice-1", telegram_id=777, player_value=4, house_value=4),
            )
        self.assertTrue(result["tie"])
        self.assertEqual(result["player_value"], 4)
        self.assertEqual(result["source"], "telegram_dice")
        confirm.assert_not_awaited()
        credit.assert_not_awaited()
        self.assertEqual(conn.ledger_inserts, [])
        update = conn.execute.await_args.args[0]
        self.assertIn("SET game_data", update)
        self.assertNotIn("casino_house_ledger", update)

    async def test_six_vs_five_wins_with_commission_cap(self):
        conn = CubResolveConn(WAITING_CUB)
        patches = self._resolve_patches()
        with patches[0], patches[1], patches[2] as confirm, patches[3] as credit, patches[4], patches[5], \
                patches[6] as commissions:
            result = await resolve_cub_with_conn(
                conn,
                CubResolveRequest(game_id="cub-dice-1", telegram_id=777, player_value=6, house_value=5),
            )
        self.assertFalse(result["tie"])
        self.assertEqual(result["outcome"]["kind"], "win")
        self.assertEqual(result["commission_rub"], "1.00")
        self.assertEqual(result["payout_rub"], "199.00")
        self.assertEqual(result["player_value"], 6)
        self.assertEqual(result["house_value"], 5)
        self.assertEqual(result["source"], "telegram_dice")
        self.assertNotIn("rng", result)
        confirm.assert_awaited_once()
        credit.assert_awaited_once()
        self.assertEqual(credit.await_args.kwargs["payout_rub"], Decimal("199.00"))
        self.assertEqual(len(conn.ledger_inserts), 1)
        commissions.assert_awaited_once()

    async def test_one_vs_two_pays_zero(self):
        conn = CubResolveConn(WAITING_CUB)
        patches = self._resolve_patches()
        with patches[0], patches[1], patches[2], patches[3] as credit, patches[4], patches[5], patches[6]:
            result = await resolve_cub_with_conn(
                conn,
                CubResolveRequest(game_id="cub-dice-1", telegram_id=777, player_value=1, house_value=2),
            )
        self.assertEqual(result["outcome"]["kind"], "loss")
        self.assertEqual(result["payout_rub"], "0.00")
        self.assertIsNone(result["outcome"]["winner_id"])
        credit.assert_not_awaited()
        self.assertEqual(len(conn.ledger_inserts), 1)

    async def test_resolve_finished_is_idempotent(self):
        finished = {
            **WAITING_CUB,
            "status": "finished",
            "winner_id": 777,
            "payout_rub": Decimal("199.00"),
            "commission_rub": Decimal("1.00"),
            "outcome": {"kind": "win", "winner_id": 777},
            "game_data": {**WAITING_CUB["game_data"], "player_value": 6, "house_value": 5},
        }
        conn = CubResolveConn(finished)
        patches = self._resolve_patches()
        with patches[0], patches[1], patches[2] as confirm, patches[3] as credit, patches[4], patches[5], patches[6]:
            result = await resolve_cub_with_conn(
                conn,
                CubResolveRequest(game_id="cub-dice-1", telegram_id=777, player_value=1, house_value=2),
            )
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["payout_rub"], "199.00")
        confirm.assert_not_awaited()
        credit.assert_not_awaited()
        self.assertEqual(conn.ledger_inserts, [])

    async def test_pending_returns_waiting_round(self):
        conn = types.SimpleNamespace(
            fetchrow=AsyncMock(
                return_value={"game_id": "cub-dice-1", "bet_rub": Decimal("100.00"), "status": "waiting", "game_data": {}}
            )
        )
        result = await pending_cub_with_conn(conn, 777)
        self.assertEqual(result["pending"]["game_id"], "cub-dice-1")
        self.assertEqual(result["pending"]["status"], "waiting_player_roll")

    def test_resolve_rejects_out_of_range_dice(self):
        with self.assertRaises(ValidationError):
            CubResolveRequest(game_id="cub-dice-1", telegram_id=777, player_value=0, house_value=6)
        with self.assertRaises(ValidationError):
            CubResolveRequest(game_id="cub-dice-1", telegram_id=777, player_value=6, house_value=7)


CARD_SEED = "ab" * 32
CARD_GAME_ID = "baccara-fair-1"
CARD_COMMIT = internal_casino._house_rng_commit(CARD_SEED, CARD_GAME_ID)


def _active_card_game(**overrides):
    game = {
        "game_id": CARD_GAME_ID,
        "game_type": "baccara",
        "creator_id": 11,
        "opponent_id": 22,
        "bet_rub": Decimal("30.00"),
        "winner_id": None,
        "creator_hold_id": "casino-baccara-fair-1-creator",
        "opponent_hold_id": "casino-baccara-fair-1-opponent",
        "status": "active",
        "state_version": 2,
        "game_state": {},
        "outcome": None,
        "game_data": {
            "card_rng": {
                "algorithm": "HMAC-SHA256-fisher-yates-v2",
                "commit": CARD_COMMIT,
                "pair_commit": "",
                "client_seed": "focuspay",
                "nonce": 0,
                "creator_cards": [],
                "opponent_cards": [],
            }
        },
        "created_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
        "started_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
        "outcome_committed_at": None,
        "finished_at": None,
    }
    game.update(overrides)
    return game


class CardDealConn:
    def __init__(self, game, rng=None):
        self.game = dict(game)
        self.rng = rng if rng is not None else {
            "commit_hash": CARD_COMMIT,
            "server_seed": CARD_SEED,
            "status": "pending",
            "client_seed": "focuspay",
            "nonce": 0,
        }
        self.execute = AsyncMock(side_effect=self._execute)
        self.consumed = False

    async def fetchrow(self, query, *args):
        if "FROM casino_games" in query and "FOR UPDATE" in query:
            return self.game
        if "FROM casino_house_rng_commits" in query:
            return self.rng
        raise AssertionError(query)

    async def _execute(self, query, *args):
        if "SET game_data = $2::jsonb" in query:
            self.game["game_data"] = json.loads(args[1])
            return
        if "status = 'consumed'" in query:
            self.consumed = True
            self.rng = {**self.rng, "status": "consumed"}
            return
        if "rng_seed_reveal" in query:
            self.game["rng_seed_reveal"] = args[1]
            extra = json.loads(args[2]) if len(args) > 2 else {}
            self.game["game_data"] = {**_json_object_safe(self.game.get("game_data")), **extra}
            return
        if "INSERT INTO casino_house_rng_commits" in query:
            return
        if "SET rng_commit" in query:
            self.game["rng_commit"] = args[1]
            return
        raise AssertionError(query)


def _json_object_safe(value):
    if isinstance(value, dict):
        return dict(value)
    return {}


class CardFairnessTests(unittest.IsolatedAsyncioTestCase):
    def _lock(self):
        return (
            patch.object(internal_casino, "lock_casino_game", new=AsyncMock()),
            patch.object(internal_casino, "lock_casino_users", new=AsyncMock()),
        )

    async def test_prepare_persists_commit_before_any_cards(self):
        session = {
            "telegram_id": 11,
            "server_seed": CARD_SEED,
            "commit_hash": "ff" * 32,
            "client_seed": "alice",
            "nonce": 3,
            "previous_server_seed": None,
            "previous_commit": None,
        }
        executes = []

        async def fetchrow(query, *args):
            if "FROM casino_house_rng_commits" in query:
                return None
            if "FROM casino_fairness_seeds" in query:
                return session
            raise AssertionError(query)

        async def execute(query, *args):
            executes.append((query, args))
            return "UPDATE 1"

        conn = types.SimpleNamespace(execute=AsyncMock(side_effect=execute), fetchrow=AsyncMock(side_effect=fetchrow))
        result = await prepare_cards_with_conn(
            conn,
            CardsPrepareRequest(game_id=CARD_GAME_ID, game_type="baccara", telegram_id=11),
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["game_id"], CARD_GAME_ID)
        self.assertEqual(len(result["rng_commit"]), 64)
        self.assertEqual(result["client_seed"], "alice")
        self.assertEqual(result["nonce"], 3)
        self.assertNotIn("rng_seed", result)
        self.assertNotIn("server_seed", result)
        insert = next(args for query, args in executes if "INSERT INTO casino_house_rng_commits" in query)
        self.assertIn("48 hours", next(query for query, _args in executes if "INSERT INTO casino_house_rng_commits" in query))
        self.assertEqual(insert[0], CARD_GAME_ID)
        self.assertEqual(insert[2], "baccara")
        self.assertEqual(insert[3], 11)
        self.assertEqual(insert[4], CARD_SEED)
        self.assertEqual(insert[5], 3)
        self.assertEqual(insert[6], "alice")
        self.assertEqual(insert[1], internal_casino._house_rng_commit(CARD_SEED, CARD_GAME_ID))
        self.assertTrue(any("nonce = nonce + 1" in query for query, _args in executes))

    async def test_deal_follows_hmac_shoe_and_hides_seed(self):
        from casino_cards import dealt_cards

        conn = CardDealConn(_active_card_game())
        expected = dealt_cards(CARD_SEED, CARD_GAME_ID, "creator", 2)
        with self._lock()[0]:
            first = await deal_cards_with_conn(
                conn,
                CardsDealRequest(game_id=CARD_GAME_ID, telegram_id=11, hand_size=2),
            )
            again = await deal_cards_with_conn(
                conn,
                CardsDealRequest(game_id=CARD_GAME_ID, telegram_id=11, hand_size=2),
            )
            hit = await deal_cards_with_conn(
                conn,
                CardsDealRequest(game_id=CARD_GAME_ID, telegram_id=11, hand_size=3),
            )
        self.assertEqual(first["cards"], expected)
        self.assertFalse(first["idempotent"])
        self.assertEqual(again["cards"], expected)
        self.assertTrue(again["idempotent"])
        self.assertEqual(hit["cards"], dealt_cards(CARD_SEED, CARD_GAME_ID, "creator", 3))
        self.assertEqual(hit["cards"][:2], expected)
        self.assertNotIn("rng_seed", first)
        self.assertNotIn("server_seed", first)
        self.assertEqual(first["rng_commit"], CARD_COMMIT)

    async def test_deal_rejects_a_stranger(self):
        conn = CardDealConn(_active_card_game())
        with self._lock()[0], self.assertRaises(HTTPException) as raised:
            await deal_cards_with_conn(
                conn,
                CardsDealRequest(game_id=CARD_GAME_ID, telegram_id=99, hand_size=2),
            )
        self.assertEqual(raised.exception.status_code, 409)

    async def test_reveal_waits_until_the_round_is_committed(self):
        conn = CardDealConn(_active_card_game())
        with self._lock()[0], self.assertRaises(HTTPException) as raised:
            await reveal_cards_with_conn(
                conn,
                CardsRevealRequest(game_id=CARD_GAME_ID, telegram_id=11),
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(conn.consumed)

        conn = CardDealConn(_active_card_game(status="finished"))
        with self._lock()[0]:
            revealed = await reveal_cards_with_conn(
                conn,
                CardsRevealRequest(game_id=CARD_GAME_ID, telegram_id=22),
            )
        self.assertEqual(revealed["rng_seed"], CARD_SEED)
        self.assertEqual(revealed["rng_commit"], CARD_COMMIT)
        self.assertTrue(conn.consumed)

    async def test_create_binds_the_prepare_commit_onto_the_game(self):
        inserted = []

        async def fetchrow(query, *args):
            if "SELECT * FROM casino_games" in query:
                return None
            if "INSERT INTO casino_games" in query:
                return {
                    "game_id": args[0], "game_type": args[1], "creator_id": args[2],
                    "opponent_id": None, "bet_rub": args[3], "creator_hold_id": args[4],
                    "opponent_hold_id": None, "status": "waiting", "state_version": 0,
                    "game_state": {}, "outcome": None, "created_at": None, "started_at": None,
                    "outcome_committed_at": None, "finished_at": None,
                    "game_chat_binding_id": None, "game_chat_id": None,
                    "game_chat_binding_revision": None, "game_data": {},
                }
            if "FROM casino_house_rng_commits" in query:
                return None
            if "FROM casino_fairness_seeds" in query:
                return {
                    "telegram_id": 11,
                    "server_seed": CARD_SEED,
                    "commit_hash": "ff" * 32,
                    "client_seed": "focuspay",
                    "nonce": 0,
                    "previous_server_seed": None,
                    "previous_commit": None,
                }
            raise AssertionError(query)

        async def execute(query, *args):
            inserted.append((query, args))

        conn = types.SimpleNamespace(fetchrow=AsyncMock(side_effect=fetchrow), execute=AsyncMock(side_effect=execute))
        settings = canonical_casino_settings([
            {"key": "enabled_games", "value": {"baccara": True}},
            {"key": "min_bet_rub", "value": {"amount": 10}},
            {"key": "max_bet_rub", "value": {"amount": 100000}},
        ])
        with patch.object(internal_casino, "lock_casino_game", new=AsyncMock()), patch.object(
            internal_casino, "lock_casino_users", new=AsyncMock()
        ), patch.object(
            internal_casino, "load_casino_settings", new=AsyncMock(return_value=settings)
        ), patch.object(internal_casino, "reserve_unified_funds", new=AsyncMock()):
            result = await create_or_resume_game_with_conn(
                conn,
                CasinoGameCreateRequest(
                    game_id=CARD_GAME_ID, game_type="baccara", creator_id=11, stake_rub="30",
                ),
            )
        self.assertEqual(len(result["game"]["rng_commit"]), 64)
        self.assertTrue(any("casino_house_rng_commits" in query for query, _args in inserted))
        self.assertTrue(any("SET rng_commit" in query for query, _args in inserted))


def _internal_pool(conn):
    class Transaction:
        def __init__(self):
            self.enter = AsyncMock(return_value=None)
            self.exit = AsyncMock(return_value=False)

        async def __aenter__(self):
            return await self.enter()

        async def __aexit__(self, *args):
            return await self.exit(*args)

    class Acquire:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *args):
            return False

    pool = types.SimpleNamespace(acquire=lambda: Acquire())
    conn.transaction = lambda: Transaction()

    async def get_pool():
        return pool

    return get_pool


class FixedRoomInternalContractTests(unittest.IsolatedAsyncioTestCase):
    def test_create_body_rejects_one_seat(self):
        with self.assertRaises(ValidationError):
            internal_casino.FixedRoomCreateRequest(
                telegram_id=77, stake_rub=Decimal("100"), seat_count=1
            )
        body = internal_casino.FixedRoomCreateRequest(
            telegram_id=77, stake_rub=Decimal("100.00"), seat_count=3
        )
        self.assertEqual(body.seat_count, 3)
        self.assertEqual(body.stake_rub, Decimal("100.00"))

    def test_blank_room_id_is_400(self):
        with self.assertRaises(HTTPException) as raised:
            internal_casino._strip_room_id("  ")
        self.assertEqual(raised.exception.status_code, 400)

    async def test_list_and_create_call_domain(self):
        conn = types.SimpleNamespace()
        get_pool = _internal_pool(conn)
        listed = {"rooms": [{"room_id": "fr-aabbccddeeff"}], "enabled": True}
        created = {"room_id": "fr-aabbccddeeff", "stake_rub": 100.0, "seat_count": 3}
        with patch.object(internal_casino, "_verify_internal_token"), \
                patch.object(internal_casino, "get_pool", get_pool), \
                patch("casino_fixed_rooms.ensure_closer") as ensure, \
                patch("casino_fixed_rooms.list_open", new=AsyncMock(return_value=listed)) as list_open, \
                patch("casino_fixed_rooms.create_room", new=AsyncMock(return_value=created)) as create_room:
            listed_result = await internal_casino.get_internal_fixed_rooms(
                telegram_id=77, x_internal_token="internal"
            )
            created_result = await internal_casino.post_internal_fixed_room(
                internal_casino.FixedRoomCreateRequest(
                    telegram_id=77, stake_rub=Decimal("100"), seat_count=3
                ),
                x_internal_token="internal",
            )
        list_open.assert_awaited_once()
        self.assertEqual(list_open.await_args.kwargs["viewer_id"], 77)
        create_room.assert_awaited_once()
        self.assertEqual(create_room.await_args.kwargs["user_id"], 77)
        self.assertEqual(create_room.await_args.kwargs["seat_count"], 3)
        self.assertEqual(create_room.await_args.kwargs["stake_rub"], Decimal("100"))
        self.assertTrue(listed_result["success"])
        self.assertEqual(listed_result["rooms"][0]["room_id"], "fr-aabbccddeeff")
        self.assertTrue(created_result["success"])
        self.assertEqual(created_result["room_id"], "fr-aabbccddeeff")
        self.assertGreaterEqual(ensure.call_count, 1)

    async def test_join_leave_cancel_bot_call_domain(self):
        conn = types.SimpleNamespace()
        get_pool = _internal_pool(conn)
        snap = {"room_id": "fr-aabbccddeeff", "filled": 2}
        body = internal_casino.FixedRoomActorRequest(telegram_id=88)
        with patch.object(internal_casino, "_verify_internal_token"), \
                patch.object(internal_casino, "get_pool", get_pool), \
                patch("casino_fixed_rooms.ensure_closer"), \
                patch("casino_fixed_rooms.join_room", new=AsyncMock(return_value=snap)) as join_room, \
                patch("casino_fixed_rooms.leave_room", new=AsyncMock(return_value=snap)) as leave_room, \
                patch("casino_fixed_rooms.cancel_room", new=AsyncMock(return_value=snap)) as cancel_room, \
                patch("casino_fixed_rooms.add_bot", new=AsyncMock(return_value=snap)) as add_bot:
            joined = await internal_casino.post_internal_fixed_room_join(
                "fr-aabbccddeeff", body, x_internal_token="internal"
            )
            await internal_casino.post_internal_fixed_room_leave(
                "fr-aabbccddeeff", body, x_internal_token="internal"
            )
            await internal_casino.post_internal_fixed_room_cancel(
                "fr-aabbccddeeff", body, x_internal_token="internal"
            )
            await internal_casino.post_internal_fixed_room_bot(
                "fr-aabbccddeeff", body, x_internal_token="internal"
            )
        self.assertEqual(join_room.await_args.kwargs["user_id"], 88)
        self.assertEqual(join_room.await_args.kwargs["room_id"], "fr-aabbccddeeff")
        self.assertEqual(leave_room.await_args.kwargs["room_id"], "fr-aabbccddeeff")
        self.assertEqual(cancel_room.await_args.kwargs["room_id"], "fr-aabbccddeeff")
        self.assertEqual(add_bot.await_args.kwargs["room_id"], "fr-aabbccddeeff")
        self.assertTrue(joined["success"])


class V2InternalCloserContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_table_endpoints_start_web_closer(self):
        conn = types.SimpleNamespace()
        get_pool = _internal_pool(conn)
        table = {"table_id": "t1", "status": "open"}
        with patch.object(internal_casino, "_verify_internal_token"), \
                patch.object(internal_casino, "get_pool", get_pool), \
                patch.object(internal_casino, "_ensure_v2_web_closer") as ensure, \
                patch.object(internal_casino, "create_v2_table_with_conn", new=AsyncMock(return_value={"success": True, "table": table})), \
                patch.object(internal_casino, "join_v2_table_with_conn", new=AsyncMock(return_value={"success": True, "table": table})), \
                patch.object(internal_casino, "add_v2_bot_with_conn", new=AsyncMock(return_value={"success": True, "table": table})), \
                patch.object(internal_casino, "start_v2_table_with_conn", new=AsyncMock(return_value={"success": True, "table": table})):
            await internal_casino.create_v2_table(
                V2TableCreateRequest(
                    table_id="t1",
                    game_type="baccara",
                    creator_id=77,
                    stake_rub=Decimal("50"),
                    max_players=2,
                    idempotency_key="create",
                ),
                x_internal_token="internal",
            )
            await internal_casino.join_v2_table(
                "t1",
                V2TableJoinRequest(telegram_id=88, expected_state_version=1, idempotency_key="join"),
                x_internal_token="internal",
            )
            await internal_casino.add_v2_table_bot(
                "t1",
                V2TableAddBotRequest(telegram_id=77, expected_state_version=2, idempotency_key="bot"),
                x_internal_token="internal",
            )
            await internal_casino.start_v2_table(
                "t1",
                V2TableStartRequest(creator_id=77, expected_state_version=3, idempotency_key="start"),
                x_internal_token="internal",
            )
        self.assertEqual(ensure.call_count, 4)
