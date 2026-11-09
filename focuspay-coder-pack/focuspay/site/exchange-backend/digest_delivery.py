"""PostgreSQL-backed claims for idempotent digest delivery."""
from __future__ import annotations

import secrets
from datetime import date

from db import get_pool

CLAIM_LEASE_SECONDS = 15 * 60


async def claim_digest_delivery(
    *,
    digest_kind: str,
    recipient_key: str,
    delivery_date: date,
) -> str | None:
    """Claim one delivery without holding a transaction during Telegram HTTP."""
    claim_token = secrets.token_urlsafe(24)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO digest_deliveries (
                digest_kind, recipient_key, delivery_date, status,
                claim_token, claimed_until, updated_at
            )
            VALUES ($1, $2, $3, 'claimed', $4,
                    now() + make_interval(secs => $5), now())
            ON CONFLICT (digest_kind, recipient_key, delivery_date) DO UPDATE
            SET status = 'claimed',
                claim_token = EXCLUDED.claim_token,
                claimed_until = EXCLUDED.claimed_until,
                updated_at = now()
            WHERE digest_deliveries.status <> 'sent'
              AND (
                  digest_deliveries.status = 'pending'
                  OR digest_deliveries.claimed_until IS NULL
                  OR digest_deliveries.claimed_until <= now()
              )
            RETURNING claim_token
            """,
            digest_kind,
            recipient_key,
            delivery_date,
            claim_token,
            CLAIM_LEASE_SECONDS,
        )
    return str(row["claim_token"]) if row else None


async def complete_digest_delivery(claim_token: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE digest_deliveries
            SET status = 'sent', sent_at = now(), claimed_until = NULL, updated_at = now()
            WHERE claim_token = $1 AND status = 'claimed'
            """,
            claim_token,
        )
    return result == "UPDATE 1"


async def release_digest_delivery(claim_token: str) -> None:
    """Release a failed claim so another scheduler tick can retry it."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE digest_deliveries
            SET status = 'pending', claim_token = NULL,
                claimed_until = NULL, updated_at = now()
            WHERE claim_token = $1 AND status = 'claimed'
            """,
            claim_token,
        )
