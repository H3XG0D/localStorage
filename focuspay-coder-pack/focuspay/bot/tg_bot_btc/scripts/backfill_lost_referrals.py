#!/usr/bin/env python3
"""Восстановление рефералов, потерянных из-за капчи (с 2026-07-03).

Команды:
  stats       — сводка по «потерянным» пользователям
  unlock      — снять referral_locked (чтобы сработала повторная ссылка)
  apply       — применить pending_ref_token из bot_users
  assign      — ручная привязка user_id к ref_token реферера
  recover     — unlock + apply + отчёт (без ручных assign)
  replay-log  — привязать по bot_start_ref_log (после деплоя с логированием)
  commissions — догон начислений по PAID сделкам уже привязанных рефералов
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

CAPTCHA_BUG_SINCE = "2026-07-03"


def _parse_since(value: str) -> datetime:
    raw = (value or CAPTCHA_BUG_SINCE).strip()
    if "T" in raw or " " in raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)


async def _pool():
    from services import config_rates as cfg
    from services.db import get_pool, init_db

    await init_db(cfg.DATABASE_DSN)
    return await get_pool()


async def cmd_stats(since: str) -> int:
    since_dt = _parse_since(since)
    pool = await _pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              (SELECT COUNT(*)::int FROM bot_users
               WHERE first_seen_at >= $1::timestamptz) AS new_users,
              (SELECT COUNT(*)::int FROM bot_users bu
               WHERE bu.first_seen_at >= $1::timestamptz
                 AND bu.captcha_passed_at IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM user_referral_attributions a WHERE a.user_id = bu.user_id
                 )) AS captcha_no_attr,
              (SELECT COUNT(*)::int FROM bot_users bu
               WHERE bu.first_seen_at >= $1::timestamptz
                 AND bu.referral_locked = TRUE
                 AND NOT EXISTS (
                     SELECT 1 FROM user_referral_attributions a WHERE a.user_id = bu.user_id
                 )) AS locked_no_attr,
              (SELECT COUNT(*)::int FROM bot_users
               WHERE pending_ref_token IS NOT NULL) AS pending_tokens,
              (SELECT COUNT(*)::int FROM user_referral_attributions
               WHERE created_at >= $1::timestamptz) AS attributions_since
            """,
            since_dt,
        )
    r = rows[0]
    print(f"С {since_dt.isoformat()}:")
    print(f"  новых в боте:              {r['new_users']}")
    print(f"  прошли капчу без реферала: {r['captcha_no_attr']}")
    print(f"  referral_locked без реф.:  {r['locked_no_attr']}")
    print(f"  pending_ref_token:         {r['pending_tokens']}")
    print(f"  новых атрибуций:           {r['attributions_since']}")
    return 0


async def cmd_unlock(since: str, dry_run: bool) -> int:
    since_dt = _parse_since(since)
    pool = await _pool()
    async with pool.acquire() as conn:
        candidates = await conn.fetch(
            """
            SELECT bu.user_id, bu.username, bu.first_seen_at, bu.captcha_passed_at
            FROM bot_users bu
            WHERE bu.first_seen_at >= $1::timestamptz
              AND bu.referral_locked = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_attributions a WHERE a.user_id = bu.user_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM promo_attributions p WHERE p.user_id = bu.user_id
              )
            ORDER BY bu.first_seen_at ASC
            """,
            since_dt,
        )
        if dry_run:
            for row in candidates:
                print(
                    f"would unlock user={row['user_id']} @{row['username'] or '-'} "
                    f"seen={row['first_seen_at']}"
                )
            print(f"Done (dry-run). Would unlock: {len(candidates)}")
            return 0

        result = await conn.execute(
            """
            UPDATE bot_users bu
            SET referral_locked = FALSE
            WHERE bu.first_seen_at >= $1::timestamptz
              AND bu.referral_locked = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_attributions a WHERE a.user_id = bu.user_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM promo_attributions p WHERE p.user_id = bu.user_id
              )
            """,
            since_dt,
        )
    print(f"Done (applied). {result}")
    return 0


async def cmd_apply(dry_run: bool) -> int:
    from services.user_referral_attribution import apply_pending_ref_token_if_any

    pool = await _pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, username, pending_ref_token
            FROM bot_users
            WHERE pending_ref_token IS NOT NULL
            ORDER BY user_id
            """
        )

    applied = 0
    for row in rows:
        uid = int(row["user_id"])
        token = row["pending_ref_token"]
        if dry_run:
            print(f"would apply user={uid} @{row['username'] or '-'} token={token}")
            applied += 1
            continue
        result = await apply_pending_ref_token_if_any(uid)
        if result == "applied":
            print(f"applied user={uid} token={token}")
            applied += 1
        else:
            print(f"skip user={uid} token={token} result={result}")

    mode = "dry-run" if dry_run else "applied"
    print(f"Done ({mode}). processed={len(rows)} applied={applied}")
    return 0


async def cmd_assign(
    user_id: int,
    ref_token: str,
    dry_run: bool,
    *,
    since: str | None = None,
    until: str | None = None,
) -> int:
    from services.user_referral_attribution import assign_referrer_by_token

    pool = await _pool()
    targets: list[int] = [user_id] if user_id else []

    if not user_id and since:
        since_dt = _parse_since(since)
        until_dt = _parse_since(until) if until else None
        async with pool.acquire() as conn:
            q = """
                SELECT bu.user_id
                FROM bot_users bu
                WHERE bu.first_seen_at >= $1::timestamptz
                  AND NOT EXISTS (
                      SELECT 1 FROM user_referral_attributions a WHERE a.user_id = bu.user_id
                  )
            """
            params: list = [since_dt]
            if until_dt:
                q += " AND bu.first_seen_at < $2::timestamptz"
                params.append(until_dt)
            q += " ORDER BY bu.first_seen_at ASC"
            rows = await conn.fetch(q, *params)
            targets = [int(r["user_id"]) for r in rows]

    if not targets:
        print("Нет пользователей для привязки")
        return 1

    applied = 0
    for uid in targets:
        if dry_run:
            print(f"would assign user={uid} -> token={ref_token}")
            applied += 1
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE bot_users SET referral_locked = FALSE WHERE user_id = $1",
                uid,
            )
        result = await assign_referrer_by_token(uid, ref_token)
        if result == "applied":
            print(f"assigned user={uid} token={ref_token}")
            applied += 1
        else:
            print(f"skip user={uid} token={ref_token} result={result}")

    mode = "dry-run" if dry_run else "applied"
    print(f"Done ({mode}). targets={len(targets)} applied={applied}")
    return 0


async def cmd_commissions(dry_run: bool) -> int:
    from services.user_referral_commission import accrue_user_referral_commission

    pool = await _pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT o.order_id, o.user_id, a.referrer_user_id
            FROM orders o
            JOIN user_referral_attributions a ON a.user_id = o.user_id
            WHERE o.status IN ('PAID', 'COMPLETED')
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_ledger l WHERE l.order_id = o.order_id
              )
            ORDER BY o.updated_at ASC
            """
        )

    done = 0
    for row in rows:
        oid = row["order_id"]
        if dry_run:
            print(
                f"would accrue order={oid} user={row['user_id']} "
                f"referrer={row['referrer_user_id']}"
            )
            done += 1
            continue
        ok = await accrue_user_referral_commission(oid)
        if ok:
            print(f"accrued order={oid} referrer={row['referrer_user_id']}")
            done += 1
        else:
            print(f"skip order={oid}")

    mode = "dry-run" if dry_run else "applied"
    print(f"Done ({mode}). processed={len(rows)} accrued={done}")
    return 0


async def cmd_partner_commissions(dry_run: bool) -> int:
    """Догон партнёрских начислений по PAID-сделкам без записи в partner_ledger."""
    from services.partner_commission import accrue_partner_commission

    pool = await _pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT o.order_id
            FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id
            JOIN promo_campaigns pc ON pc.code = pa.promo_code AND pc.campaign_kind = 'partner'
            WHERE o.status IN ('PAID', 'COMPLETED')
              AND NOT EXISTS (
                  SELECT 1 FROM partner_ledger pl WHERE pl.order_id = o.order_id
              )
            ORDER BY o.order_id
            """
        )

    done = 0
    for row in rows:
        oid = row["order_id"]
        if dry_run:
            print(f"would accrue partner order={oid}")
            done += 1
            continue
        ok = await accrue_partner_commission(oid)
        if ok:
            print(f"accrued partner order={oid}")
            done += 1
        else:
            print(f"skip order={oid}")

    mode = "dry-run" if dry_run else "applied"
    print(f"Done ({mode}). processed={len(rows)} accrued={done}")
    return 0


async def cmd_replay_log(dry_run: bool) -> int:
    from services.referral_links import extract_any_ref_token
    from services.user_referral_attribution import assign_referrer_by_token

    pool = await _pool()
    async with pool.acquire() as conn:
        # Все строки лога без атрибуции — берём лучший токен по пользователю
        # (последний старт часто ответ капчи без ref_, не исходный deep-link).
        rows = await conn.fetch(
            """
            SELECT l.user_id, l.ref_token, l.payload, bu.username, l.created_at
            FROM bot_start_ref_log l
            JOIN bot_users bu ON bu.user_id = l.user_id
            WHERE (l.ref_token IS NOT NULL OR l.payload IS NOT NULL)
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_attributions a WHERE a.user_id = l.user_id
              )
            ORDER BY l.user_id, l.created_at ASC
            """
        )
        known_tokens = {
            str(r["ref_token"]).lower()
            for r in await conn.fetch(
                "SELECT ref_token FROM bot_users WHERE ref_token IS NOT NULL"
            )
        }
        # Партнёрские токены из promo_campaigns тоже валидны для привязки
        # через bot_users, если совпадают; иначе — только user-токены.
        promo_tokens = {
            str(r["ref_token"]).lower()
            for r in await conn.fetch(
                """
                SELECT ref_token FROM promo_campaigns
                WHERE ref_token IS NOT NULL AND COALESCE(is_active, TRUE)
                """
            )
        }

    best: dict[int, tuple[str, str | None]] = {}
    for row in rows:
        uid = int(row["user_id"])
        token = row["ref_token"]
        if not token:
            token = extract_any_ref_token(row["payload"] or "")
        if not token:
            continue
        token = str(token).lower()
        # Только реальные токены рефереров — отсекаем ответы капчи/мусор.
        if token not in known_tokens and token not in promo_tokens:
            continue
        if uid not in best:
            best[uid] = (token, row["username"])

    applied = 0
    skipped = 0
    for uid, (token, username) in sorted(best.items()):
        if dry_run:
            print(f"would assign user={uid} @{username or '-'} token={token}")
            applied += 1
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE bot_users SET referral_locked = FALSE WHERE user_id = $1",
                uid,
            )
        result = await assign_referrer_by_token(uid, token)
        if result == "applied":
            print(f"assigned user={uid} token={token}")
            applied += 1
        else:
            # Партнёрский promo-токен без совпадения в bot_users
            if result == "invalid" and token in promo_tokens:
                from services.promo_attribution import apply_promo_from_start_payload

                ok = await apply_promo_from_start_payload(uid, f"ref_{token}")
                if ok:
                    print(f"assigned promo user={uid} token={token}")
                    applied += 1
                    continue
            print(f"skip user={uid} token={token} result={result}")
            skipped += 1

    mode = "dry-run" if dry_run else "applied"
    print(
        f"Done ({mode}). candidates={len(best)} applied={applied} skipped={skipped}"
    )
    return 0


async def cmd_recover(since: str, dry_run: bool) -> int:
    await cmd_stats(since)
    print()
    await cmd_unlock(since, dry_run)
    print()
    await cmd_apply(dry_run)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default=CAPTCHA_BUG_SINCE,
        help=f"Начало периода бага (default: {CAPTCHA_BUG_SINCE})",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="Конец окна для массовой assign (ISO datetime)",
    )
    parser.add_argument("--dry-run", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="Сводка")
    sub.add_parser("unlock", help="Снять referral_locked")
    sub.add_parser("apply", help="Применить pending_ref_token")
    sub.add_parser("recover", help="unlock + apply")
    sub.add_parser("replay-log", help="Привязка из bot_start_ref_log")
    sub.add_parser("commissions", help="Догон реф. начислений по PAID")
    sub.add_parser("partner-commissions", help="Догон партнёрских начислений по PAID")

    p_assign = sub.add_parser("assign", help="Ручная или пакетная привязка")
    p_assign.add_argument("--user-id", type=int, default=0)
    p_assign.add_argument("--ref-token", required=True)
    p_assign.add_argument("--window", action="store_true", help="Все новые в --since..--until")

    args = parser.parse_args()

    if args.cmd == "assign" and args.window and not args.until:
        print("Для --window укажите --until", file=sys.stderr)
        return 2

    async def run() -> int:
        if args.cmd == "stats":
            return await cmd_stats(args.since)
        if args.cmd == "unlock":
            return await cmd_unlock(args.since, args.dry_run)
        if args.cmd == "apply":
            return await cmd_apply(args.dry_run)
        if args.cmd == "recover":
            return await cmd_recover(args.since, args.dry_run)
        if args.cmd == "replay-log":
            return await cmd_replay_log(args.dry_run)
        if args.cmd == "commissions":
            return await cmd_commissions(args.dry_run)
        if args.cmd == "partner-commissions":
            return await cmd_partner_commissions(args.dry_run)
        if args.cmd == "assign":
            return await cmd_assign(
                args.user_id,
                args.ref_token.strip().lower(),
                args.dry_run,
                since=args.since if args.window else None,
                until=args.until if args.window else None,
            )
        return 1

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
