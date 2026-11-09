"""Opt-in live Casino PvP/recovery checks against the isolated staging stack.

The module intentionally skips unless it is run inside the ``casino-e2e`` Compose
profile with explicit staging configuration.  It never calls Telegram or PayFast.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlsplit

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - local developer environments
    asyncpg = None

from tests.e2e.telegram_adapter import FIXTURE_GAME_CHAT_ID, FIXTURE_USER_IDS, SyntheticTelegramAdapter
from tests.telebot_stub import TelebotModules


PLAYER_ONE = 100000001
PLAYER_TWO = 100000002
ADMIN_USER = 100000003
STAKE = Decimal("10.00")
_PRODUCTION_LITERALS = ("focuspay.org", "153.80.249.77")


class Keyboard:
    def __init__(self) -> None:
        self.buttons: list[Button] = []

    def add(self, button: "Button") -> None:
        self.buttons.append(button)


class Button:
    def __init__(self, text: str, **kwargs: object) -> None:
        self.text = text
        self.kwargs = kwargs


class _HandlerBot(SyntheticTelegramAdapter):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.message_handlers: dict[str, object] = {}

    def register_message_handler(self, handler: object, *, commands: list[str]) -> None:
        for command in commands:
            self.message_handlers[command] = handler

    def message_handler(self, **kwargs: object):
        def decorator(handler: object) -> object:
            for command in kwargs.get("commands", []):
                self.message_handlers[command] = handler
            return handler
        return decorator

    def callback_query_handler(self, **kwargs: object):
        return lambda handler: handler


def _safe_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise unittest.SkipTest(f"staging E2E requires {name}")
    return value


def _contains_production_target(value: str) -> bool:
    normalized = value.lower()
    return any(literal in normalized for literal in _PRODUCTION_LITERALS)


def _validate_staging_runtime() -> tuple[str, str]:
    if os.environ.get("ENVIRONMENT", "").strip().lower() != "staging":
        raise unittest.SkipTest("staging E2E refuses to run outside ENVIRONMENT=staging")
    base_url = _safe_value("FOCUSPAY_API_URL")
    dsn = _safe_value("DATABASE_DSN")
    _safe_value("FOCUSPAY_INTERNAL_TOKEN")
    if _contains_production_target(base_url) or _contains_production_target(dsn):
        raise unittest.SkipTest("staging E2E rejected a production-directed endpoint")
    parsed_url = urlsplit(base_url)
    parsed_dsn = urlsplit(dsn)
    if parsed_url.scheme != "http" or parsed_url.hostname != "backend":
        raise unittest.SkipTest("staging E2E requires the internal http://backend staging API")
    if parsed_dsn.scheme not in {"postgres", "postgresql"} or parsed_dsn.hostname != "postgres":
        raise unittest.SkipTest("staging E2E requires the internal postgres staging DSN")
    if os.environ.get("STAGING_E2E", "").strip() != "1":
        raise unittest.SkipTest("set STAGING_E2E=1 to opt in to staging E2E mutations")
    if set((PLAYER_ONE, PLAYER_TWO, ADMIN_USER)) != FIXTURE_USER_IDS:
        raise RuntimeError("fixture identity constants diverged")
    return base_url, dsn


class StagingPvpRecoveryTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_url, cls.dsn = _validate_staging_runtime()
        if asyncpg is None:
            raise unittest.SkipTest("staging E2E requires asyncpg in the runner image")
        with TelebotModules("focuspay_client"):
            cls.focuspay_client_module = importlib.import_module("focuspay_client")
        cls.FocusPayClient = cls.focuspay_client_module.FocusPayClient

    async def asyncSetUp(self) -> None:
        self.db = await asyncpg.connect(self.dsn)
        self.client = self.FocusPayClient(
            base_url=self.base_url,
            internal_token=os.environ["FOCUSPAY_INTERNAL_TOKEN"],
        )
        self.game_ids: list[str] = []
        await self._assert_fixture_contract()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.db.close()

    @staticmethod
    def _new_game_id(label: str) -> str:
        return f"e2e-{label}-{uuid.uuid4().hex}"

    async def _assert_fixture_contract(self) -> None:
        settings = await self.client.get_casino_settings()
        enabled = settings.get("enabled_games")
        self.assertIsInstance(enabled, dict)
        self.assertFalse(enabled.get("raffle"))
        binding = await self.client.get_active_game_chat_binding()
        self.assertIsInstance(binding, dict)
        self.assertEqual(binding.get("chat_id"), FIXTURE_GAME_CHAT_ID)
        self.assertEqual(binding.get("telegram_url"), "https://t.me/focuspay_fixture")
        users = await self.db.fetchval(
            "SELECT COUNT(*) FROM bot_users WHERE user_id = ANY($1::bigint[])",
            list(FIXTURE_USER_IDS),
        )
        self.assertEqual(users, len(FIXTURE_USER_IDS))

    async def _game_row(self, game_id: str):
        row = await self.db.fetchrow(
            """SELECT game_id, status, creator_id, opponent_id, state_version, outcome,
                      recovery_completed_at, recovery_claim_token
                 FROM casino_games WHERE game_id = $1""",
            game_id,
        )
        self.assertIsNotNone(row)
        return {**dict(row), "outcome": json.loads(row["outcome"]) if isinstance(row["outcome"], str) else row["outcome"]}

    async def _holds(self, game_id: str):
        return await self.db.fetch(
            """SELECT telegram_id, role, status, amount_rub
                 FROM casino_balance_holds WHERE game_id = $1 ORDER BY role""",
            game_id,
        )

    async def _cashback_ledger(self, game_id: str):
        return await self.db.fetch(
            """SELECT user_id, type, amount_rub, order_id
                 FROM user_cashback_ledger
                 WHERE note LIKE '%' || $1 || '%' OR order_id LIKE '%' || $1 || '%'
                 ORDER BY id""",
            game_id,
        )

    async def _outbox(self, game_id: str):
        return await self.db.fetch(
            """SELECT id, event_type, recipient_id, status, attempts
                 FROM casino_notification_outbox WHERE game_id = $1 ORDER BY id""",
            game_id,
        )

    async def _create_active_game(self, label: str) -> tuple[str, int]:
        game_id = self._new_game_id(label)
        self.game_ids.append(game_id)
        created = await self.client.create_or_resume_game(game_id, "pvp_dice", PLAYER_ONE, STAKE)
        version = int(created["game"]["state_version"])
        self.assertEqual(version, 0)
        joined = await self.client.join_and_hold_game(game_id, PLAYER_TWO)
        self.assertEqual(joined["game"]["status"], "active")
        persisted = await self.client.persist_game_state(
            game_id,
            expected_state_version=int(joined["game"]["state_version"]),
            game_state={"game_id": game_id, "phase": "rolling", "fixture": True},
        )
        return game_id, int(persisted["game"]["state_version"])

    async def _commit(self, game_id: str, version: int, kind: str, *, winner_id: int | None = None) -> int:
        response = await self.client.commit_game_outcome(
            game_id,
            winner_id=winner_id,
            expected_state_version=version,
            outcome={"kind": kind, "reason": f"e2e_{kind}", "fixture": True},
        )
        self.assertEqual(response["game"]["status"], "outcome_committed")
        return int(response["game"]["state_version"])

    async def _credit_synthetic_deposit(self, *, amount: Decimal, label: str) -> int:
        deal_id = await self.db.fetchval(
            """
            INSERT INTO external_deals (
                exchanger_id, amount_rub, crypto, markup_pct, card_fee_pct, usdt_rate_rub,
                client_pays_rub, payfast_fee_rub, net_profit_rub, principal_usdt, reward_usdt,
                receive_fee_usd, house_profit_usd, status, client_transaction_id
            ) VALUES (
                91001, $1, 'usdt', 0, 0, 100,
                $1, 0, 0, 0, 0, 0, 0, 'confirmed', $2
            ) RETURNING id
            """,
            amount,
            f"casino-dep-{PLAYER_ONE}-{label}",
        )
        self.assertIsInstance(deal_id, int)
        credited = await self.client.credit_deposit(deal_id=deal_id)
        self.assertFalse(credited["idempotent"])
        self.assertEqual(Decimal(credited["amount_rub"]), amount)
        return deal_id

    async def _finished_winner_game(self, label: str, stake: Decimal) -> dict[str, object]:
        game_id = self._new_game_id(label)
        self.game_ids.append(game_id)
        created = await self.client.create_or_resume_game(game_id, "pvp_dice", PLAYER_ONE, stake)
        joined = await self.client.join_and_hold_game(game_id, PLAYER_TWO)
        persisted = await self.client.persist_game_state(
            game_id,
            expected_state_version=int(joined["game"]["state_version"]),
            game_state={"game_id": game_id, "phase": "rolling", "fixture": True},
        )
        committed = await self.client.commit_game_outcome(
            game_id,
            winner_id=PLAYER_ONE,
            expected_state_version=int(persisted["game"]["state_version"]),
            outcome={"kind": "winner", "reason": f"e2e_{label}", "fixture": True},
        )
        settled = await self.client.settle_committed_outcome(game_id)
        self.assertEqual(settled["status"], "finished")
        return await self.db.fetchrow(
            "SELECT game_data, commission_rub, payout_rub FROM casino_games WHERE game_id = $1",
            game_id,
        )

    async def test_deposit_wagering_counts_house_take_and_switches_pricing_after_all_locks(self) -> None:
        await self._credit_synthetic_deposit(amount=Decimal("100.00"), label="e2e-wager-a")
        await self._credit_synthetic_deposit(amount=Decimal("100.00"), label="e2e-wager-b")
        progress = await self.client.get_wagering(PLAYER_ONE)
        self.assertEqual(progress["locked_rub"], "200.00")
        self.assertEqual(progress["required_house_take_rub"], "42.00")
        self.assertEqual(progress["remaining_house_take_rub"], "42.00")
        self.assertEqual(progress["required_rub"], "280.00")
        self.assertEqual(progress["done_rub"], "0.00")
        self.assertEqual(progress["remaining_rub"], "280.00")

        first = await self._finished_winner_game("wager-first", Decimal("140.00"))
        first_pricing = json.loads(str(first["game_data"]))["pricing_snapshot"]
        self.assertEqual(first_pricing["commission_rate"], "15.00")
        progress = await self.client.get_wagering(PLAYER_ONE)
        self.assertEqual(progress["locked_rub"], "100.00")
        self.assertEqual(progress["done_rub"], "0.00")
        self.assertEqual(progress["remaining_house_take_rub"], "21.00")
        self.assertEqual(progress["remaining_rub"], "140.00")

        second = await self._finished_winner_game("wager-second", Decimal("140.00"))
        second_pricing = json.loads(str(second["game_data"]))["pricing_snapshot"]
        self.assertEqual(second_pricing["commission_rate"], "15.00")
        progress = await self.client.get_wagering(PLAYER_ONE)
        self.assertEqual(progress["locked_rub"], "0.00")
        self.assertEqual(progress["required_rub"], "0.00")
        self.assertEqual(progress["done_rub"], "0.00")
        self.assertEqual(progress["remaining_rub"], "0.00")

        game_id, version = await self._create_active_game("wager-complete")
        await self._commit(game_id, version, "winner", winner_id=PLAYER_ONE)
        pricing = (await self._game_row(game_id))["outcome"]
        snapshot = await self.db.fetchval(
            "SELECT game_data -> 'pricing_snapshot' ->> 'commission_rate' FROM casino_games WHERE game_id = $1",
            game_id,
        )
        self.assertEqual(snapshot, "5.00")
        self.assertEqual(pricing["kind"], "winner")

    async def test_active_game_chat_guard_allows_only_fixture_chat(self) -> None:
        from games.chat_guard import ActiveGameChatGuard

        guard = ActiveGameChatGuard(self.client)
        self.assertTrue(await guard.allows_chat(FIXTURE_GAME_CHAT_ID))
        self.assertTrue(await guard.allows_chat("-1001234567890"))
        self.assertFalse(await guard.allows_chat(PLAYER_ONE))
        self.assertFalse(await guard.allows_chat(-1009999999999))
        self.assertFalse(await guard.allows_chat(True))

    async def test_private_allgames_only_emits_navigation(self) -> None:
        with TelebotModules("games.pvp", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.baccara", "games.blackjack", "games.house_cub"):
            pvp = importlib.import_module("games.pvp")
        previous_types = pvp.types
        pvp.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        pvp.active_games.clear()
        pvp._game_locks.clear()
        bot = _HandlerBot()
        try:
            pvp.register_pvp_handlers(bot, self.client)
            before = await self.db.fetchval("SELECT COUNT(*) FROM casino_games WHERE game_id LIKE 'e2e-%'")
            message = SimpleNamespace(
                message_id=1,
                chat=SimpleNamespace(id=PLAYER_ONE, type="private"),
                from_user=SimpleNamespace(id=PLAYER_ONE, username="fixture_one", first_name="Fixture One"),
                text="/allgames",
            )
            await bot.message_handlers["allgames"](message)
            self.assertEqual(len(bot.calls), 1)
            call = bot.calls[0]
            self.assertEqual(call.method, "reply_to")
            self.assertIn("ожидающих игр", call.payload["text"])
            after = await self.db.fetchval("SELECT COUNT(*) FROM casino_games WHERE game_id LIKE 'e2e-%'")
            self.assertEqual(after, before)
        finally:
            pvp.types = previous_types
            pvp.active_games.clear()
            pvp._game_locks.clear()

    async def test_two_players_persist_commit_and_settle_once(self) -> None:
        game_id, version = await self._create_active_game("winner")
        before_one = Decimal(str(await self.client.get_balance(PLAYER_ONE)))
        before_two = Decimal(str(await self.client.get_balance(PLAYER_TWO)))
        holds = await self._holds(game_id)
        self.assertEqual([(row["role"], row["status"]) for row in holds], [("creator", "active"), ("opponent", "active")])
        self.assertEqual({Decimal(str(row["amount_rub"])) for row in holds}, {STAKE})
        await self._commit(game_id, version, "winner", winner_id=PLAYER_ONE)
        settled = await self.client.settle_committed_outcome(game_id)
        self.assertEqual(settled["status"], "finished")
        again = await self.client.settle_committed_outcome(game_id)
        self.assertTrue(again["idempotent"])
        row = await self._game_row(game_id)
        self.assertEqual(row["status"], "finished")
        self.assertEqual(int(row["state_version"]), version + 1)
        self.assertEqual(row["outcome"]["kind"], "winner")
        holds = await self._holds(game_id)
        self.assertEqual({row["status"] for row in holds}, {"confirmed"})
        ledger = await self._cashback_ledger(game_id)
        self.assertEqual(len([row for row in ledger if row["type"] == "spend"]), 2)
        accruals = [row for row in ledger if row["type"] == "accrual"]
        self.assertEqual(len(accruals), 1)
        self.assertEqual(int(accruals[0]["user_id"]), PLAYER_ONE)
        self.assertEqual(Decimal(str(accruals[0]["amount_rub"])), Decimal(str(settled["payout_rub"])))
        self.assertEqual(Decimal(str(await self.client.get_balance(PLAYER_ONE))), before_one + Decimal(str(settled["payout_rub"])))
        self.assertEqual(Decimal(str(await self.client.get_balance(PLAYER_TWO))), before_two)
        outbox = await self._outbox(game_id)
        settled_notes = [row for row in outbox if row["event_type"] == "game_settled"]
        self.assertEqual(len(settled_notes), 2)
        self.assertEqual({int(row["recipient_id"]) for row in settled_notes}, {PLAYER_ONE, PLAYER_TWO})

    async def test_group_command_opens_wizard_without_holding_funds(self) -> None:
        with TelebotModules("games.pvp", "games.table_wizard", "games.v2_tables", "games.v2_runtime", "games.baccara", "games.blackjack", "games.house_cub"):
            pvp = importlib.import_module("games.pvp")
        previous_types = pvp.types
        pvp.types = SimpleNamespace(InlineKeyboardMarkup=Keyboard, InlineKeyboardButton=Button)
        pvp.active_games.clear()
        pvp._game_locks.clear()
        bot = _HandlerBot()
        before = Decimal(str(await self.client.get_balance(PLAYER_ONE)))
        before_games = await self.db.fetchval("SELECT COUNT(*) FROM casino_games WHERE game_id LIKE 'e2e-%'")
        try:
            pvp.register_pvp_handlers(bot, self.client)
            message = SimpleNamespace(
                message_id=2,
                chat=SimpleNamespace(id=FIXTURE_GAME_CHAT_ID, type="supergroup"),
                from_user=SimpleNamespace(id=PLAYER_ONE, username="fixture_one", first_name="Fixture One"),
                text="/2cub 10",
            )
            await bot.message_handlers["2cub"](message)
            wizard = next(
                call for call in bot.calls
                if "На сколько игроков" in str(call.payload.get("text") or "")
            )
            self.assertIn(wizard.method, {"reply_to", "send_message"})
            after_games = await self.db.fetchval("SELECT COUNT(*) FROM casino_games WHERE game_id LIKE 'e2e-%'")
            self.assertEqual(after_games, before_games)
            self.assertFalse(pvp.active_games)
            self.assertEqual(Decimal(str(await self.client.get_balance(PLAYER_ONE))), before)
        finally:
            pvp.types = previous_types
            pvp.active_games.clear()
            pvp._game_locks.clear()

    async def test_restart_recovery_non_winner_and_manual_review_work(self) -> None:
        for kind in ("draw", "cancel", "timeout"):
            game_id, version = await self._create_active_game(f"recovery-{kind}")
            await self._commit(game_id, version, kind)
        waiting_id = self._new_game_id("waiting")
        self.game_ids.append(waiting_id)
        await self.client.create_or_resume_game(waiting_id, "pvp_dice", PLAYER_ONE, STAKE)
        active_id, _ = await self._create_active_game("active")

        snapshot_before = await self.client.get_recovery_snapshot()
        self.assertGreaterEqual(snapshot_before["pending"].get("waiting", 0), 1)
        self.assertGreaterEqual(snapshot_before["pending"].get("active", 0), 1)
        processed = await importlib.import_module("recovery").run_recovery_pass(
            self.client, worker_id=f"e2e-restart-{uuid.uuid4().hex}", limit=20, lease_seconds=60
        )
        self.assertGreaterEqual(processed, 3)
        for game_id in self.game_ids[-5:-2]:
            row = await self._game_row(game_id)
            self.assertEqual(row["status"], "cancelled")
            self.assertIsNotNone(row["recovery_completed_at"])
            self.assertEqual({hold["status"] for hold in await self._holds(game_id)}, {"released"})
        self.assertEqual((await self._game_row(waiting_id))["status"], "waiting")
        self.assertEqual((await self._game_row(active_id))["status"], "active")

    async def test_recovery_lease_and_outbox_retry_do_not_duplicate_settlement(self) -> None:
        game_id, version = await self._create_active_game("lease")
        await self._commit(game_id, version, "winner", winner_id=PLAYER_ONE)
        recovery = importlib.import_module("recovery")
        worker_id = f"e2e-lease-{uuid.uuid4().hex}"
        processed = 0
        for _ in range(6):
            processed += await recovery.run_recovery_pass(self.client, worker_id=worker_id, limit=1, lease_seconds=60)
            if (await self._game_row(game_id))["status"] == "finished":
                break
        self.assertGreaterEqual(processed, 1)
        self.assertEqual((await self._game_row(game_id))["status"], "finished")
        ledger_before = await self._cashback_ledger(game_id)
        processed_again = await recovery.run_recovery_pass(self.client, worker_id=worker_id, limit=1, lease_seconds=60)
        self.assertIn(processed_again, {0, 1})
        self.assertEqual(await self._cashback_ledger(game_id), ledger_before)
        outbox_before = await self._outbox(game_id)
        failing_bot = _HandlerBot(fail_next_send=True)
        delivered = await recovery.run_outbox_pass(failing_bot, self.client, worker_id=worker_id, limit=2, lease_seconds=60)
        self.assertEqual(delivered, 2)
        self.assertEqual(await self._cashback_ledger(game_id), ledger_before)
        self.assertEqual(len(await self._outbox(game_id)), len(outbox_before))
        self.assertIn("pending", {row["status"] for row in await self._outbox(game_id)})
        retry_bot = _HandlerBot()
        for _ in range(3):
            await recovery.run_outbox_pass(
                retry_bot,
                self.client,
                worker_id=f"{worker_id}-retry-{uuid.uuid4().hex}",
                limit=20,
                lease_seconds=60,
            )
            if {row["status"] for row in await self._outbox(game_id)} == {"completed"}:
                break
        self.assertEqual(await self._cashback_ledger(game_id), ledger_before)
        self.assertEqual(len(await self._outbox(game_id)), len(outbox_before))
        self.assertEqual({row["status"] for row in await self._outbox(game_id)}, {"completed"})


if __name__ == "__main__":
    unittest.main()
