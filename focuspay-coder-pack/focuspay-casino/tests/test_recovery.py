import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from recovery import (
    process_recovery_job,
    recovery_outbox_loop,
    run_outbox_pass,
    run_recovery_pass,
)


class RecoveryProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_recovery_does_not_starve_outbox(self):
        delivery = AsyncMock(side_effect=asyncio.CancelledError())
        with patch('recovery.run_recovery_pass', new=AsyncMock(side_effect=RuntimeError('bad job'))), \
             patch('recovery.run_outbox_pass', new=delivery):
            with self.assertRaises(asyncio.CancelledError):
                await recovery_outbox_loop(AsyncMock(), AsyncMock(), worker_id='worker')
        delivery.assert_awaited_once()

    async def test_committed_outcome_real_finished_response_is_settled_then_completed(self):
        client = AsyncMock()
        client.settle_committed_outcome.return_value = {"success": True, "status": "finished"}
        job = {
            "game_id": "game-1",
            "claim_token": "claim-1",
            "status": "outcome_committed",
            "outcome": {"kind": "winner"},
        }

        self.assertTrue(await process_recovery_job(client, job))

        client.settle_committed_outcome.assert_awaited_once_with(game_id="game-1")
        client.release_game.assert_not_called()
        client.complete_recovery_job.assert_awaited_once_with(game_id="game-1", claim_token="claim-1")

    async def test_committed_house_win_is_settled_then_completed(self):
        client = AsyncMock()
        client.settle_committed_outcome.return_value = {"success": True, "status": "finished"}
        job = {
            "game_id": "game-robot-1",
            "claim_token": "claim-robot",
            "status": "outcome_committed",
            "outcome": {"kind": "house_win"},
        }

        self.assertTrue(await process_recovery_job(client, job))

        client.settle_committed_outcome.assert_awaited_once_with(game_id="game-robot-1")
        client.release_game.assert_not_called()
        client.complete_recovery_job.assert_awaited_once_with(
            game_id="game-robot-1", claim_token="claim-robot"
        )

    async def test_committed_timeout_is_released_then_completed(self):
        client = AsyncMock()
        client.release_game.return_value = {"success": True, "game": {"status": "cancelled"}}
        job = {
            "game_id": "game-1",
            "claim_token": "claim-1",
            "status": "outcome_committed",
            "outcome": {"kind": "timeout"},
        }

        self.assertTrue(await process_recovery_job(client, job))

        client.release_game.assert_awaited_once_with(game_id="game-1", reason="recovery_timeout")
        client.settle_committed_outcome.assert_not_called()
        client.complete_recovery_job.assert_awaited_once_with(game_id="game-1", claim_token="claim-1")

    async def test_nonterminal_action_response_is_not_completed(self):
        client = AsyncMock()
        client.release_game.return_value = {"success": True, "game": {"status": "active"}}
        job = {
            "game_id": "game-1",
            "claim_token": "claim-1",
            "status": "outcome_committed",
            "outcome": {"kind": "timeout"},
        }

        with self.assertRaisesRegex(ValueError, "did not reach a terminal"):
            await process_recovery_job(client, job)

        client.complete_recovery_job.assert_not_called()

    async def test_unknown_nonterminal_intent_is_not_completed(self):
        client = AsyncMock()
        job = {"game_id": "game-1", "claim_token": "claim-1", "status": "funded"}

        with self.assertRaisesRegex(ValueError, "Unsupported"):
            await process_recovery_job(client, job)

        client.complete_recovery_job.assert_not_called()
        client.settle_committed_outcome.assert_not_called()
        client.release_game.assert_not_called()

    async def test_claim_response_must_be_valid_before_startup_can_continue(self):
        client = AsyncMock()
        client.claim_recovery_jobs.return_value = {"success": True, "items": "not-a-list"}

        with self.assertRaisesRegex(ValueError, "invalid items"):
            await run_recovery_pass(client, worker_id="worker")

    async def test_recovery_outbox_worker_stops_immediately_when_cancelled(self):
        client = AsyncMock()
        client.claim_recovery_jobs.return_value = {"success": True, "items": []}
        client.claim_outbox_messages.return_value = {"success": True, "items": []}
        bot = AsyncMock()

        task = asyncio.create_task(recovery_outbox_loop(bot, client, worker_id="worker"))
        await asyncio.sleep(0)
        self.assertTrue(client.claim_recovery_jobs.awaited)
        self.assertTrue(client.claim_outbox_messages.awaited)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        recovery_claims = client.claim_recovery_jobs.await_count
        outbox_claims = client.claim_outbox_messages.await_count
        await asyncio.sleep(0)
        self.assertEqual(client.claim_recovery_jobs.await_count, recovery_claims)
        self.assertEqual(client.claim_outbox_messages.await_count, outbox_claims)


class RecoveryOutboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_outbox_delivery_appends_durable_wagering_snapshot(self):
        bot = AsyncMock()
        client = AsyncMock()
        client.claim_outbox_messages.return_value = {
            "success": True,
            "items": [
                {
                    "outbox_id": 9,
                    "claim_token": "claim-9",
                    "payload": {
                        "chat_id": 10,
                        "text": "Игра рассчитана.",
                        "wagering": {"locked_rub": "150.25", "remaining_rub": "31.55"},
                    },
                }
            ],
        }

        self.assertEqual(await run_outbox_pass(bot, client, worker_id="worker"), 1)

        self.assertIn("31.55 ₽", bot.send_message.await_args.args[1])
        self.assertEqual(bot.send_message.await_args.kwargs["parse_mode"], "HTML")
        client.complete_outbox_message.assert_awaited_once()

    async def test_outbox_failure_is_recorded_without_affecting_other_notifications(self):
        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("Telegram unavailable")
        client = AsyncMock()
        client.claim_outbox_messages.return_value = {
            "success": True,
            "items": [
                {
                    "outbox_id": 9,
                    "claim_token": "claim-9",
                    "payload": {"chat_id": 10, "text": "message"},
                }
            ],
        }

        self.assertEqual(await run_outbox_pass(bot, client, worker_id="worker"), 1)

        client.fail_outbox_message.assert_awaited_once_with(
            outbox_id=9,
            claim_token="claim-9",
            error="Telegram unavailable",
            error_kind="temporary",
            retry_after_seconds=None,
        )
        client.complete_outbox_message.assert_not_called()

    async def test_outbox_rate_limit_preserves_telegram_retry_after(self):
        bot = AsyncMock()
        limited = RuntimeError("Too Many Requests")
        limited.result_json = {
            "error_code": 429,
            "parameters": {"retry_after": 29},
        }
        bot.send_message.side_effect = limited
        client = AsyncMock()
        client.claim_outbox_messages.return_value = {
            "success": True,
            "items": [{
                "outbox_id": 10,
                "claim_token": "claim-10",
                "payload": {"chat_id": 10, "text": "message"},
            }],
        }

        self.assertEqual(await run_outbox_pass(bot, client, worker_id="worker"), 1)

        client.fail_outbox_message.assert_awaited_once_with(
            outbox_id=10,
            claim_token="claim-10",
            error="Too Many Requests",
            error_kind="rate_limited",
            retry_after_seconds=29,
        )

    async def test_outbox_cancellation_is_not_recorded_as_delivery_failure(self):
        bot = AsyncMock()
        bot.send_message.side_effect = asyncio.CancelledError()
        client = AsyncMock()
        client.claim_outbox_messages.return_value = {
            "success": True,
            "items": [
                {
                    "outbox_id": 9,
                    "claim_token": "claim-9",
                    "payload": {"chat_id": 10, "text": "message"},
                }
            ],
        }

        with self.assertRaises(asyncio.CancelledError):
            await run_outbox_pass(bot, client, worker_id="worker")

        client.fail_outbox_message.assert_not_called()
        client.complete_outbox_message.assert_not_called()

    async def test_roulette_settle_drops_live_card_and_tracks_result(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from recovery import _deliver_outbox_message

        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=77))
        bot.delete_message = AsyncMock()
        with (
            patch("games.roulette_card.drop", AsyncMock()) as drop_card,
            patch("games.chat_reaper.track_sent") as track_sent,
        ):
            await _deliver_outbox_message(
                bot,
                {
                    "event_type": "roulette_table_settled",
                    "payload": {
                        "chat_id": -556,
                        "text": "🎡 <b>Рулетка</b> · выпало <b>31</b> чёрное",
                        "parse_mode": "HTML",
                    },
                },
            )
        drop_card.assert_awaited_once_with(bot, -556)
        bot.send_message.assert_awaited()
        self.assertIn("выпало", bot.send_message.await_args.args[1])
        track_sent.assert_called_once()
        self.assertEqual(track_sent.call_args.args[0], -556)
        self.assertEqual(track_sent.call_args.args[1].message_id, 77)
        self.assertEqual(track_sent.call_args.args[2], 20)

    async def test_private_roulette_result_keeps_longer_ttl(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from games.chat_reaper import TTL_ROUND
        from recovery import _deliver_outbox_message

        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=12))
        with (
            patch("games.roulette_card.drop", AsyncMock()) as drop_card,
            patch("games.chat_reaper.track_sent") as track_sent,
            patch("games.chat_reaper.track_group_result") as track_group,
        ):
            await _deliver_outbox_message(
                bot,
                {
                    "event_type": "roulette_table_settled",
                    "payload": {
                        "chat_id": 8443902979,
                        "text": "🎡 <b>Рулетка</b> · выпало <b>7</b>",
                        "parse_mode": "HTML",
                    },
                },
            )
        drop_card.assert_awaited_once()
        track_group.assert_not_called()
        track_sent.assert_called_once()
        self.assertEqual(track_sent.call_args.args[2], TTL_ROUND)


if __name__ == "__main__":
    unittest.main()
