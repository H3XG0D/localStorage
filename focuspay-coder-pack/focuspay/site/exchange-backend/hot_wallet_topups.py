"""Пополнения горячего кошелька: ожидание подтверждения, доверенные пополнения, возврат в автопилот."""
from __future__ import annotations

import logging
import time
from typing import Any

from auto_settings import auto_payout_trusted_topups, auto_payout_wait_funds_max_min

logger = logging.getLogger("hot_wallet_topups")

# Отказы, после которых выплата может пройти сама, как только деньги подтвердятся.
FUNDS_REASONS = frozenset(
    {
        "insufficient_funds",
        "funds_wait_timeout",
        "mempool_chain_limit",
        "signer_rejected:insufficient_funds",
        "signer_rejected:mempool_chain_limit",
    }
)
REQUEUED = "requeued"

# order_id -> (monotonic since, coin, amount)
_waiting: dict[str, tuple[float, str, float]] = {}
_announced: set[str] = set()
_alerted_topups: set[str] = set()
_resumed_at: dict[str, float] = {}
_RESUME_COOLDOWN_SEC = 60.0


def effective_spendable(row: dict[str, Any] | None) -> float:
    """Сколько можно потратить прямо сейчас с учётом доверенных пополнений."""
    if not isinstance(row, dict):
        return 0.0
    spend = float(row.get("spendable") or 0)
    if auto_payout_trusted_topups() and row.get("spendable_fast") is not None:
        return max(spend, float(row.get("spendable_fast") or 0))
    return spend


def pending_unconfirmed(row: dict[str, Any] | None) -> float:
    """Пополнения в пути, которые ещё нельзя потратить (доверенные уже в effective_spendable)."""
    if not isinstance(row, dict):
        return 0.0
    extra = effective_spendable(row) - float(row.get("spendable") or 0)
    return round(max(0.0, float(row.get("unconfirmed") or 0) - extra), 8)


def can_wait_for_funds(
    order_id: str,
    *,
    coin: str,
    amount: float,
    spendable: float,
    pending: float,
    now: float | None = None,
) -> bool:
    """True — денег хватит после подтверждения пополнения, и ждём не дольше лимита."""
    if spendable + pending + 1e-12 < amount:
        forget_wait(order_id)
        return False
    max_sec = auto_payout_wait_funds_max_min() * 60
    if max_sec <= 0:
        return False
    t = time.monotonic() if now is None else now
    since = _waiting.setdefault(order_id, (t, coin, amount))[0]
    return t - since <= max_sec


def forget_wait(order_id: str) -> None:
    _waiting.pop(order_id, None)
    _announced.discard(order_id)


def waiting_snapshot(now: float | None = None) -> list[dict[str, Any]]:
    t = time.monotonic() if now is None else now
    return [
        {"order_id": oid, "coin": coin, "amount": amount, "waiting_sec": int(t - since)}
        for oid, (since, coin, amount) in sorted(_waiting.items(), key=lambda kv: kv[1][0])
    ]


def take_new_waiting() -> list[dict[str, Any]]:
    """Ожидающие, о которых владелец ещё не знает. Каждая заявка — один раз."""
    fresh = [w for w in waiting_snapshot() if w["order_id"] not in _announced]
    _announced.update(w["order_id"] for w in fresh)
    return fresh


def wait_notice(fresh: list[dict[str, Any]]) -> str | None:
    if not fresh:
        return None
    total: dict[str, float] = {}
    for w in fresh:
        total[w["coin"]] = total.get(w["coin"], 0.0) + float(w["amount"])
    sums = ", ".join(f"{amt:.8f} {coin.upper()}" for coin, amt in sorted(total.items()))
    return (
        f"⏳ {len(fresh)} автовыплат ждут подтверждения пополнения горячего кошелька ({sums}). "
        f"Уйдут сами после 1 подтверждения, через {auto_payout_wait_funds_max_min()} мин без "
        "подтверждения — оператору."
    )


def buy_request_id(order_id: str, rows: list[dict[str, Any]]) -> str | None:
    """request_id для автовыплаты. None — по заявке уже есть живая отправка.

    Подписант помнит отказ навсегда, поэтому повтор после возврата в автопилот
    идёт с суффиксом, как и у ручной выплаты с кошелька проекта.
    """
    base = f"order:{order_id}"
    for row in rows:
        status = str(row.get("status") or "")
        kind = str(row.get("kind") or "")
        if str(row.get("txid") or "").strip():
            return None
        if kind != "buy_order":
            return None
        if status not in ("queued", REQUEUED):
            return None
    for row in rows:
        if row.get("kind") == "buy_order" and row.get("status") == "queued":
            return str(row["request_id"])
    if not rows:
        return base
    return f"{base}-r{len(rows)}"


def requeue_block_reason(order: dict[str, Any] | None, rows: list[dict[str, Any]]) -> str | None:
    """Почему заявку нельзя вернуть в автопилот (None — можно)."""
    if not order:
        return "not_found"
    if str(order.get("status") or "").upper() != "COMPLETED":
        return "wrong_status"
    if str(order.get("payout_tx_hash") or "").strip():
        return "already_paid"
    buy_rows = [r for r in rows if r.get("kind") == "buy_order"]
    if not any(
        r.get("status") == "failed" and str(r.get("reject_reason") or "") in FUNDS_REASONS
        for r in buy_rows
    ):
        return "not_funds_failure"
    for row in rows:
        if str(row.get("txid") or "").strip():
            return "already_sent"
        if row.get("kind") != "buy_order":
            return "manual_send"
        if row.get("kind") == "buy_order" and row.get("status") in ("queued", "sent", "confirmed"):
            return "already_sent"
    return None


async def payout_rows(conn, order_id: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT request_id, kind, status, txid, reject_reason, created_at
        FROM payout_requests
        WHERE ref_id = $1 AND kind IN ('buy_order', 'manual_buy')
        ORDER BY created_at ASC
        """,
        order_id,
    )
    return [dict(r) for r in rows]


def btc_failures_covered(
    items: list[dict[str, Any]],
    spendable: float,
    *,
    now: float,
    resumed_at: dict[str, float],
) -> list[str]:
    """Заявки BTC, которым уже хватает монет, включая неподтверждённые."""
    out: list[str] = []
    for item in items or []:
        if str(item.get("coin") or "").lower() != "btc":
            continue
        order_id = str(item.get("order_id") or "")
        amount = float(item.get("amount_crypto") or 0)
        if not order_id or amount <= 0 or spendable + 1e-12 < amount:
            continue
        if now - float(resumed_at.get(order_id) or 0) < _RESUME_COOLDOWN_SEC:
            continue
        out.append(order_id)
    return out


async def resume_btc_funds_failures() -> list[str]:
    """Вернуть в автопилот покупки BTC, которые не ушли из-за пустого кошелька.

    Как только неподтверждённое пополнение уже можно тратить, заявка снова
    попадает в очередь. LTC ждёт обычное подтверждение.
    """
    if not auto_payout_trusted_topups():
        return []
    from signer_client import fetch_signer_balances, signer_configured

    if not signer_configured():
        return []
    try:
        bal = await fetch_signer_balances()
    except Exception:
        logger.warning("signer balance unavailable for btc resume", exc_info=True)
        return []
    if not bal.get("ok"):
        return []
    row = (bal.get("coins") or {}).get("btc")
    spendable = effective_spendable(row if isinstance(row, dict) else None)
    if spendable <= 0:
        return []
    from db import get_pool

    now = time.monotonic()
    done: list[str] = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        covered = btc_failures_covered(
            await list_funds_failures(conn),
            spendable,
            now=now,
            resumed_at=_resumed_at,
        )
        for order_id in covered:
            _resumed_at[order_id] = now
            reason = await requeue_buy_order(conn, order_id)
            if reason:
                logger.info("btc resume skipped %s: %s", order_id, reason)
                continue
            done.append(order_id)
            logger.info("btc payout resumed, spendable %.8f order %s", spendable, order_id)
    if done:
        try:
            from telegram_notify import send_admin_message

            ids = ", ".join(done)
            await send_admin_message(
                f"Автовыплата снова в очереди ({ids}): неподтверждённый BTC уже можно отправить."
            )
        except Exception:
            logger.warning("btc resume notify failed", exc_info=True)
    return done


async def requeue_buy_order(conn, order_id: str) -> str | None:
    """Вернуть заявку в автопилот. Возвращает причину отказа или None."""
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"pw:{order_id}")
        order = await conn.fetchrow(
            "SELECT order_id, status, payout_tx_hash FROM orders WHERE order_id = $1 FOR UPDATE",
            order_id,
        )
        rows = await payout_rows(conn, order_id)
        reason = requeue_block_reason(dict(order) if order else None, rows)
        if reason:
            return reason
        await conn.execute(
            """
            UPDATE payout_requests SET status = $2, updated_at = now()
            WHERE ref_id = $1 AND kind = 'buy_order' AND status = 'failed'
            """,
            order_id,
            REQUEUED,
        )
        # Выплату ведёт автопилот: заявка не должна зависеть от того, кто сейчас на смене.
        await conn.execute(
            "UPDATE orders SET auto_served = TRUE WHERE order_id = $1", order_id
        )
    forget_wait(order_id)
    return None


async def list_funds_failures(conn, limit: int = 30) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (pr.ref_id)
               pr.ref_id AS order_id, pr.request_id, pr.coin, pr.amount_crypto, pr.amount_rub,
               pr.reject_reason, pr.updated_at, o.user_id, bu.username, bu.first_name
        FROM payout_requests pr
        JOIN orders o ON o.order_id = pr.ref_id
        LEFT JOIN bot_users bu ON bu.user_id = o.user_id
        WHERE pr.kind = 'buy_order'
          AND pr.status = 'failed'
          AND pr.reject_reason = ANY($1::text[])
          AND o.status = 'COMPLETED'
          AND o.payout_tx_hash IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM payout_requests x
              WHERE x.ref_id = pr.ref_id
                AND (
                  x.kind = 'manual_buy'
                  OR x.txid IS NOT NULL
                  OR x.status IN ('queued', 'sent', 'confirmed')
                )
          )
        ORDER BY pr.ref_id, pr.updated_at DESC
        LIMIT $2
        """,
        list(FUNDS_REASONS),
        int(limit),
    )
    out = []
    for r in rows:
        name = r["username"]
        out.append(
            {
                "order_id": r["order_id"],
                "request_id": r["request_id"],
                "coin": r["coin"],
                "amount_crypto": float(r["amount_crypto"]) if r["amount_crypto"] is not None else None,
                "amount_rub": float(r["amount_rub"] or 0),
                "reject_reason": r["reject_reason"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                "user_id": r["user_id"],
                "username": f"@{name}" if name and not str(name).startswith("@") else name,
                "first_name": r["first_name"],
            }
        )
    return out


def topup_alerts(items: list[dict[str, Any]]) -> list[str]:
    """Доверенное пополнение пропало или заменено: выплаты из него тоже пропадут."""
    out = []
    for item in items or []:
        txid = str(item.get("txid") or "")
        status = str(item.get("status") or "")
        if status not in ("conflicted", "dropped") or not txid or txid in _alerted_topups:
            continue
        _alerted_topups.add(txid)
        out.append(
            f"🚨 Доверенное пополнение <code>{txid}</code> — {status}. Автовыплаты, потраченные "
            "из него до подтверждения, могут пропасть из сети. Проверьте их по ноде и "
            "отключите «Доверенные пополнения» до разбора."
        )
    return out


async def alert_topup_tick() -> None:
    if not auto_payout_trusted_topups():
        return
    from signer_client import fetch_signer_topups, signer_configured

    if not signer_configured():
        return
    data = await fetch_signer_topups("btc")
    if not data.get("ok"):
        return
    for text in topup_alerts(data.get("items") or []):
        try:
            from telegram_notify import send_admin_message

            await send_admin_message(text)
        except Exception:
            logger.warning("topup alert failed: %s", text, exc_info=True)
