#!/usr/bin/env python3
"""Resend ops receipt-review card for latest IP-reuse order (or --order-id)."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_ROOT))


async def _pick_order(order_id: str | None) -> dict | None:
    from services.db import get_order, get_pool

    if order_id:
        return await get_order(order_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT order_id
            FROM orders
            WHERE (payment_snapshot->>'device_ip_reuse') = 'true'
               OR (
                    payment_snapshot ? 'device_ip_matches'
                    AND jsonb_typeof(payment_snapshot->'device_ip_matches') = 'array'
                    AND jsonb_array_length(payment_snapshot->'device_ip_matches') > 0
               )
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
    if not row:
        return None
    return await get_order(str(row["order_id"]))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from services import config_rates as cfg
    from services.callback_signatures import sign_receipt_review
    from services.db import init_db, get_bot_user
    from services.order_ops_notify import notify_ops_receipt_review
    from services.receipt_ops_review import _build_receipt_risk_note
    from telegram import Bot

    await init_db(cfg.DATABASE_DSN)
    order = await _pick_order(args.order_id)
    if not order:
        print("No IP-reuse order found")
        return 1

    oid = str(order["order_id"])
    uid = int(order["user_id"])
    from services.payment_snapshot import order_payment_snapshot

    snap = order_payment_snapshot(order)
    print("order:", oid)
    print("user:", uid)
    print("status:", order.get("status"))
    print("ip_reuse:", snap.get("device_ip_reuse"))
    print("matches:", snap.get("device_ip_matches"))
    print("reuse_count:", snap.get("device_reuse_count"))

    bu = await get_bot_user(uid) or {}
    risk_note, risk_level = await _build_receipt_risk_note(order, pdf_meta=None)
    print("risk_level:", risk_level)
    print("--- note preview ---")
    print(risk_note)
    print("---")

    if args.dry_run:
        print("dry-run: not sending")
        return 0

    bot = Bot(token=cfg.TELEGRAM_BOT_TOKEN)
    sig = sign_receipt_review(oid)
    await notify_ops_receipt_review(
        order,
        bot,
        username=(bu.get("username") or None),
        review_signature=sig,
        note=risk_note,
        prefer_client_review_group=True,
    )
    print("sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
