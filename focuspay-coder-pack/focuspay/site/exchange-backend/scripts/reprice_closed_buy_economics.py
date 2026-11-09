#!/usr/bin/env python3
"""Reprice closed BUY economics snapshots under the 20/21/22 percent policy.

The default mode is read-only. --apply requires a caller-provided run ID and writes
an audit revision before updating each order snapshot. --rollback restores only
rows that still contain the snapshot produced by that run.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Mapping

import asyncpg

from economics_snapshot import build_economics_snapshot, order_economics

CUTOFF_MOSCOW = datetime.fromisoformat("2026-08-17T00:00:00+03:00")
REPRICE_FORMULA_VERSION = "repriced_buy_v1"
POLICY_HISTORICAL_20 = "historical_20"
POLICY_RECENT_AUTO_21 = "recent_auto_21"
POLICY_RECENT_MANUAL_22 = "recent_manual_22"
POLICY_MANUAL_OPERATOR_EXCLUDED = "manual_operator_excluded"
LEGACY_AUTO_CARD_FEE_PCT = 0.12
LEGACY_MANUAL_CARD_FEE_PCT = 0.14

SELECT_COLUMNS = """
    id, order_id, direction, crypto, fiat_amount, crypto_amount, rate,
    cashback_applied_rub, card_fee_pct, economics_snapshot, created_at,
    order_source, manual_spread_pct, merchant_order_id, payment_snapshot
"""


def _json_value(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return dict(value) if isinstance(value, Mapping) else None


def _is_manual_operator(order: Mapping[str, Any]) -> bool:
    return (
        str(order.get("order_source") or "").lower() == "manual_operator"
        and order.get("manual_spread_pct") is not None
    )


def _is_auto_buy(order: Mapping[str, Any]) -> bool:
    fee = order.get("card_fee_pct")
    if fee is not None:
        fee_value = float(fee)
        return abs(fee_value - LEGACY_AUTO_CARD_FEE_PCT) <= abs(
            fee_value - LEGACY_MANUAL_CARD_FEE_PCT
        )

    payment = _json_value(order.get("payment_snapshot")) or {}
    if str(payment.get("merchant_uuid") or "").strip():
        return True

    merchant_order_id = str(order.get("merchant_order_id") or "").strip()
    order_id = str(order.get("order_id") or "").strip()
    return bool(merchant_order_id and merchant_order_id != order_id and "-" in merchant_order_id)


def reprice_policy(order: Mapping[str, Any]) -> tuple[str, float | None]:
    """Return policy and immutable quote markup; None means intentionally excluded."""
    if _is_manual_operator(order):
        return POLICY_MANUAL_OPERATOR_EXCLUDED, None

    created_at = order.get("created_at")
    if not isinstance(created_at, datetime):
        raise ValueError(f"order {order.get('order_id')} has no created_at")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    if created_at.astimezone(CUTOFF_MOSCOW.tzinfo) < CUTOFF_MOSCOW:
        return POLICY_HISTORICAL_20, 1.20
    if _is_auto_buy(order):
        return POLICY_RECENT_AUTO_21, 1.21
    return POLICY_RECENT_MANUAL_22, 1.22


def rebuilt_snapshot(
    order: Mapping[str, Any], *, policy: str, markup: float, run_id: str
) -> dict[str, Any]:
    raw_fee = order.get("card_fee_pct")
    # Historical schema explicitly defines NULL as the legacy automatic 12% fee.
    card_fee = float(raw_fee) if raw_fee is not None else LEGACY_AUTO_CARD_FEE_PCT
    snapshot = build_economics_snapshot(
        "buy",
        str(order.get("crypto") or ""),
        float(order.get("fiat_amount") or 0),
        float(order.get("crypto_amount") or 0),
        float(order.get("rate") or 0),
        cashback_applied_rub=float(order.get("cashback_applied_rub") or 0),
        card_fee=card_fee,
        manual_buy=policy == POLICY_RECENT_MANUAL_22,
        buy_markup_override=markup,
        formula_version=REPRICE_FORMULA_VERSION,
    )
    snapshot["reprice_policy"] = policy
    snapshot["reprice_run_id"] = run_id
    return snapshot


def report_for_orders(orders: list[Mapping[str, Any]], *, run_id: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "candidates": 0,
        "excluded": 0,
        "policies": Counter(),
        "snapshots": Counter(),
        "old_profit_rub": 0.0,
        "new_profit_rub": 0.0,
        "delta_profit_rub": 0.0,
        "null_card_fee": 0,
        "manual_operator_order_ids": [],
    }
    for order in orders:
        snapshot = _json_value(order.get("economics_snapshot")) or {}
        report["snapshots"][str(snapshot.get("formula_version") or "missing")] += 1
        if order.get("card_fee_pct") is None:
            report["null_card_fee"] += 1
        policy, markup = reprice_policy(order)
        report["policies"][policy] += 1
        if markup is None:
            report["excluded"] += 1
            report["manual_operator_order_ids"].append(str(order["order_id"]))
            continue
        report["candidates"] += 1
        old_profit = order_economics(order, clamp=False)["service_profit_rub"]
        new_profit = rebuilt_snapshot(
            order, policy=policy, markup=markup, run_id=run_id
        )["service_profit_rub"]
        report["old_profit_rub"] += old_profit
        report["new_profit_rub"] += new_profit
    report["delta_profit_rub"] = report["new_profit_rub"] - report["old_profit_rub"]
    report["policies"] = dict(report["policies"])
    report["snapshots"] = dict(report["snapshots"])
    return report


async def _fetch_candidates(
    conn: asyncpg.Connection, *, batch_size: int | None = None, after_id: int | None = None
):
    query = f"""
        SELECT {SELECT_COLUMNS}
        FROM orders
        WHERE status IN ('PAID', 'COMPLETED')
          AND LOWER(direction) = 'buy'
    """
    params: list[Any] = []
    if after_id is not None:
        query += f" AND id > ${len(params) + 1}"
        params.append(after_id)
    query += " ORDER BY id"
    if batch_size is not None:
        query += f" LIMIT ${len(params) + 1} FOR UPDATE SKIP LOCKED"
        params.append(batch_size)
    return await conn.fetch(query, *params)


async def dry_run(*, dsn: str, run_id: str) -> dict[str, Any]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await _fetch_candidates(conn)
        return report_for_orders([dict(row) for row in rows], run_id=run_id)
    finally:
        await conn.close()


async def apply(*, dsn: str, run_id: str, batch_size: int) -> dict[str, int]:
    conn = await asyncpg.connect(dsn)
    counts = Counter()
    after_id = 0
    try:
        while True:
            async with conn.transaction():
                rows = await _fetch_candidates(
                    conn, batch_size=batch_size, after_id=after_id
                )
                if not rows:
                    break
                after_id = int(rows[-1]["id"])
                changed_at = datetime.now(tz=timezone.utc)
                for row in rows:
                    order = dict(row)
                    policy, markup = reprice_policy(order)
                    counts[policy] += 1
                    if markup is None:
                        continue
                    old_snapshot = _json_value(order.get("economics_snapshot"))
                    new_snapshot = rebuilt_snapshot(
                        order, policy=policy, markup=markup, run_id=run_id
                    )
                    old_profit = order_economics(order, clamp=False)["service_profit_rub"]
                    inserted = await conn.execute(
                        """
                        INSERT INTO order_economics_snapshot_revisions (
                            order_id, run_id, policy, old_snapshot, new_snapshot,
                            old_service_profit_rub, new_service_profit_rub, changed_at
                        ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
                        ON CONFLICT (run_id, order_id) DO NOTHING
                        """,
                        str(order["order_id"]),
                        run_id,
                        policy,
                        json.dumps(old_snapshot) if old_snapshot is not None else None,
                        json.dumps(new_snapshot),
                        old_profit,
                        new_snapshot["service_profit_rub"],
                        changed_at,
                    )
                    if not inserted.endswith(" 1"):
                        counts["already_revised"] += 1
                        continue
                    result = await conn.execute(
                        """
                        UPDATE orders
                        SET economics_snapshot = $2::jsonb
                        WHERE order_id = $1
                          AND economics_snapshot IS NOT DISTINCT FROM $3::jsonb
                        """,
                        str(order["order_id"]),
                        json.dumps(new_snapshot),
                        json.dumps(old_snapshot) if old_snapshot is not None else None,
                    )
                    if result.endswith(" 1"):
                        counts["updated"] += 1
                    else:
                        await conn.execute(
                            """
                            DELETE FROM order_economics_snapshot_revisions
                            WHERE run_id = $1 AND order_id = $2
                            """,
                            run_id,
                            str(order["order_id"]),
                        )
                        counts["concurrent_change"] += 1
        return dict(counts)
    finally:
        await conn.close()


async def rollback(*, dsn: str, run_id: str, batch_size: int) -> dict[str, int]:
    conn = await asyncpg.connect(dsn)
    counts = Counter()
    try:
        while True:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT r.order_id, r.old_snapshot, r.new_snapshot
                    FROM order_economics_snapshot_revisions r
                    WHERE r.run_id = $1
                      AND r.reverted_at IS NULL
                      AND r.rollback_skipped_at IS NULL
                    ORDER BY r.id
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                    """,
                    run_id,
                    batch_size,
                )
                if not rows:
                    break
                for row in rows:
                    result = await conn.execute(
                        """
                        UPDATE orders
                        SET economics_snapshot = $2::jsonb
                        WHERE order_id = $1
                          AND economics_snapshot IS NOT DISTINCT FROM $3::jsonb
                        """,
                        str(row["order_id"]),
                        json.dumps(_json_value(row["old_snapshot"]))
                        if _json_value(row["old_snapshot"]) is not None
                        else None,
                        json.dumps(_json_value(row["new_snapshot"])),
                    )
                    if result.endswith(" 1"):
                        counts["restored"] += 1
                        await conn.execute(
                            """
                            UPDATE order_economics_snapshot_revisions
                            SET reverted_at = now()
                            WHERE run_id = $1 AND order_id = $2
                            """,
                            run_id,
                            str(row["order_id"]),
                        )
                    else:
                        counts["skipped_changed"] += 1
                        await conn.execute(
                            """
                            UPDATE order_economics_snapshot_revisions
                            SET rollback_skipped_at = now()
                            WHERE run_id = $1 AND order_id = $2
                            """,
                            run_id,
                            str(row["order_id"]),
                        )
        return dict(counts)
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_DSN", ""))
    parser.add_argument("--run-id", default="dry-run")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--apply", action="store_true", help="write revisions and snapshots")
    parser.add_argument("--rollback", action="store_true", help="restore snapshots from --run-id")
    args = parser.parse_args()
    if not args.dsn:
        print("DATABASE_DSN required", file=sys.stderr)
        return 1
    if args.batch_size < 1 or args.batch_size > 1000:
        print("--batch-size must be between 1 and 1000", file=sys.stderr)
        return 1
    if args.apply and args.rollback:
        print("--apply and --rollback cannot be combined", file=sys.stderr)
        return 1
    if (args.apply or args.rollback) and args.run_id == "dry-run":
        print("--run-id is required for apply or rollback", file=sys.stderr)
        return 1

    if args.rollback:
        output = asyncio.run(rollback(dsn=args.dsn, run_id=args.run_id, batch_size=args.batch_size))
    elif args.apply:
        output = asyncio.run(apply(dsn=args.dsn, run_id=args.run_id, batch_size=args.batch_size))
    else:
        output = asyncio.run(dry_run(dsn=args.dsn, run_id=args.run_id))
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
