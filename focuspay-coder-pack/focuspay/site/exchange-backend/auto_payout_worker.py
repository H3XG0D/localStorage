"""Фоновый воркер: reserved withdrawals + BUY COMPLETED auto payouts.

Инварианты:
- никаких HTTP-вызовов внутри транзакции и под FOR UPDATE;
- заявка «забирается» атомарным UPDATE ... WHERE status = 'reserved';
- деньги не уходят дважды: signer идемпотентен по request_id, а статус
  'sending' + сверка по request_id исключают повторную отправку.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from auto_payout_audit_log import audit_payout_event
from auto_settings import (
    auto_payout_daily_cap_rub,
    auto_payout_enabled,
    auto_payout_max_rub,
)
from db import get_pool
from signer_client import fetch_signer_payout, submit_signer_payout

logger = logging.getLogger("auto_payout_worker")

_TICK_SEC = 15
_MAX_ATTEMPTS = 5
_SENDING_RECHECK_SEC = 60


class PartialHoldError(RuntimeError):
    """Резерв собран не полностью — транзакция должна откатиться."""

    def __init__(self, held: float, need: float) -> None:
        super().__init__(f"partial hold {held:.2f} of {need:.2f}")
        self.held = held
        self.need = need


def should_autosend_buy(row, verdict: str | None) -> bool:
    """Заявка, рождённая автопилотом, или обычная покупка, которая сейчас прошла бы сама.

    Второе нужно, когда оператор на смене: клиент всё равно получает монеты с кошелька
    проекта, а люди на смене получают 5% присутствия, не ведя выплату руками.
    """
    if row.get("auto_served"):
        return True
    return str(verdict or "") == "auto"


async def _coin_funds(coin: str) -> tuple[float, float] | None:
    """(можно тратить сейчас, ждёт подтверждения)."""
    from hot_wallet_topups import effective_spendable
    from signer_client import fetch_signer_balances, signer_configured

    if not signer_configured():
        return None
    try:
        bal = await fetch_signer_balances()
    except Exception:
        logger.warning("signer balance unavailable", exc_info=True)
        return None
    if not bal.get("ok"):
        return None
    row = (bal.get("coins") or {}).get(coin)
    if not isinstance(row, dict) or "spendable" not in row:
        return None
    spendable = effective_spendable(row)
    pending = max(0.0, float(row.get("unconfirmed") or 0))
    if spendable > float(row.get("spendable") or 0):
        # Доверенная часть уже в spendable_fast и одновременно лежит в unconfirmed.
        pending = max(0.0, pending - (spendable - float(row.get("spendable") or 0)))
    return spendable, pending


async def _mark_auto_served(conn, order_id: str) -> None:
    await conn.execute(
        "UPDATE orders SET auto_served = TRUE WHERE order_id = $1",
        order_id,
    )


async def _signer_is_dry_run() -> bool:
    """Холостой подписант отдаёт фейковый хеш. Таким хешем заявку закрывать нельзя."""
    from signer_client import fetch_signer_health, signer_configured

    if not signer_configured():
        return False
    try:
        health = await fetch_signer_health()
    except Exception:
        logger.warning("signer health failed", exc_info=True)
        return False
    return health.get("dry_run") is True


async def _notify_ops(text: str) -> None:
    try:
        from telegram_notify import send_admin_message

        await send_admin_message(text)
    except Exception:
        logger.warning("ops notify failed: %s", text, exc_info=True)


async def _enqueue_payout_request(
    conn,
    *,
    request_id: str,
    kind: str,
    ref_id: str,
    user_id: int | None,
    coin: str,
    address: str,
    amount_crypto: float | None,
    amount_rub: float | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO payout_requests (
            request_id, kind, ref_id, user_id, coin, address,
            amount_crypto, amount_rub, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'queued')
        ON CONFLICT (request_id) DO NOTHING
        """,
        request_id,
        kind,
        ref_id,
        user_id,
        coin.lower(),
        address.strip(),
        Decimal(str(amount_crypto)) if amount_crypto is not None else None,
        Decimal(str(amount_rub)) if amount_rub is not None else None,
    )


async def _set_request_amount(conn, request_id: str, amount_crypto: float) -> None:
    await conn.execute(
        """
        UPDATE payout_requests
        SET amount_crypto = $2, updated_at = now()
        WHERE request_id = $1
        """,
        request_id,
        Decimal(str(amount_crypto)),
    )


async def _mark_request(conn, request_id: str, status: str, txid: str | None = None) -> None:
    await conn.execute(
        """
        UPDATE payout_requests
        SET status = $2,
            txid = COALESCE($3, txid),
            sent_at = CASE WHEN $2 = 'sent' THEN now() ELSE sent_at END,
            updated_at = now()
        WHERE request_id = $1
        """,
        request_id,
        status,
        txid or None,
    )


async def _daily_auto_total_rub(conn) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM payout_requests
        WHERE created_at >= date_trunc('day', now())
          AND kind IN ('buy_order', 'withdrawal')
          AND status IN ('queued', 'sent', 'confirmed')
        """
    )
    return float(val or 0)


async def daily_cap_room(conn) -> float:
    cap = auto_payout_daily_cap_rub()
    if cap <= 0:
        return 0.0
    return max(0.0, cap - await _daily_auto_total_rub(conn))


# ---------------------------------------------------------------- withdrawals


async def _settle_shortfall(conn, row) -> float:
    """Сколько не хватит process_withdrawal_paid для списания (0 — хватает).

    Та же формула, что в финальном списании: иначе крипта уйдёт, а списание
    с баланса упадёт уже после отправки.
    """
    from casino_wagering import locked_by_wagering
    from user_unified_balance import unified_available

    user_id = int(row["referrer_user_id"])
    amount = float(row["amount_rub"])
    available = float(await unified_available(conn, user_id))
    # Своя сумма уже вычтена: как pending-заявка или как hold-строки (reserved).
    available += amount
    available -= float(await locked_by_wagering(conn, user_id))
    return max(0.0, amount - available)


async def _quote_crypto_amount(row) -> tuple[float | None, float | None]:
    """RUB → coin ровно тем же путём, что видит оператор в очереди выводов."""
    from crypto_network_fee import quote_withdraw_crypto
    from routers.public import get_rates_cached

    try:
        rates = await get_rates_cached() or {}
    except Exception:
        logger.warning("rates unavailable for auto withdrawal", exc_info=True)
        rates = {}
    quote = quote_withdraw_crypto(
        method=str(row.get("method") or ""),
        crypto=str(row.get("crypto") or ""),
        amount_rub=row.get("amount_rub"),
        payout_amount_rub=row.get("payout_amount_rub"),
        network_fee_rub=row.get("network_fee_rub"),
        rates=rates,
    )
    amount = quote.get("payout_crypto_amount")
    rate = quote.get("rate_rub")
    return (float(amount) if amount else None, float(rate) if rate else None)


async def _requeue_withdrawal(wd_id: int, reason: str, *, give_up: bool) -> None:
    """Возврат в очередь: give_up → снимаем резерв и отдаём оператору."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if give_up:
                from auto_withdraw_holds import release_withdrawal_holds

                await release_withdrawal_holds(conn, wd_id)
            await conn.execute(
                """
                UPDATE user_referral_withdrawals
                SET status = $2, auto_reason = $3
                WHERE id = $1 AND status IN ('reserved', 'sending')
                """,
                wd_id,
                "pending" if give_up else "reserved",
                reason[:200],
            )
            if give_up:
                await _mark_request(conn, f"wd:{wd_id}", "failed")
    await audit_payout_event(
        f"wd:{wd_id}", "manual_handoff" if give_up else "retry", {"reason": reason}
    )
    if give_up:
        await _notify_ops(
            f"⚠️ Автовывод #{wd_id} передан оператору: {reason}. Резерв снят, баланс возвращён."
        )


async def _settle_withdrawal(wd_id: int, request_id: str, txid: str) -> None:
    from user_referral_withdraw import (
        notify_withdrawal_completed,
        process_withdrawal_paid,
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _mark_request(conn, request_id, "confirmed", txid)
    # Отдельное соединение и своя транзакция внутри: нельзя держать FOR UPDATE.
    paid, err = await process_withdrawal_paid(
        wd_id, payout_tx_hash=txid, from_autopilot=True
    )
    if paid:
        await audit_payout_event(request_id, "paid", {"txid": txid})
        # Как у операторского /paid: клиент + правка сообщения в ops-группе.
        try:
            await notify_withdrawal_completed(paid, tx_hash=txid)
        except Exception:
            logger.exception("auto withdrawal notify failed id=%s", wd_id)
            await _notify_ops(
                f"⚠️ Автовывод #{wd_id} оплачен (tx <code>{txid}</code>), "
                "но уведомления клиенту/ops не ушли — проверьте вручную."
            )
        return
    logger.warning("withdrawal paid hook failed id=%s err=%s", wd_id, err)
    await audit_payout_event(request_id, "paid_hook_failed", {"txid": txid, "error": err})
    await _notify_ops(
        f"❗️ Автовывод #{wd_id} отправлен (tx <code>{txid}</code>), "
        f"но списание с баланса не прошло: {err}. Нужна ручная сверка."
    )


async def _process_reserved_withdrawal(wd_id: int) -> None:
    pool = await get_pool()
    request_id = f"wd:{wd_id}"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE user_referral_withdrawals
            SET status = 'sending',
                auto_attempts = COALESCE(auto_attempts, 0) + 1,
                auto_sent_at = now()
            WHERE id = $1 AND status = 'reserved'
            RETURNING *
            """,
            wd_id,
        )
        if not row:
            return
        attempts = int(row.get("auto_attempts") or 1)
        payout_rub = float(row.get("payout_amount_rub") or row["amount_rub"])
        coin = str(row.get("crypto") or "").split("_")[0].lower()
        address = str(row.get("requisites") or "").strip()
        shortfall = await _settle_shortfall(conn, row)
        amount_crypto, rate = await _quote_crypto_amount(row)
        if amount_crypto and amount_crypto > 0:
            await _set_request_amount(conn, request_id, amount_crypto)

    if shortfall > 0.01:
        await _requeue_withdrawal(
            wd_id, f"balance_shortfall:{shortfall:.2f}", give_up=True
        )
        return
    if not amount_crypto or amount_crypto <= 0:
        await _requeue_withdrawal(
            wd_id, "rate_unavailable", give_up=attempts >= _MAX_ATTEMPTS
        )
        return
    if not address or coin not in ("btc", "ltc"):
        await _requeue_withdrawal(wd_id, f"unsupported_coin:{coin}", give_up=True)
        return
    if await _signer_is_dry_run():
        await _requeue_withdrawal(wd_id, "dry_run", give_up=True)
        return

    body = {
        "request_id": request_id,
        "coin": coin,
        "address": address,
        "amount": amount_crypto,
        "amount_rub": round(payout_rub, 2),
        "order_ref": str(wd_id),
        "kind": "withdrawal",
    }
    st, resp = await submit_signer_payout(body)
    await audit_payout_event(request_id, f"signer_{st}", {"rate_rub": rate, **resp})

    if st in ("accepted", "duplicate"):
        txid = str(resp.get("txid") or "")
        if txid:
            await _settle_withdrawal(wd_id, request_id, txid)
        else:
            async with pool.acquire() as conn:
                await _mark_request(conn, request_id, "sent")
        return
    if st == "rejected":
        reason = str(resp.get("reason") or resp.get("error") or "signer_rejected")
        await _requeue_withdrawal(wd_id, f"signer_rejected:{reason}", give_up=True)
        return
    # unknown: отправка могла состояться. Оставляем 'sending' и сверяем по request_id.
    await _notify_ops(
        f"⏳ Автовывод #{wd_id}: signer не ответил однозначно, ждём сверки по {request_id}."
    )


async def _reconcile_sending_withdrawal(wd_id: int) -> None:
    """Статус 'sending' висит: спрашиваем signer, что стало с request_id."""
    request_id = f"wd:{wd_id}"
    code, data = await fetch_signer_payout(request_id)
    st = str(data.get("status") or "").lower()
    txid = str(data.get("txid") or "")
    if st in ("sent", "confirmed") and txid:
        await _settle_withdrawal(wd_id, request_id, txid)
        return
    if code == 404 or st in ("not_found", "rejected"):
        await _requeue_withdrawal(wd_id, f"signer_no_record:{st or code}", give_up=True)
        return
    logger.info("withdrawal %s still in flight at signer: %s", wd_id, st or code)


# ---------------------------------------------------------------- buy orders


_PAYFAST_RETRY = frozenset({"payfast_api_error"})
# Payfast ещё не дал финальный апрув трейдера: ждём, а не отдаём оператору.
_PAYFAST_WAIT = frozenset(
    {
        "payfast_not_paid",
        "payfast_awaiting_trader",
        "payfast_check_pending",
        "payfast_recheck_requested",
    }
)
_PAYFAST_WAIT_MAX_SEC = 2 * 3600
_PAYFAST_RECHECK_SEC = 60
_payfast_next_check: dict[str, float] = {}


def _payfast_backoff_active(order_id: str) -> bool:
    import time

    return _payfast_next_check.get(order_id, 0.0) > time.monotonic()


def _payfast_backoff(order_id: str) -> None:
    import time

    _payfast_next_check[order_id] = time.monotonic() + _PAYFAST_RECHECK_SEC
    if len(_payfast_next_check) > 1000:
        now = time.monotonic()
        for k in [k for k, v in _payfast_next_check.items() if v < now]:
            _payfast_next_check.pop(k, None)


def _waited_too_long(row) -> bool:
    from datetime import datetime, timezone

    since = row.get("updated_at") or row.get("created_at")
    if not isinstance(since, datetime):
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - since).total_seconds() > _PAYFAST_WAIT_MAX_SEC


async def _fail_buy_to_operator(row, reason: str, *, coin: str, address: str) -> None:
    order_id = str(row["order_id"])
    request_id = f"order:{order_id}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _enqueue_payout_request(
            conn,
            request_id=request_id,
            kind="buy_order",
            ref_id=order_id,
            user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
            coin=coin,
            address=address,
            amount_crypto=float(row.get("crypto_amount") or 0),
            amount_rub=float(row.get("fiat_amount") or 0),
        )
        await _mark_request(conn, request_id, "failed")
        await conn.execute(
            "UPDATE payout_requests SET reject_reason = $2 WHERE request_id = $1",
            request_id,
            reason[:200],
        )
    # 'failed' исключает заявку из следующих тиков — уведомление уходит один раз.
    await _notify_ops(
        f"⚠️ Автовыплата по заявке {order_id} не отправлена ({reason}). "
        "Крипта не уходила, нужен оператор."
    )


async def _buy_preflight(order_id: str) -> tuple[bool, str]:
    """Проверки ДО отправки: Payfast реально оплачен и сумма крипты не больше оплаты.

    confirm_buy_payout делает то же самое, но уже после broadcast. Здесь отказ
    значит, что монеты ещё не ушли.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
    if not order:
        return False, "not_found"
    order_d = dict(order)
    if str(order_d.get("status") or "").upper() != "COMPLETED":
        return False, "wrong_status"
    if (order_d.get("payout_tx_hash") or "").strip():
        return False, "already_paid"

    from payin_requisite_rail import is_payin_order, order_reki_payfast_id

    if not is_payin_order(order_d) and not order_reki_payfast_id(order_d):
        from payfast_payin_guard import verify_payfast_ready_for_payout

        ok_pf, pf_err, _ = await verify_payfast_ready_for_payout(order_d, require_uuid=True)
        if not ok_pf:
            return False, pf_err or "payfast_not_ready"

    import os
    import sys

    bot_root = os.environ.get("TG_BOT_PATH", "/opt/tg_bot_btc")
    if bot_root not in sys.path:
        sys.path.append(bot_root)
    try:
        from services.buy_payout_validate import validate_buy_payout_crypto
    except Exception:
        logger.exception("buy payout validator unavailable")
        return False, "validator_unavailable"
    ok_amt, amt_err = validate_buy_payout_crypto(order_d)
    if not ok_amt:
        return False, amt_err or "amount_mismatch"
    return True, "ok"


async def _wait_or_fail_funds(
    row, reason: str, *, coin: str, address: str, amount_crypto: float,
    spendable: float, pending: float,
) -> None:
    """Денег не хватает: ждём подтверждения пополнения или отдаём оператору."""
    from hot_wallet_topups import can_wait_for_funds, forget_wait

    order_id = str(row["order_id"])
    if can_wait_for_funds(
        order_id, coin=coin, amount=amount_crypto, spendable=spendable, pending=pending
    ):
        logger.info("auto buy payout waits funds order=%s reason=%s", order_id, reason)
        _payfast_backoff(order_id)
        return
    if spendable + pending + 1e-12 >= amount_crypto:
        reason = "funds_wait_timeout"
    forget_wait(order_id)
    await _fail_buy_to_operator(row, reason, coin=coin, address=address)


async def _process_buy_order_row(row, room_rub: float) -> bool:
    from hot_wallet_topups import buy_request_id, forget_wait, payout_rows

    order_id = str(row["order_id"])
    coin = str(row.get("crypto") or "").split("_")[0].lower()
    if coin not in ("btc", "ltc"):
        return False
    fiat = float(row.get("fiat_amount") or 0)
    if fiat > auto_payout_max_rub() + 0.01 or fiat > room_rub + 0.01:
        return False
    address = str(row.get("requisites") or "").strip()
    amount_crypto = float(row.get("crypto_amount") or 0)
    if amount_crypto <= 0 or not address:
        return False
    if _payfast_backoff_active(order_id):
        return False

    try:
        ready, reason = await _buy_preflight(order_id)
    except Exception:
        logger.exception("buy preflight failed order=%s", order_id)
        return False
    if not ready:
        if reason in _PAYFAST_RETRY or reason in ("wrong_status", "already_paid", "not_found"):
            logger.info("auto buy payout waits order=%s reason=%s", order_id, reason)
            return False
        if reason in _PAYFAST_WAIT:
            if not _waited_too_long(row):
                logger.info("auto buy payout waits payfast order=%s reason=%s", order_id, reason)
                _payfast_backoff(order_id)
                return False
            reason = f"payfast_wait_timeout:{reason}"
        await _fail_buy_to_operator(row, reason, coin=coin, address=address)
        return False
    if await _signer_is_dry_run():
        await _fail_buy_to_operator(row, "dry_run", coin=coin, address=address)
        return False
    funds = await _coin_funds(coin)
    if funds is not None and funds[0] + 1e-12 < amount_crypto:
        await _wait_or_fail_funds(
            row, "insufficient_funds", coin=coin, address=address,
            amount_crypto=amount_crypto, spendable=funds[0], pending=funds[1],
        )
        return False

    pool = await get_pool()
    async with pool.acquire() as conn:
        request_id = buy_request_id(order_id, await payout_rows(conn, order_id))
    if request_id is None:
        logger.info("auto buy payout skipped order=%s: payout already in flight", order_id)
        return False

    from payout_wallet_confirm import resolve_payout_address

    approved = await resolve_payout_address(
        row,
        coin=coin,
        address=address,
        fiat=fiat,
        amount_crypto=amount_crypto,
    )
    if not approved:
        return False
    address = approved

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Тот же лок, что у ручной выплаты с кошелька проекта: иначе оператор и
            # автопилот могут одновременно отправить по одной заявке под разными request_id.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"pw:{order_id}")
            if buy_request_id(order_id, await payout_rows(conn, order_id)) != request_id:
                logger.info("auto buy payout skipped order=%s: payout rows changed", order_id)
                return False
            await _mark_auto_served(conn, order_id)
            await _enqueue_payout_request(
                conn,
                request_id=request_id,
                kind="buy_order",
                ref_id=order_id,
                user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
                coin=coin,
                address=address,
                amount_crypto=amount_crypto,
                amount_rub=fiat,
            )

    body = {
        "request_id": request_id,
        "coin": coin,
        "address": address,
        "amount": amount_crypto,
        "amount_rub": round(fiat, 2),
        "order_ref": order_id,
        "kind": "buy_order",
    }
    st, resp = await submit_signer_payout(body)
    await audit_payout_event(request_id, f"signer_{st}", resp)
    if st not in ("accepted", "duplicate"):
        if st == "rejected":
            signer_reason = str(resp.get("reason") or resp.get("error") or "")
            if signer_reason in ("insufficient_funds", "mempool_chain_limit"):
                # Монеты не уходили. Этот request_id подписант больше не примет:
                # следующая попытка пойдёт с суффиксом.
                from hot_wallet_topups import REQUEUED, can_wait_for_funds

                waiting = can_wait_for_funds(
                    order_id, coin=coin, amount=amount_crypto,
                    spendable=0.0, pending=amount_crypto,
                )
                async with pool.acquire() as conn:
                    await _mark_request(conn, request_id, REQUEUED if waiting else "failed")
                    await conn.execute(
                        "UPDATE payout_requests SET reject_reason = $2 WHERE request_id = $1",
                        request_id,
                        f"signer_rejected:{signer_reason}"[:200],
                    )
                if waiting:
                    _payfast_backoff(order_id)
                    return True
                forget_wait(order_id)
            else:
                async with pool.acquire() as conn:
                    await _mark_request(conn, request_id, "failed")
                    await conn.execute(
                        "UPDATE payout_requests SET reject_reason = $2 WHERE request_id = $1",
                        request_id,
                        f"signer_rejected:{signer_reason}"[:200],
                    )
            await _notify_ops(
                f"⚠️ Автовыплата по заявке {order_id} отклонена signer: "
                f"{signer_reason}. Нужен оператор."
            )
        return True
    forget_wait(order_id)
    txid = str(resp.get("txid") or "")
    if not txid:
        async with pool.acquire() as conn:
            await _mark_request(conn, request_id, "sent")
        return True

    from bot_status_bridge import confirm_buy_payout

    ok, err, _order = await confirm_buy_payout(
        order_id, tx_hash=txid, actor="auto", operator_id=None, force=False
    )
    async with pool.acquire() as conn:
        await _mark_request(conn, request_id, "confirmed" if ok else "sent", txid)
        if ok:
            await conn.execute(
                """
                UPDATE orders
                SET payout_confirmed_by = 'auto', payout_confirmed_at = now()
                WHERE order_id = $1
                """,
                order_id,
            )
            from auto_recon import record_auto_buy_payout
            from operator_payroll_split import accrue_autopilot_paid_order

            await record_auto_buy_payout(conn, order_id, fiat, coin, txid)
            await accrue_autopilot_paid_order(conn, order_id)
    if not ok:
        logger.warning("auto buy payout confirm failed order=%s err=%s", order_id, err)
        await _notify_ops(
            f"❗️ Заявка {order_id}: крипта отправлена (tx <code>{txid}</code>), "
            f"но подтверждение не прошло: {err}. Нужна ручная сверка."
        )
    return True


# ---------------------------------------------------------------------- tick


async def _handoff_reserved_when_disabled() -> None:
    """Тумблер выключен: reserved-заявки не должны вечно держать баланс."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        ids = [
            int(r["id"])
            for r in await conn.fetch(
                "SELECT id FROM user_referral_withdrawals WHERE status = 'reserved' LIMIT 20"
            )
        ]
    for wd_id in ids:
        try:
            await _requeue_withdrawal(wd_id, "auto_payout_disabled", give_up=True)
        except Exception:
            logger.exception("handoff reserved id=%s", wd_id)


async def _stale_sending_ids() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id FROM user_referral_withdrawals
            WHERE status = 'sending'
              AND COALESCE(auto_sent_at, created_at)
                  < now() - ($1 || ' seconds')::interval
            ORDER BY id ASC LIMIT 5
            """,
            str(_SENDING_RECHECK_SEC),
        )
    return [int(r["id"]) for r in rows]


async def _tick() -> None:
    try:
        from payout_wallet_confirm import sweep_due_wallet_confirms

        await sweep_due_wallet_confirms()
    except Exception:
        logger.exception("sweep due wallet confirms failed")

    # 'sending' сверяем всегда, даже при выключенном тумблере: отправка могла
    # уйти, и закрыть такую заявку может только сверка по request_id.
    for wd_id in await _stale_sending_ids():
        try:
            await _reconcile_sending_withdrawal(wd_id)
        except Exception:
            logger.exception("auto withdrawal reconcile id=%s", wd_id)

    if not auto_payout_enabled():
        await _handoff_reserved_when_disabled()
        return
    try:
        from hot_wallet_topups import resume_btc_funds_failures

        await resume_btc_funds_failures()
    except Exception:
        logger.exception("resume btc unconfirmed failed")
    pool = await get_pool()
    async with pool.acquire() as conn:
        room = await daily_cap_room(conn)
        reserved = [
            int(r["id"])
            for r in await conn.fetch(
                """
                SELECT id FROM user_referral_withdrawals
                WHERE status = 'reserved'
                ORDER BY id ASC LIMIT 5
                """
            )
        ]
        # Уже отправленные/отклонённые не берём: signer ответит duplicate/rejected,
        # а повтор каждые 15 с только спамит. Их разбирает человек.
        buy_rows = await conn.fetch(
            """
            SELECT o.order_id, o.user_id, o.crypto, o.crypto_amount, o.fiat_amount, o.requisites,
                   o.created_at, o.updated_at, o.status, o.direction, o.auto_served
            FROM orders o
            WHERE upper(o.direction) = 'BUY'
              AND o.status = 'COMPLETED'
              AND lower(split_part(COALESCE(o.crypto, ''), '_', 1)) IN ('btc', 'ltc')
              AND o.payout_tx_hash IS NULL
              AND o.requisites IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM payout_requests pr
                  WHERE pr.ref_id = o.order_id
                    AND (
                      (pr.kind = 'buy_order' AND pr.status IN ('sent', 'confirmed', 'failed'))
                      OR pr.kind = 'manual_buy'
                    )
              )
            ORDER BY o.updated_at ASC
            LIMIT 20
            """
        )
        try:
            from auto_preview import build_preview_context, preview_order_autopay

            ctx = await build_preview_context(conn, (r["user_id"] for r in buy_rows))
            buy_rows = [
                row
                for row in buy_rows
                if should_autosend_buy(
                    row,
                    str(preview_order_autopay(dict(row), ctx).get("verdict") or ""),
                )
            ]
        except Exception:
            logger.exception("auto buy eligibility failed, keeping only auto_served")
            buy_rows = [row for row in buy_rows if row.get("auto_served")]

    # Резервы выводов уже учтены в payout_requests при reserve — их отправляем
    # даже при исчерпанном лимите: деньги клиента уже заморожены под эту выплату.
    for wd_id in reserved:
        try:
            await _process_reserved_withdrawal(wd_id)
        except Exception:
            logger.exception("auto withdrawal tick id=%s", wd_id)

    if room <= 0 and buy_rows:
        logger.info("auto payout daily cap reached, buy payouts wait for operator")
        return
    for row in buy_rows:
        fiat = float(row.get("fiat_amount") or 0)
        if fiat > room + 0.01:
            continue
        try:
            if await _process_buy_order_row(row, room):
                room -= fiat
        except Exception:
            logger.exception("auto buy payout tick order=%s", row["order_id"])

    from hot_wallet_topups import take_new_waiting, wait_notice

    notice = wait_notice(take_new_waiting())
    if notice:
        await _notify_ops(notice)


async def auto_payout_worker_loop() -> None:
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("auto_payout_worker tick failed")
        await asyncio.sleep(_TICK_SEC)


async def reserve_withdrawal_for_auto(withdrawal_id: int) -> bool:
    """После create_withdrawal: hold + reserved + очередь payout_requests."""
    pool = await get_pool()
    reserved = False
    async with pool.acquire() as conn:
        async with conn.transaction():
            wd = await conn.fetchrow(
                "SELECT * FROM user_referral_withdrawals WHERE id = $1 FOR UPDATE",
                withdrawal_id,
            )
            if not wd or wd["status"] != "pending":
                return False
            from auto_withdraw_holds import hold_unified_withdrawal

            amount_rub = float(wd["amount_rub"])
            shortfall = await _settle_shortfall(conn, wd)
            if shortfall > 0.01:
                raise PartialHoldError(amount_rub - shortfall, amount_rub)
            held = await hold_unified_withdrawal(
                conn, int(wd["referrer_user_id"]), withdrawal_id, amount_rub
            )
            if held + 0.01 < amount_rub:
                # Частичный резерв недопустим: откатываем транзакцию целиком,
                # заявка остаётся pending и уходит оператору.
                raise PartialHoldError(held, amount_rub)
            await conn.execute(
                "UPDATE user_referral_withdrawals SET status = 'reserved' WHERE id = $1",
                withdrawal_id,
            )
            await _enqueue_payout_request(
                conn,
                request_id=f"wd:{withdrawal_id}",
                kind="withdrawal",
                ref_id=str(withdrawal_id),
                user_id=int(wd["referrer_user_id"]),
                coin=str(wd.get("crypto") or "").split("_")[0].lower(),
                address=str(wd["requisites"]),
                amount_crypto=None,
                amount_rub=amount_rub,
            )
            reserved = True
    await audit_payout_event(
        f"wd:{withdrawal_id}", "reserved", {"withdrawal_id": withdrawal_id}
    )
    return reserved
