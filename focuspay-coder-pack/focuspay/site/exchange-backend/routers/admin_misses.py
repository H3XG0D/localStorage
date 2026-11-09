"""Read-only admin misses: same source as bot owner /dash and /misses."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from auth import get_current_admin
from db import get_pool
from miss_unique import CLIENT_HOUR, MSK, as_utc, dedupe_miss_rows, msk_clock, row_fiat

router = APIRouter()


def _parse_day(raw: Optional[str], fallback: date) -> date:
    if not raw:
        return fallback
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return fallback


@router.get("/misses")
async def get_admin_misses(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _admin=Depends(get_current_admin),
):
    today = datetime.now(MSK).date()
    d_to = _parse_day(date_to, today)
    d_from = _parse_day(date_from, d_to - timedelta(days=6))
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    start = datetime.combine(d_from, datetime.min.time(), tzinfo=MSK)
    end = datetime.combine(d_to + timedelta(days=1), datetime.min.time(), tzinfo=MSK)

    empty = {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "timezone": "Europe/Moscow",
        "data_status": "unavailable",
        "reason": "table_missing",
        "total": 0,
        "fiat_sum": None,
        "by_direction": [],
        "by_reason": [],
        "by_hour": [{"hour": h, "count": 0, "fiat_sum": None} for h in range(24)],
        "chart": [],
        "unique_rule": "one_client_per_hour",
        "definitions": {
            "miss": "Клиент не получил реквизиты, потому что на смене не было обеих ролей client+finance. Это те же пропуски, что в /dash.",
            "unique": "Один клиент за скользящий час. Повтор через 5–30 мин не считается. Сумма — первая попытка.",
        },
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'no_shift_requisites_blocks'
            )
            """
        )
        if not exists:
            return empty

        cols = {
            str(r["column_name"])
            for r in await conn.fetch(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'no_shift_requisites_blocks'
                """
            )
        }
        if not {"id", "user_id", "direction", "created_at"}.issubset(cols):
            return empty

        select = ["id", "user_id", "direction", "created_at"]
        if "reason" in cols:
            select.append("reason")
        if "fiat_amount" in cols:
            select.append("fiat_amount")
        rows = await conn.fetch(
            f"""
            SELECT {", ".join(select)}
            FROM no_shift_requisites_blocks
            WHERE created_at >= $1 AND created_at < $2
            ORDER BY created_at ASC, id ASC
            """,
            start - CLIENT_HOUR,
            end,
        )

    start_utc = start.astimezone(timezone.utc)
    kept = []
    for row in dedupe_miss_rows(list(rows)):
        ts = as_utc(row["created_at"])
        if ts is None or ts < start_utc:
            continue
        kept.append(row)
    by_day: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "fiat_sum": 0.0})
    by_hour = [{"hour": h, "count": 0, "fiat_sum": 0.0} for h in range(24)]
    by_direction: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "fiat_sum": 0.0})
    by_reason: dict[str, int] = defaultdict(int)
    fiat_total = 0.0
    fiat_known = False

    for row in kept:
        clock = msk_clock(row["created_at"])
        if clock is None:
            continue
        day, hour = clock
        direction = str(row["direction"] or "buy")[:8]
        reason = str(row["reason"] if "reason" in row.keys() else "no_shift") or "no_shift"
        fiat, has_fiat = row_fiat(row)
        if has_fiat:
            fiat_known = True
            fiat_total += fiat
        by_day[day]["count"] += 1
        by_day[day]["fiat_sum"] += fiat
        by_hour[hour]["count"] += 1
        by_hour[hour]["fiat_sum"] += fiat
        by_direction[direction]["count"] += 1
        by_direction[direction]["fiat_sum"] += fiat
        by_reason[reason] += 1

    chart = []
    cur = d_from
    while cur <= d_to:
        key = cur.isoformat()
        bucket = by_day.get(key, {"count": 0, "fiat_sum": 0.0})
        chart.append(
            {
                "date": key,
                "count": int(bucket["count"]),
                "fiat_sum": round(float(bucket["fiat_sum"]), 2) if fiat_known else None,
            }
        )
        cur += timedelta(days=1)

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "timezone": "Europe/Moscow",
        "data_status": "available",
        "reason": None,
        "total": len(kept),
        "fiat_sum": round(fiat_total, 2) if fiat_known else None,
        "unique_rule": "one_client_per_hour",
        "by_direction": [
            {
                "direction": key,
                "count": int(val["count"]),
                "fiat_sum": round(float(val["fiat_sum"]), 2) if fiat_known else None,
            }
            for key, val in sorted(by_direction.items())
        ],
        "by_reason": [{"reason": key, "count": int(val)} for key, val in sorted(by_reason.items())],
        "by_hour": [
            {
                "hour": int(slot["hour"]),
                "count": int(slot["count"]),
                "fiat_sum": round(float(slot["fiat_sum"]), 2) if fiat_known else None,
            }
            for slot in by_hour
        ],
        "chart": chart,
        "definitions": empty["definitions"],
    }
