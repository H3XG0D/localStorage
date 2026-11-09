"""Черновик повторного запроса реквизитов.

Не строка в orders: кабинет, админка и отстук его не видят.
Окно 30 минут с первого отказа. Кнопка жмёт мерчанта не чаще раза в 5 минут
и срок не продлевает. Тихий и обычный бан черновик не получают.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from db import get_pool
from payin_requisite_rail import buy_paid_count

logger = logging.getLogger("requisite_retry")

MIN_PAID_BUYS = 5
WINDOW = timedelta(minutes=30)
COOLDOWN = timedelta(minutes=5)

_EMPTY = (
    "Реквизитов всё ещё нет. Следующая попытка через 5 минут."
)
_SAVED = (
    "Сейчас нет свободных реквизитов. "
    "Параметры сделки сохранены на 30 минут. "
    "Повторить запрос можно раз в 5 минут."
)


def snapshot_is_requisite_retry(snapshot: Any) -> bool:
    if not snapshot:
        return False
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError:
            return False
    return bool(isinstance(snapshot, dict) and snapshot.get("requisite_retry"))


def split_crypto(crypto: str) -> tuple[str, str | None]:
    raw = str(crypto or "").strip()
    parts = raw.split("_", 1)
    coin = parts[0].lower()
    network = parts[1].lower() if len(parts) > 1 and parts[1] else None
    return coin, network


def wallet_coin_supported(coin: str, *, requisite_retry: bool) -> bool:
    """BTC/LTC подтверждают всегда. USDT/TRX — только у заявки из черновика."""
    code = str(coin or "").split("_", 1)[0].lower()
    if code in ("btc", "ltc"):
        return True
    return bool(requisite_retry) and code in ("usdt", "trx")


def kept_expiry(existing_expires: datetime | None, now: datetime) -> datetime:
    """Открытый черновик держит первый срок. Новый стартует на 30 минут."""
    expires = _aware(existing_expires) if existing_expires is not None else None
    moment = _aware(now)
    if expires is not None and expires > moment:
        return expires
    return moment + WINDOW


def decide_attempt(
    now: datetime,
    expires_at: datetime,
    last_attempt_at: datetime,
) -> dict[str, Any]:
    """Можно ли снова спросить реквизиты. Окно и кулдаун не сдвигаются сами."""
    moment = _aware(now)
    expires = _aware(expires_at)
    last = _aware(last_attempt_at)
    if expires <= moment:
        return {"ok": False, "reason": "expired", "retry_after_sec": 0}
    wait = last + COOLDOWN - moment
    seconds = wait.total_seconds()
    if seconds > 0:
        return {
            "ok": False,
            "reason": "cooldown",
            "retry_after_sec": max(1, int(seconds + 0.999)),
        }
    return {
        "ok": True,
        "reason": "ready",
        "retry_after_sec": int(COOLDOWN.total_seconds()),
    }


def client_message(reason: str, retry_after_sec: int = 0) -> str:
    if reason == "expired":
        return "Время запроса вышло. Начните обмен заново."
    if reason == "cooldown":
        minutes = max(1, (int(retry_after_sec) + 59) // 60)
        return f"Повторить запрос можно через {minutes} мин."
    if reason == "empty":
        return _EMPTY
    return _SAVED


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value).isoformat()


def _sub_token(value: str | None) -> str:
    token = str(value or "SBPRUB").upper()
    if token not in ("SBPRUB", "CARDRUB"):
        return "SBPRUB"
    return token


def _unavailable() -> dict[str, Any]:
    return {"saved": False, "ok": False, "requisite_retry": False, "reason": "ineligible"}


async def _eligible(conn, user_id: int) -> bool:
    row = await conn.fetchrow(
        "SELECT is_banned, ban_type FROM bot_users WHERE user_id = $1",
        int(user_id),
    )
    if row and row["is_banned"]:
        return False
    return await buy_paid_count(conn, user_id) >= MIN_PAID_BUYS


def _client_view(row, *, reason: str, retry_after_sec: int | None = None) -> dict[str, Any]:
    if retry_after_sec is None:
        decision = decide_attempt(
            datetime.now(timezone.utc),
            row["expires_at"],
            row["last_attempt_at"],
        )
        retry_after_sec = int(decision["retry_after_sec"])
        if reason == "saved":
            retry_after_sec = int(COOLDOWN.total_seconds())
    return {
        "requisite_retry": True,
        "saved": reason in ("saved", "empty", "cooldown", "ready"),
        "ok": reason == "ready",
        "reason": reason,
        "expires_at": _iso(row["expires_at"]),
        "retry_after_sec": int(retry_after_sec),
        "attempt_count": int(row["attempt_count"] or 1),
        "fiat_amount": float(row["fiat_amount"] or 0),
        "crypto": str(row["crypto"] or ""),
        "sub_token": str(row["sub_token"] or ""),
        "message": client_message(reason, int(retry_after_sec)),
    }


def _draft_view(row, *, reason: str) -> dict[str, Any]:
    view = _client_view(row, reason=reason, retry_after_sec=int(COOLDOWN.total_seconds()))
    view.update(
        {
            "ok": True,
            "user_id": int(row["user_id"]),
            "network": row["network"],
            "wallet": str(row["wallet"] or ""),
            "rate": float(row["rate"] or 0),
            "crypto_amount": float(row["crypto_amount"] or 0),
            "amount_currency": row["amount_currency"],
            "order_source": row["order_source"] or "site",
        }
    )
    return view


def operator_retry_out(row) -> dict[str, Any]:
    expires = _aware(row["expires_at"])
    left = max(0, int((expires - datetime.now(timezone.utc)).total_seconds()))
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "buyer_username": row["buyer_username"],
        "buyer_first_name": row["buyer_first_name"],
        "fiat_amount": float(row["fiat_amount"] or 0),
        "crypto": str(row["crypto"] or ""),
        "sub_token": str(row["sub_token"] or ""),
        "attempt_count": int(row["attempt_count"] or 1),
        "expires_at": expires.isoformat(),
        "seconds_left": left,
    }


async def list_open_retries(conn) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT r.id, r.user_id, r.fiat_amount, r.crypto, r.sub_token,
               r.expires_at, r.attempt_count,
               bu.username AS buyer_username, bu.first_name AS buyer_first_name
        FROM requisite_retry_requests r
        LEFT JOIN bot_users bu ON bu.user_id = r.user_id
        WHERE r.status = 'open' AND r.expires_at > now()
        ORDER BY r.created_at ASC
        """
    )
    return [operator_retry_out(row) for row in rows]


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    wallet = str(payload.get("wallet") or "").strip()
    crypto = str(payload.get("crypto") or "").strip()
    if len(wallet) < 10 or not crypto:
        return None
    try:
        fiat = float(payload.get("fiat_amount") or 0)
        rate = float(payload.get("rate") or 0)
        crypto_amount = float(payload.get("crypto_amount") or 0)
    except (TypeError, ValueError):
        return None
    if fiat <= 0:
        return None
    network = payload.get("network")
    network_text = str(network).strip() if network else None
    amount_currency = payload.get("amount_currency")
    return {
        "user_id": int(payload["user_id"]),
        "fiat_amount": fiat,
        "crypto": crypto[:32],
        "network": network_text[:32] if network_text else None,
        "wallet": wallet[:200],
        "sub_token": _sub_token(payload.get("sub_token")),
        "rate": rate,
        "crypto_amount": crypto_amount,
        "amount_currency": str(amount_currency).strip().lower()[:16] if amount_currency else None,
        "order_source": str(payload.get("order_source") or "site")[:32],
    }


async def _upsert(conn, payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    clean = _clean_payload(payload)
    if clean is None:
        return {"saved": False, "ok": False, "requisite_retry": False, "reason": "invalid"}
    user_id = clean["user_id"]
    if not await _eligible(conn, user_id):
        return _unavailable()
    moment = _aware(now or datetime.now(timezone.utc))
    existing = await conn.fetchrow(
        """
        SELECT * FROM requisite_retry_requests
        WHERE user_id = $1 AND status = 'open'
        FOR UPDATE
        """,
        user_id,
    )
    expires = kept_expiry(existing["expires_at"] if existing else None, moment)
    if existing and _aware(existing["expires_at"]) > moment:
        row = await conn.fetchrow(
            """
            UPDATE requisite_retry_requests
            SET fiat_amount = $2,
                crypto = $3,
                network = $4,
                wallet = $5,
                sub_token = $6,
                rate = $7,
                crypto_amount = $8,
                amount_currency = $9,
                order_source = $10,
                last_attempt_at = $11,
                attempt_count = attempt_count + 1
            WHERE id = $1
            RETURNING *
            """,
            existing["id"],
            clean["fiat_amount"],
            clean["crypto"],
            clean["network"],
            clean["wallet"],
            clean["sub_token"],
            clean["rate"],
            clean["crypto_amount"],
            clean["amount_currency"],
            clean["order_source"],
            moment,
        )
        return _client_view(row, reason="saved")
    if existing:
        await conn.execute(
            """
            UPDATE requisite_retry_requests
            SET status = 'closed', closed_at = $2
            WHERE id = $1 AND status = 'open'
            """,
            existing["id"],
            moment,
        )
    row = await conn.fetchrow(
        """
        INSERT INTO requisite_retry_requests (
            user_id, fiat_amount, crypto, network, wallet, sub_token,
            rate, crypto_amount, amount_currency, order_source,
            status, created_at, expires_at, last_attempt_at, attempt_count
        )
        VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10,
            'open', $11, $12, $11, 1
        )
        RETURNING *
        """,
        user_id,
        clean["fiat_amount"],
        clean["crypto"],
        clean["network"],
        clean["wallet"],
        clean["sub_token"],
        clean["rate"],
        clean["crypto_amount"],
        clean["amount_currency"],
        clean["order_source"],
        moment,
        expires,
    )
    return _client_view(row, reason="saved")


async def open_requisite_retry(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await _upsert(conn, payload)
    except asyncpg.UndefinedTableError:
        logger.warning("requisite_retry_requests is missing")
        return _unavailable()


async def _claim(conn, user_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    moment = _aware(now or datetime.now(timezone.utc))
    existing = await conn.fetchrow(
        """
        SELECT * FROM requisite_retry_requests
        WHERE user_id = $1 AND status = 'open'
        FOR UPDATE
        """,
        int(user_id),
    )
    if not existing:
        return {
            "ok": False,
            "saved": False,
            "requisite_retry": True,
            "reason": "expired",
            "retry_after_sec": 0,
            "message": client_message("expired"),
        }
    decision = decide_attempt(moment, existing["expires_at"], existing["last_attempt_at"])
    if not decision["ok"]:
        if decision["reason"] == "expired":
            await conn.execute(
                """
                UPDATE requisite_retry_requests
                SET status = 'closed', closed_at = $2
                WHERE id = $1 AND status = 'open'
                """,
                existing["id"],
                moment,
            )
        view = _client_view(
            existing,
            reason=decision["reason"],
            retry_after_sec=int(decision["retry_after_sec"]),
        )
        view["ok"] = False
        return view
    row = await conn.fetchrow(
        """
        UPDATE requisite_retry_requests
        SET last_attempt_at = $2, attempt_count = attempt_count + 1
        WHERE id = $1
        RETURNING *
        """,
        existing["id"],
        moment,
    )
    return _draft_view(row, reason="ready")


async def claim_requisite_attempt(user_id: int) -> dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await _claim(conn, user_id)
    except asyncpg.UndefinedTableError:
        logger.warning("requisite_retry_requests is missing")
        return {
            "ok": False,
            "saved": False,
            "requisite_retry": True,
            "reason": "expired",
            "retry_after_sec": 0,
            "message": client_message("expired"),
        }


async def close_requisite_retry(user_id: int, order_id: str) -> None:
    """Закрыть черновик и пометить созданную заявку."""
    if not order_id:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE orders
                SET payment_snapshot = COALESCE(payment_snapshot, '{}'::jsonb)
                    || '{"requisite_retry": true}'::jsonb
                WHERE order_id = $1
                """,
                str(order_id),
            )
            await conn.execute(
                """
                UPDATE requisite_retry_requests
                SET status = 'closed', closed_at = now(), order_id = $2
                WHERE user_id = $1 AND status = 'open'
                """,
                int(user_id),
                str(order_id),
            )


async def _client_state(conn, user_id: int, reason: str) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT * FROM requisite_retry_requests
        WHERE user_id = $1 AND status = 'open' AND expires_at > now()
        """,
        int(user_id),
    )
    if not row:
        return {
            "ok": False,
            "saved": False,
            "requisite_retry": True,
            "reason": "expired",
            "retry_after_sec": 0,
            "message": client_message("expired"),
        }
    view = _client_view(row, reason=reason, retry_after_sec=int(COOLDOWN.total_seconds()))
    view["ok"] = False
    return view


def _order_id_of(result: dict[str, Any]) -> str:
    if result.get("order_id"):
        return str(result["order_id"])
    row = result.get("row") or {}
    return str(row.get("order_id") or "")


async def fulfill_open_retry(
    *,
    user_id: int,
    client_ip: str | None,
    order_source: str,
) -> dict[str, Any]:
    """Повтор с сайта: кулдаун, поиск реквизитов, обычная заявка или тот же черновик."""
    from fastapi import HTTPException
    from runtime_settings import MAINTENANCE_MESSAGE, maintenance_mode

    if maintenance_mode():
        raise HTTPException(status_code=503, detail=MAINTENANCE_MESSAGE)

    from order_service import _unpaid_cooldown_remaining_sec, _unpaid_cooldown_detail

    unpaid_wait = await _unpaid_cooldown_remaining_sec(int(user_id))
    if unpaid_wait > 0:
        pool = await get_pool()
        async with pool.acquire() as conn:
            view = await _client_state(conn, int(user_id), "cooldown")
        view["retry_after_sec"] = unpaid_wait
        view["message"] = _unpaid_cooldown_detail(unpaid_wait)
        return view

    claimed = await claim_requisite_attempt(user_id)
    if not claimed.get("ok"):
        return claimed
    from buy_order_web import create_buy_web

    result = await create_buy_web(
        user_id=int(user_id),
        crypto_sym=str(claimed["crypto"]),
        crypto_amount=float(claimed.get("crypto_amount") or 0),
        fiat_amount=max(1, int(round(float(claimed["fiat_amount"])))),
        rate=float(claimed.get("rate") or 0),
        requisites=str(claimed["wallet"]),
        sub_token=str(claimed["sub_token"]),
        plan_mode=None,
        client_ip=client_ip,
        order_source=str(claimed.get("order_source") or order_source or "site"),
        requisite_retry=True,
    )
    if result.get("requisite_retry_empty"):
        message = str(result.get("message") or "")
        pool = await get_pool()
        async with pool.acquire() as conn:
            view = await _client_state(conn, user_id, "empty")
        if message:
            view["message"] = message
        return view
    order_id = _order_id_of(result)
    if order_id:
        await close_requisite_retry(user_id, order_id)
        from order_service import get_order_for_user, notify_created_buy

        row = result.get("row")
        if row:
            await notify_created_buy(dict(row))
        presented = await get_order_for_user(order_id, int(user_id), client_ip)
        if presented:
            return presented
        return {"order_id": order_id, "status": str((result.get("row") or {}).get("status") or "CREATED")}
    return result
