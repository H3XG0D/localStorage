"""Сводка клиента магазина (HMAC POST) — те же поля, что карточка /stat|/check."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

_STATUS_AS_ORDER = {
    "confirmed": "PAID",
    "pending": "AWAITING_CHECK",
    "awaiting_receipt": "PENDING",
    "cancelled": "CANCELED",
    "canceled": "CANCELED",
}


def empty_client_stat() -> dict[str, Any]:
    return {
        "paid_orders": 0,
        "total_orders": 0,
        "buy_paid": 0,
        "buy_failed": 0,
        "conversion_pct": None,
        "turnover_rub": 0.0,
        "first_order_at": None,
        "last_paid_at": None,
    }


def _as_int(value, default: int = 0) -> int:
    if value is None or value is False:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    if value is None or value is False:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def coerce_client_stat_payload(raw: Any) -> dict[str, Any] | None:
    """Разобрать тело магазина. Лишние/персональные ключи отбрасываем."""
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    paid = max(0, _as_int(raw.get("paid_orders")))
    total = max(0, _as_int(raw.get("total_orders")))
    buy_paid = max(0, _as_int(raw.get("buy_paid"), paid))
    buy_failed = max(0, _as_int(raw.get("buy_failed")))
    if total <= 0:
        total = buy_paid + buy_failed
    denom = buy_paid + buy_failed
    conv_raw = raw.get("conversion_pct")
    if conv_raw is None or conv_raw == "":
        conv = round(100.0 * buy_paid / denom, 1) if denom > 0 else None
    else:
        try:
            conv = round(float(conv_raw), 1)
        except (TypeError, ValueError):
            conv = round(100.0 * buy_paid / denom, 1) if denom > 0 else None
    return {
        "paid_orders": paid,
        "total_orders": total,
        "buy_paid": buy_paid,
        "buy_failed": buy_failed,
        "conversion_pct": conv,
        "turnover_rub": round(_as_float(raw.get("turnover_rub")), 2),
        "first_order_at": _as_iso(raw.get("first_order_at")),
        "last_paid_at": _as_iso(raw.get("last_paid_at")),
    }


def payload_from_row(raw: Any) -> dict[str, Any]:
    parsed = coerce_client_stat_payload(raw)
    return parsed if parsed else empty_client_stat()


def fingerprint_alias_seed(exchanger_id: int, fingerprint: str | None, deal_id: int | None = None) -> int:
    raw = str(fingerprint or "").strip()
    if raw:
        digest = hashlib.sha256(f"{int(exchanger_id)}:{raw}".encode("utf-8")).hexdigest()
        n = int(digest[:12], 16)
        return n if n > 0 else 1
    if deal_id:
        return abs(int(deal_id))
    return abs(int(exchanger_id) or 0)


def deal_status_as_order(status: str | None) -> str:
    key = str(status or "").strip().lower()
    return _STATUS_AS_ORDER.get(key, (str(status or "PENDING").upper() or "PENDING"))


def check_public_out(deal: dict[str, Any], stat: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload_from_row(stat if stat is not None else deal.get("client_stat"))
    return {
        "deal_id": int(deal.get("id") or 0),
        "status": deal_status_as_order(str(deal.get("status") or "")),
        "deal_status": str(deal.get("status") or ""),
        "client_pays_rub": float(deal.get("client_pays_rub") or 0),
        "crypto": str(deal.get("crypto") or "usdt").lower(),
        "fingerprint": str(deal.get("customer_fingerprint") or "").strip() or None,
        "client_transaction_id": deal.get("client_transaction_id") or None,
        **payload,
    }


def SCHEMA_SQL() -> tuple[str, ...]:
    return (
        """
        ALTER TABLE external_deals
            ADD COLUMN IF NOT EXISTS client_stat JSONB
        """,
        """
        ALTER TABLE external_deals
            ADD COLUMN IF NOT EXISTS client_stat_at TIMESTAMPTZ
        """,
        """
        CREATE TABLE IF NOT EXISTS external_client_stats (
            exchanger_id INTEGER NOT NULL REFERENCES external_exchangers(id) ON DELETE CASCADE,
            fingerprint  TEXT NOT NULL,
            payload      JSONB NOT NULL,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (exchanger_id, fingerprint)
        )
        """,
    )


async def ensure_client_stat_schema(conn) -> None:
    for sql in SCHEMA_SQL():
        await conn.execute(sql)


async def fetch_fingerprint_stat(conn, exchanger_id: int, fingerprint: str | None) -> dict[str, Any] | None:
    fp = str(fingerprint or "").strip()
    if not fp:
        return None
    row = await conn.fetchrow(
        """
        SELECT payload FROM external_client_stats
        WHERE exchanger_id = $1 AND fingerprint = $2
        """,
        int(exchanger_id),
        fp,
    )
    if not row:
        return None
    return payload_from_row(row["payload"])


async def save_client_stat(
    conn,
    *,
    exchanger_id: int,
    payload: dict[str, Any],
    fingerprint: str | None = None,
    deal_id: int | None = None,
) -> dict[str, Any]:
    await ensure_client_stat_schema(conn)
    stat = coerce_client_stat_payload(payload)
    if stat is None:
        raise ValueError("client_stat required")
    body = json.dumps(stat, ensure_ascii=False, separators=(",", ":"))
    fp = str(fingerprint or "").strip() or None
    if fp:
        await conn.execute(
            """
            INSERT INTO external_client_stats (exchanger_id, fingerprint, payload, updated_at)
            VALUES ($1, $2, $3::jsonb, now())
            ON CONFLICT (exchanger_id, fingerprint)
            DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
            """,
            int(exchanger_id),
            fp,
            body,
        )
    if deal_id:
        await conn.execute(
            """
            UPDATE external_deals
            SET client_stat = $1::jsonb, client_stat_at = now()
            WHERE id = $2 AND exchanger_id = $3
            """,
            body,
            int(deal_id),
            int(exchanger_id),
        )
    return stat


async def apply_stat_on_create(
    conn,
    *,
    exchanger_id: int,
    deal_id: int,
    fingerprint: str | None,
    client_stat: Any = None,
) -> dict[str, Any] | None:
    """Сохранить переданную сводку или подставить кэш по fingerprint."""
    parsed = coerce_client_stat_payload(client_stat)
    fp = str(fingerprint or "").strip() or None
    if parsed is not None:
        return await save_client_stat(
            conn,
            exchanger_id=exchanger_id,
            payload=parsed,
            fingerprint=fp,
            deal_id=deal_id,
        )
    cached = await fetch_fingerprint_stat(conn, exchanger_id, fp)
    if not cached:
        return None
    await conn.execute(
        """
        UPDATE external_deals
        SET client_stat = $1::jsonb, client_stat_at = now()
        WHERE id = $2 AND exchanger_id = $3
        """,
        json.dumps(cached, ensure_ascii=False, separators=(",", ":")),
        int(deal_id),
        int(exchanger_id),
    )
    return cached
