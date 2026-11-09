"""Подписки на новости: opt-in / opt-out, категории, версия согласия."""
from __future__ import annotations

import json
import logging
from typing import Iterable

from services.db import get_pool
from services.news_privacy import pseudo_user, security_log

logger = logging.getLogger("news_subscriptions")

CONSENT_VERSION = "news-privacy-v1"
ALLOWED_CATEGORIES = frozenset({"general", "rates", "promo", "security", "product"})


def _norm_categories(cats: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for c in cats or []:
        k = str(c).strip().lower()
        if k in ALLOWED_CATEGORIES and k not in out:
            out.append(k)
    return out or ["general"]


async def get_subscription(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM news_subscriptions WHERE user_id = $1",
            int(user_id),
        )
    return dict(row) if row else None


async def is_subscribed(user_id: int, *, category: str = "general") -> bool:
    row = await get_subscription(user_id)
    if not row or not row.get("opted_in"):
        return False
    cats = row.get("categories") or []
    if isinstance(cats, str):
        try:
            cats = json.loads(cats)
        except Exception:
            cats = []
    cat = (category or "general").strip().lower()
    return cat in {str(c).lower() for c in cats} or (
        cat == "general" and bool(cats)
    )


async def opt_in(
    user_id: int,
    *,
    categories: Iterable[str] | None = None,
    source: str = "bot",
) -> dict:
    cats = _norm_categories(categories)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO news_subscriptions (
                user_id, opted_in, categories, consent_version, consent_source,
                consented_at, opted_out_at, updated_at
            ) VALUES ($1, TRUE, $2::jsonb, $3, $4, now(), NULL, now())
            ON CONFLICT (user_id) DO UPDATE SET
                opted_in = TRUE,
                categories = EXCLUDED.categories,
                consent_version = EXCLUDED.consent_version,
                consent_source = EXCLUDED.consent_source,
                consented_at = now(),
                opted_out_at = NULL,
                updated_at = now()
            RETURNING *
            """,
            int(user_id),
            json.dumps(cats),
            CONSENT_VERSION,
            (source or "bot")[:64],
        )
    security_log.info(
        "news_opt_in user=%s cats=%s source=%s",
        pseudo_user(user_id),
        cats,
        source,
    )
    return dict(row)


async def opt_out(user_id: int, *, source: str = "bot") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO news_subscriptions (
                user_id, opted_in, categories, consent_version, consent_source,
                opted_out_at, updated_at
            ) VALUES ($1, FALSE, '[]'::jsonb, $2, $3, now(), now())
            ON CONFLICT (user_id) DO UPDATE SET
                opted_in = FALSE,
                opted_out_at = now(),
                updated_at = now()
            RETURNING *
            """,
            int(user_id),
            CONSENT_VERSION,
            (source or "bot")[:64],
        )
    security_log.info("news_opt_out user=%s source=%s", pseudo_user(user_id), source)
    return dict(row)


async def list_recipients(category: str, *, limit: int = 50000) -> list[int]:
    cat = (category or "general").strip().lower()
    if cat not in ALLOWED_CATEGORIES:
        cat = "general"
    limit = max(1, min(int(limit), 100_000))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id
            FROM news_subscriptions
            WHERE opted_in = TRUE
              AND (
                categories @> to_jsonb(ARRAY[$1]::text[])
                OR ($1 = 'general' AND jsonb_array_length(categories) > 0)
              )
            ORDER BY user_id
            LIMIT $2
            """,
            cat,
            limit,
        )
    return [int(r["user_id"]) for r in rows]
