#!/usr/bin/env python3
"""Импорт старых отзывов из site_reviews в review_submissions."""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

import asyncpg

LEGACY_SOURCE_CHAT = 0
LEGACY_SOURCE_MESSAGE = 0


def _parse_username(author_name: str | None) -> str | None:
    if not author_name:
        return None
    name = author_name.strip()
    if name.startswith("@"):
        return name[1:].strip() or None
    m = re.match(r"^@?([A-Za-z0-9_]{3,32})$", name)
    return m.group(1) if m else None


async def backfill(*, dsn: str, dry_run: bool) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT id, telegram_message_id, channel_username, text, author_name, published_at
            FROM site_reviews
            WHERE submission_id IS NULL
            ORDER BY published_at ASC NULLS LAST, id ASC
            """
        )
        created = 0
        for row in rows:
            sr = dict(row)
            username = _parse_username(sr.get("author_name"))
            user_id = None
            if username:
                user_id = await conn.fetchval(
                    "SELECT user_id FROM bot_users WHERE LOWER(username) = LOWER($1) LIMIT 1",
                    username,
                )

            if user_id is None:
                user_id = 0

            author_display = sr.get("author_name") or (
                f"@{username}" if username else "legacy"
            )

            claim = await conn.fetchrow(
                """
                SELECT amount_rub FROM review_bonus_claims
                WHERE channel_message_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                int(sr["telegram_message_id"]),
            )
            bonus_rub = float(claim["amount_rub"]) if claim else None
            bonus_credited = claim is not None

            if dry_run:
                print(
                    f"DRY site_review#{sr['id']} -> user_id={user_id} "
                    f"author={author_display!r} bonus={bonus_rub}"
                )
                created += 1
                continue

            sub_id = await conn.fetchval(
                """
                INSERT INTO review_submissions (
                    user_id, order_id, tier, status, review_text, author_display,
                    source_text_chat_id, source_text_message_id,
                    channel_text_message_id, bonus_rub, bonus_credited,
                    moderated_at, created_at
                )
                VALUES (
                    $1, NULL, 'text', 'published', $2, $3,
                    $4, $5,
                    $6, $7, $8,
                    $9, COALESCE($9, now())
                )
                RETURNING id
                """,
                int(user_id),
                sr["text"],
                author_display,
                LEGACY_SOURCE_CHAT,
                LEGACY_SOURCE_MESSAGE,
                int(sr["telegram_message_id"]),
                bonus_rub,
                bonus_credited,
                sr.get("published_at"),
            )
            await conn.execute(
                "UPDATE site_reviews SET submission_id = $2 WHERE id = $1",
                sr["id"],
                sub_id,
            )
            created += 1
            print(f"linked site_review#{sr['id']} -> submission#{sub_id}")

        return created
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill site_reviews into review_submissions")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_DSN", ""))
    args = parser.parse_args()
    if not args.dsn:
        print("DATABASE_DSN required", file=sys.stderr)
        return 1
    n = asyncio.run(backfill(dsn=args.dsn, dry_run=args.dry_run))
    print(f"done: {n} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
