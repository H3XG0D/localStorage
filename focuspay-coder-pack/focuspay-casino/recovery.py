"""Backend-driven casino recovery and notification outbox processing."""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any, Mapping

from wagering import wagering_hint
from telegram_reliability import classify_telegram_delivery_error

logger = logging.getLogger(__name__)

RECOVERY_BATCH_SIZE = 50
RECOVERY_LEASE_SECONDS = 60
RECOVERY_POLL_SECONDS = 15
_ROUND_RESULT_EVENTS = frozenset({
    "roulette_table_settled",
    "jackpot_settled",
    "jackpot_refunded",
})
# The lifecycle API uses `finished` for a settled outcome and wraps a release
# result as `{ "game": {"status": "cancelled"} }`. No other state is safe
# to acknowledge as recovered.
_TERMINAL_STATUSES = frozenset({"finished", "cancelled"})


def default_worker_id() -> str:
    """Return a process-specific worker identity for backend recovery leases."""
    return f"casino-bot-{socket.gethostname()}-{os.getpid()}"


def _require_claim_items(response: Mapping[str, Any], *, kind: str) -> list[Mapping[str, Any]]:
    if response.get("success") is not True:
        raise ValueError(f"{kind} claim was not successful")
    items = response.get("items")
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        raise ValueError(f"{kind} claim response has invalid items")
    return items


def _game_status(job: Mapping[str, Any]) -> str:
    status = job.get("status", job.get("game_status"))
    if not isinstance(status, str) or not status:
        raise ValueError("Recovery job is missing game status")
    return status


def _claim_identity(job: Mapping[str, Any]) -> tuple[str, str]:
    game_id = job.get("game_id")
    claim_token = job.get("claim_token")
    if not isinstance(game_id, (str, int)) or not str(game_id):
        raise ValueError("Recovery job is missing game_id")
    if not isinstance(claim_token, str) or not claim_token:
        raise ValueError("Recovery job is missing claim_token")
    return str(game_id), claim_token


def _is_terminal(response: Mapping[str, Any]) -> bool:
    """Accept only the lifecycle API's terminal game responses.

    Settlement returns a flat response with ``status: finished``. Releasing a
    game returns a lifecycle envelope whose ``game.status`` is ``cancelled``.
    ``financial_state`` is intentionally inspected only when supplied as a
    string by a compatible lifecycle response; it cannot make an arbitrary
    non-terminal game response terminal.
    """
    game = response.get("game")
    snapshot = game if isinstance(game, Mapping) else response
    status = snapshot.get("status")
    if isinstance(status, str) and status in _TERMINAL_STATUSES:
        return True

    financial_state = snapshot.get("financial_state")
    return isinstance(financial_state, str) and financial_state in _TERMINAL_STATUSES


async def process_recovery_job(client: Any, job: Mapping[str, Any]) -> bool:
    """Execute exactly one persisted backend intent and acknowledge terminal work."""
    game_id, claim_token = _claim_identity(job)
    status = _game_status(job)

    if status == "outcome_committed":
        outcome = job.get("outcome")
        if not isinstance(outcome, Mapping):
            raise ValueError("Committed recovery job is missing immutable outcome")
        kind = outcome.get("kind")
        if kind in {"winner", "house_win"}:
            terminal = await client.settle_committed_outcome(game_id=game_id)
        elif kind in {"draw", "cancel", "timeout"}:
            terminal = await client.release_game(game_id=game_id, reason=f"recovery_{kind}")
        else:
            raise ValueError(f"Unsupported committed outcome kind: {kind}")
    elif status in {"waiting", "active"} and job.get("outcome") is None:
        # Legacy/pre-outcome work cannot safely move money. Preserve it for
        # manual review rather than inventing a cancellation outcome after a crash.
        raise ValueError("Recovery job has no immutable outcome")
    elif _is_terminal(job):
        terminal = job
    else:
        # The backend chose this job; an unknown non-terminal state must not be
        # guessed by the bot. Leaving the lease uncompleted schedules a retry.
        raise ValueError(f"Unsupported non-terminal recovery status: {status}")

    if not isinstance(terminal, Mapping) or not _is_terminal(terminal):
        raise ValueError(f"Recovery action for {game_id} did not reach a terminal backend state")

    await client.complete_recovery_job(game_id=game_id, claim_token=claim_token)
    return True


async def run_recovery_pass(
    client: Any,
    *,
    worker_id: str,
    limit: int = RECOVERY_BATCH_SIZE,
    lease_seconds: int = RECOVERY_LEASE_SECONDS,
) -> int:
    """Claim and process one bounded recovery batch; errors intentionally escape."""
    response = await client.claim_recovery_jobs(
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
    )
    if not isinstance(response, Mapping):
        raise ValueError("Recovery claim response must be an object")

    processed = 0
    for job in _require_claim_items(response, kind="Recovery"):
        await process_recovery_job(client, job)
        processed += 1
    return processed


async def _deliver_outbox_message(bot: Any, message: Mapping[str, Any]) -> None:
    """Deliver a persisted Telegram message without influencing financial state."""
    payload = message.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("Outbox message payload must be an object")
    chat_id = payload.get("chat_id")
    text = payload.get("text")
    if not isinstance(chat_id, (str, int)) or not isinstance(text, str):
        raise ValueError("Outbox message payload requires chat_id and text")
    wagering = payload.get("wagering")
    if isinstance(wagering, Mapping):
        text += wagering_hint(wagering, currency_symbol="₽")

    kwargs = {
        key: payload[key]
        for key in ("disable_web_page_preview", "reply_markup")
        if key in payload
    }
    if "<" in text and ">" in text:
        kwargs["parse_mode"] = "HTML"
    elif "parse_mode" in payload:
        kwargs["parse_mode"] = payload["parse_mode"]
    event_type = str(message.get("event_type") or "")
    parsed_chat = int(chat_id) if str(chat_id).lstrip("-").isdigit() else None
    if event_type in _ROUND_RESULT_EVENTS and parsed_chat is not None:
        if event_type == "roulette_table_settled":
            from games.roulette_card import drop as drop_roulette_card
            await drop_roulette_card(bot, parsed_chat)
        else:
            from games.jackpot_card import drop as drop_jackpot_card
            await drop_jackpot_card(bot, parsed_chat)
    sent = await bot.send_message(chat_id, text, **kwargs)
    if event_type in _ROUND_RESULT_EVENTS:
        from games.chat_reaper import TTL_ROUND, track_group_result, track_sent

        if parsed_chat is not None and parsed_chat < 0:
            track_group_result(parsed_chat, sent)
        else:
            track_sent(chat_id, sent, TTL_ROUND)


async def run_outbox_pass(
    bot: Any,
    client: Any,
    *,
    worker_id: str,
    limit: int = RECOVERY_BATCH_SIZE,
    lease_seconds: int = RECOVERY_LEASE_SECONDS,
) -> int:
    """Deliver one bounded notification batch independently of money recovery."""
    response = await client.claim_outbox_messages(
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
    )
    if not isinstance(response, Mapping):
        raise ValueError("Outbox claim response must be an object")

    processed = 0
    for message in _require_claim_items(response, kind="Outbox"):
        outbox_id = message.get("outbox_id")
        claim_token = message.get("claim_token")
        if not isinstance(outbox_id, (str, int)) or not isinstance(claim_token, str) or not claim_token:
            raise ValueError("Outbox message is missing outbox_id or claim_token")
        try:
            await _deliver_outbox_message(bot, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Outbox delivery failed for %s", outbox_id, exc_info=True)
            error_kind, retry_after_seconds = classify_telegram_delivery_error(exc)
            await client.fail_outbox_message(
                outbox_id=outbox_id,
                claim_token=claim_token,
                error=str(exc),
                error_kind=error_kind,
                retry_after_seconds=retry_after_seconds,
            )
        else:
            await client.complete_outbox_message(
                outbox_id=outbox_id,
                claim_token=claim_token,
            )
        processed += 1
    return processed


async def recovery_outbox_loop(bot: Any, client: Any, *, worker_id: str) -> None:
    """Repeatedly run bounded backend-driven work until cancelled."""
    try:
        while True:
            # A broken recovery claim must not starve result delivery (or V2).
            for stage in (
                lambda: run_recovery_pass(client, worker_id=worker_id),
                lambda: run_outbox_pass(bot, client, worker_id=worker_id),
            ):
                try:
                    await stage()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Casino legacy worker stage failed; continuing other work")
            try:
                from games.pvp import sync_active_pvp_from_backend
                from games.v2_runtime import run_v2_outbox_pass, run_v2_recovery_pass
                for stage in (
                    lambda: sync_active_pvp_from_backend(bot, client),
                    lambda: run_v2_recovery_pass(client, worker_id=worker_id),
                    lambda: run_v2_outbox_pass(bot, client, worker_id=worker_id),
                ):
                    try:
                        await stage()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Casino V2 worker stage failed; continuing other work")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Casino recovery/outbox pass failed; work remains leased or retryable")
            await asyncio.sleep(RECOVERY_POLL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Casino recovery/outbox worker cancelled")
        raise
