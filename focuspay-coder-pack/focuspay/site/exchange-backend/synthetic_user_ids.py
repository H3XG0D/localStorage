"""Единое пространство отрицательных synthetic user_id (guest + password).

Исторически guest и password-регистрация брали -nextval() из РАЗНЫХ sequence
(web_guest_user_id_seq / web_client_user_id_seq) → один и тот же id (например -56)
мог принадлежать и старой guest-сессии с заявкой/кешбэком, и новому аккаунту.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_pool

logger = logging.getLogger("synthetic_user_ids")

# Каноническая sequence после миграции unify_synthetic_user_ids.sql.
SYNTHETIC_SEQ = "web_synthetic_user_id_seq"
# Старые sequence — только fallback, если миграция ещё не накатана.
_LEGACY_SEQS = ("web_guest_user_id_seq", "web_client_user_id_seq")

# Orphan-id для данных, отвязанных от коллизии: -(3_000_000_000 + abs(uid)).
ORPHAN_FLOOR = 3_000_000_000
_MAX_ALLOCATE_ATTEMPTS = 64


def orphan_user_id(collided_uid: int) -> int:
    n = abs(int(collided_uid))
    if n >= ORPHAN_FLOOR:
        raise ValueError(f"uid already in orphan range: {collided_uid}")
    return -(ORPHAN_FLOOR + n)


def is_orphan_user_id(uid: int) -> bool:
    return int(uid) < 0 and abs(int(uid)) >= ORPHAN_FLOOR


async def _sequence_exists(conn, name: str) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = $1",
            name,
        )
    )


async def _next_synthetic_raw(conn) -> int:
    if await _sequence_exists(conn, SYNTHETIC_SEQ):
        return int(await conn.fetchval(f"SELECT -nextval('{SYNTHETIC_SEQ}')::bigint"))
    # Fallback: advance BOTH legacy sequences and take the max abs, so two
    # unpatched callers still cannot land on the same value in one step.
    vals: list[int] = []
    for seq in _LEGACY_SEQS:
        if await _sequence_exists(conn, seq):
            vals.append(int(await conn.fetchval(f"SELECT nextval('{seq}')::bigint")))
    if not vals:
        raise RuntimeError("no synthetic user id sequence available")
    return -max(vals)


async def synthetic_id_is_taken(conn, uid: int) -> bool:
    """True if uid уже занят в любом финансовом/сессионном неймспейсе."""
    uid = int(uid)
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM web_guest_sessions WHERE synthetic_user_id = $1
            ) OR EXISTS (
                SELECT 1 FROM web_users
                WHERE client_user_id = $1 OR telegram_user_id = $1
            ) OR EXISTS (
                SELECT 1 FROM bot_users WHERE user_id = $1
            ) OR EXISTS (
                SELECT 1 FROM orders WHERE user_id = $1
            ) OR EXISTS (
                SELECT 1 FROM user_cashback_ledger WHERE user_id = $1
            ) OR EXISTS (
                SELECT 1 FROM user_referral_ledger WHERE referrer_user_id = $1
            ) OR EXISTS (
                SELECT 1 FROM promo_attributions WHERE user_id = $1
            ) OR EXISTS (
                SELECT 1 FROM user_referral_attributions WHERE user_id = $1
            )
            """,
            uid,
        )
    )


async def allocate_synthetic_user_id(conn=None) -> int:
    """Выдать свободный отрицательный synthetic user_id."""
    own_pool = conn is None
    if own_pool:
        pool = await get_pool()
        conn = await pool.acquire()
    try:
        for _ in range(_MAX_ALLOCATE_ATTEMPTS):
            uid = await _next_synthetic_raw(conn)
            if is_orphan_user_id(uid):
                continue
            if not await synthetic_id_is_taken(conn, uid):
                return uid
            logger.warning("synthetic uid %s already taken, retrying", uid)
        raise RuntimeError("could not allocate free synthetic user_id")
    finally:
        if own_pool:
            await pool.release(conn)


async def allocate_client_user_id() -> int:
    """Password-регистрация: тот же неймспейс, что и guest."""
    return await allocate_synthetic_user_id()


def _as_utc_naive(dt: Any):
    """Сравнение timestamp without time zone (orders) с timestamptz."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(__import__("datetime").timezone.utc).replace(tzinfo=None)
    return dt


async def remediate_client_guest_collisions(
    conn,
    *,
    dry_run: bool = True,
) -> list[dict]:
    """Отвязать guest-сессии и pre-reg финансы от password client_user_id.

    Для каждой коллизии guest.synthetic_user_id == web_users.client_user_id:
      1) guest-сессии → orphan uid
      2) orders / ledger / attributions с created_at < регистрации → orphan
    """
    rows = await conn.fetch(
        """
        SELECT w.id AS web_id,
               w.username,
               w.client_user_id AS uid,
               w.created_at AS reg_at,
               COUNT(g.session_token)::int AS guest_sessions
        FROM web_users w
        JOIN web_guest_sessions g ON g.synthetic_user_id = w.client_user_id
        WHERE w.client_user_id IS NOT NULL
          AND w.client_user_id > $1
        GROUP BY w.id, w.username, w.client_user_id, w.created_at
        ORDER BY w.client_user_id
        """,
        -ORPHAN_FLOOR,
    )

    report: list[dict] = []
    for row in rows:
        uid = int(row["uid"])
        orphan = orphan_user_id(uid)
        reg_at = row["reg_at"]
        reg_naive = _as_utc_naive(reg_at)

        pre_orders = await conn.fetch(
            """
            SELECT order_id, created_at, status
            FROM orders
            WHERE user_id = $1 AND created_at < $2::timestamp
            ORDER BY created_at
            """,
            uid,
            reg_naive,
        )
        pre_cashback = await conn.fetch(
            """
            SELECT id, amount_rub, type, created_at
            FROM user_cashback_ledger
            WHERE user_id = $1 AND created_at < $2
            ORDER BY created_at
            """,
            uid,
            reg_at,
        )
        pre_ref = await conn.fetch(
            """
            SELECT id, amount_rub, type, created_at
            FROM user_referral_ledger
            WHERE referrer_user_id = $1 AND created_at < $2
            ORDER BY created_at
            """,
            uid,
            reg_at,
        )
        bal_before = round(
            sum(float(r["amount_rub"]) for r in pre_cashback)
            + sum(float(r["amount_rub"]) for r in pre_ref),
            2,
        )
        entry = {
            "web_id": int(row["web_id"]),
            "username": row["username"],
            "uid": uid,
            "orphan": orphan,
            "guest_sessions": int(row["guest_sessions"]),
            "orders_moved": len(pre_orders),
            "cashback_rows_moved": len(pre_cashback),
            "referral_rows_moved": len(pre_ref),
            "balance_moved_rub": bal_before,
            "dry_run": dry_run,
        }
        report.append(entry)
        if dry_run:
            continue

        if await synthetic_id_is_taken(conn, orphan):
            # Уже чинили ранее — всё равно двигаем guest/финансы на тот же orphan.
            logger.info("orphan %s already present, reusing for uid %s", orphan, uid)

        await conn.execute(
            """
            UPDATE web_guest_sessions
            SET synthetic_user_id = $2
            WHERE synthetic_user_id = $1
            """,
            uid,
            orphan,
        )
        if pre_orders:
            await conn.execute(
                """
                UPDATE orders
                SET user_id = $2, updated_at = now()
                WHERE user_id = $1 AND created_at < $3::timestamp
                """,
                uid,
                orphan,
                reg_naive,
            )
        if pre_cashback:
            await conn.execute(
                """
                UPDATE user_cashback_ledger
                SET user_id = $2
                WHERE user_id = $1 AND created_at < $3
                """,
                uid,
                orphan,
                reg_at,
            )
        if pre_ref:
            await conn.execute(
                """
                UPDATE user_referral_ledger
                SET referrer_user_id = $2
                WHERE referrer_user_id = $1 AND created_at < $3
                """,
                uid,
                orphan,
                reg_at,
            )
        await conn.execute(
            """
            UPDATE promo_attributions
            SET user_id = $2
            WHERE user_id = $1
              AND assigned_at < $3
              AND NOT EXISTS (
                  SELECT 1 FROM promo_attributions x WHERE x.user_id = $2
              )
            """,
            uid,
            orphan,
            reg_at,
        )
        await conn.execute(
            """
            UPDATE user_referral_attributions
            SET user_id = $2
            WHERE user_id = $1
              AND created_at < $3
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_attributions x WHERE x.user_id = $2
              )
            """,
            uid,
            orphan,
            reg_at,
        )
        await conn.execute(
            """
            UPDATE web_attribution_pending
            SET guest_user_id = $2
            WHERE guest_user_id = $1
            """,
            uid,
            orphan,
        )
        await conn.execute(
            """
            INSERT INTO bot_users (user_id, username, first_name, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, now(), now())
            ON CONFLICT (user_id) DO NOTHING
            """,
            orphan,
            f"orphan_{abs(uid)}",
            "orphan-collision",
        )
        logger.warning(
            "remediated synthetic collision uid=%s orphan=%s user=%s bal_moved=%s orders=%s",
            uid,
            orphan,
            row["username"],
            bal_before,
            len(pre_orders),
        )

    return report
