#!/usr/bin/env python3
"""Привязать старые файлы чеков к заявкам по времени загрузки (mtime ≈ updated_at).

До внедрения receipt_file имена файлов не сохранялись в БД. Скрипт сопоставляет
файлы из каталога receipts с BUY-заявками, у которых чек уже был отправлен
(PENDING+), по ближайшему времени модификации файла к updated_at заявки.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", str(BOT_ROOT / "receipts")))
DEFAULT_THRESHOLD_SEC = 600

_RECEIPT_STATUSES = ("PENDING", "COMPLETED", "PAID", "DISPUTE", "FAILED")


def _ts(value) -> float | None:
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        dt = value
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return None


def _load_receipt_files(exclude: set[str]) -> list[tuple[str, float]]:
    if not RECEIPTS_DIR.is_dir():
        return []
    out: list[tuple[str, float]] = []
    for path in RECEIPTS_DIR.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name in exclude:
            continue
        try:
            out.append((path.name, path.stat().st_mtime))
        except OSError as e:
            print(f"warn: skip {path.name}: {e}")
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать сопоставления, без UPDATE",
    )
    parser.add_argument(
        "--threshold-sec",
        type=int,
        default=DEFAULT_THRESHOLD_SEC,
        help=f"Макс. разница mtime файла и updated_at заявки (по умолчанию {DEFAULT_THRESHOLD_SEC})",
    )
    parser.add_argument(
        "--order-id",
        help="Обработать только одну заявку (например 31897124)",
    )
    args = parser.parse_args()

    from services import config_rates as cfg
    from services.db import get_pool, init_db

    await init_db(cfg.DATABASE_DSN)
    pool = await get_pool()

    async with pool.acquire() as conn:
        already = {
            str(r["receipt_file"])
            for r in await conn.fetch(
                "SELECT receipt_file FROM orders WHERE receipt_file IS NOT NULL"
            )
        }

    files = _load_receipt_files(already)
    if not files:
        print(f"Нет свободных файлов в {RECEIPTS_DIR}")
        return 0

    sql = """
        SELECT order_id, updated_at, created_at, status
        FROM orders
        WHERE direction = 'buy'
          AND receipt_file IS NULL
          AND status = ANY($1::text[])
    """
    params: list = [list(_RECEIPT_STATUSES)]
    if args.order_id:
        sql += " AND order_id = $2"
        params.append(args.order_id.strip().upper())

    sql += " ORDER BY COALESCE(updated_at, created_at) ASC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    if not rows:
        print("Нет заявок для бэкофилла")
        return 0

    used_files: set[str] = set()
    matched = 0
    skipped = 0

    for row in rows:
        order_id = str(row["order_id"])
        order_ts = _ts(row["updated_at"]) or _ts(row["created_at"])
        if order_ts is None:
            skipped += 1
            print(f"skip {order_id}: нет updated_at/created_at")
            continue

        best_name: str | None = None
        best_delta = float(args.threshold_sec) + 1.0
        for name, mtime in files:
            if name in used_files:
                continue
            delta = abs(mtime - order_ts)
            if delta < best_delta:
                best_delta = delta
                best_name = name

        if not best_name or best_delta > args.threshold_sec:
            skipped += 1
            print(
                f"skip {order_id} ({row['status']}): "
                f"нет файла в пределах {args.threshold_sec}s"
            )
            continue

        used_files.add(best_name)
        matched += 1
        when = datetime.fromtimestamp(order_ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        print(
            f"{'would link' if args.dry_run else 'linked'} "
            f"{order_id} -> {best_name} (Δ{int(best_delta)}s, order {when})"
        )
        if not args.dry_run:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE orders SET receipt_file = $1 WHERE order_id = $2",
                    best_name,
                    order_id,
                )

    mode = "dry-run" if args.dry_run else "applied"
    print(
        f"Done ({mode}). Matched: {matched}, skipped: {skipped}, "
        f"files available: {len(files)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
