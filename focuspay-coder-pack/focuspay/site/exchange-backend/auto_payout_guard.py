"""Fail-closed предохранитель: signer heartbeat + hot balance."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from auto_settings import auto_min_hot_balance_rub
from db import get_pool

logger = logging.getLogger("auto_payout_guard")

_SIGNER_STALE_SEC = 120


async def signer_circuit_closed(conn=None) -> bool:
    """False = авто-реквизиты и авто-выплаты запрещены."""
    pool = await get_pool()
    use_conn = conn
    if use_conn is None:
        async with pool.acquire() as acquired:
            return await _circuit_inner(acquired)
    return await _circuit_inner(use_conn)


async def _circuit_inner(conn) -> bool:
    try:
        row = await conn.fetchrow(
            """
            SELECT signer_ok, recorded_at
            FROM hot_wallet_balances
            ORDER BY recorded_at DESC
            LIMIT 1
            """
        )
    except Exception:
        # Таблицы нет или запрос не прошёл — fail closed, авто запрещено.
        logger.warning("signer heartbeat unavailable, circuit open", exc_info=True)
        return False
    if not row:
        return False
    if not row["signer_ok"]:
        return False
    recorded = row["recorded_at"]
    if isinstance(recorded, datetime):
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - recorded.astimezone(timezone.utc)
        if age > timedelta(seconds=_SIGNER_STALE_SEC):
            logger.warning("signer heartbeat stale age=%ss", int(age.total_seconds()))
            return False
    min_rub = auto_min_hot_balance_rub()
    if min_rub > 0:
        spendable_rub = await hot_spendable_rub(conn)
        if spendable_rub < min_rub:
            logger.warning(
                "hot wallet below floor: %.2f < %.2f", spendable_rub, min_rub
            )
            return False
    return True


def order_coin(crypto: str | None) -> str:
    """btc из BTC, usdt из USDT_TRC20."""
    return str(crypto or "").split("_")[0].strip().lower()


async def coin_spendable(coin: str) -> float | None:
    """Сколько этой монеты можно отправить сейчас.

    None — подписант не ответил. 0 — монеты в ответе нет.
    """
    from hot_wallet_topups import effective_spendable
    from signer_client import fetch_signer_balances, signer_configured

    name = order_coin(coin)
    if not name or not signer_configured():
        return None
    try:
        bal = await fetch_signer_balances()
    except Exception:
        logger.warning("signer balance unavailable for %s", name, exc_info=True)
        return None
    if not bal.get("ok"):
        return None
    coins = bal.get("coins") or {}
    row = coins.get(name) if isinstance(coins, dict) else None
    if not isinstance(row, dict) or "spendable" not in row:
        return 0.0
    return effective_spendable(row)


async def reserved_buy_crypto(conn, coin: str) -> float:
    """Сколько этой монеты уже обещано открытым покупкам без выплаты."""
    name = order_coin(coin)
    if not name:
        return 0.0
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(crypto_amount), 0)::float
        FROM orders
        WHERE upper(direction) = 'BUY'
          AND lower(split_part(COALESCE(crypto, ''), '_', 1)) = $1
          AND COALESCE(btrim(payout_tx_hash), '') = ''
          AND upper(status) NOT IN ('CANCELED', 'EXPIRED', 'FAILED', 'PAID')
          AND (
            upper(status) IN ('COMPLETED', 'DISPUTE')
            OR expires_at IS NULL
            OR expires_at > now()
          )
        """,
        name,
    )
    return max(0.0, float(val or 0))


async def hot_spendable_rub(conn) -> float:
    """Рублёвая оценка доступного запаса по последнему снимку каждой монеты."""
    from hot_wallet_monitor import HEARTBEAT_COIN

    try:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(value_rub), 0)::float
            FROM (
                SELECT DISTINCT ON (coin) coin, value_rub, recorded_at
                FROM hot_wallet_balances
                WHERE coin <> $1
                ORDER BY coin, recorded_at DESC
            ) t
            WHERE recorded_at > now() - interval '10 minutes'
            """,
            HEARTBEAT_COIN,
        )
    except Exception:
        logger.warning("hot wallet balance query failed", exc_info=True)
        return 0.0
    return float(val or 0)
