#!/usr/bin/env python3
"""
Дожать BUY-выплату: COMPLETED → PAID + начисления + уведомление клиенту.

Использование:
  .venv/bin/python scripts/complete_operator_payout.py ORDER_ID TX_HASH
  .venv/bin/python scripts/complete_operator_payout.py ORDER_ID --notify-only
  .venv/bin/python scripts/complete_operator_payout.py ORDER_ID TX_HASH --operator-id 1
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.db as db
from services import config_rates as cfg
from services.buy_payout import (
    build_explorer_url,
    confirm_buy_payout,
    normalize_tx_hash,
    notify_buyer_paid,
)
from services.db import get_order, init_db


async def _run(args: argparse.Namespace) -> int:
    if not cfg.DATABASE_DSN:
        raise SystemExit("DATABASE_DSN не задан")

    await init_db(cfg.DATABASE_DSN)
    try:
        order = await get_order(args.order_id.strip())
        if not order:
            print(f"Заявка не найдена: {args.order_id}")
            return 1

        status = str(order.get("status") or "").upper()
        print(
            f"order_id={order['order_id']} status={status} "
            f"operator_id={order.get('operator_id')} "
            f"payout_tx_hash={order.get('payout_tx_hash')}"
        )

        if args.notify_only:
            if status != "PAID":
                print("notify-only: заявка не в статусе PAID")
                return 1
            tx = (order.get("payout_tx_hash") or "").strip()
            if not tx:
                print("Нет payout_tx_hash в заявке")
                return 1
            explorer = build_explorer_url(str(order.get("crypto") or ""), tx)
            await notify_buyer_paid(dict(order), explorer)
            print("Уведомление клиенту отправлено (повторно)")
            return 0

        tx_raw = args.tx_hash or order.get("payout_tx_hash") or ""
        normalized = normalize_tx_hash(str(tx_raw))
        if not normalized:
            raise SystemExit("Укажите корректный tx_hash")

        ok, err, out = await confirm_buy_payout(
            args.order_id.strip(),
            tx_hash=normalized,
            actor=args.actor,
            operator_id=args.operator_id,
        )
        if not ok:
            print(f"Ошибка: {err}")
            return 1

        print(f"OK → PAID, tx={normalized}")
        if out:
            print(f"fiat={out.get('fiat_amount')} crypto={out.get('crypto_amount')}")
        return 0
    finally:
        if db.DB_POOL is not None:
            await db.DB_POOL.close()
            db.DB_POOL = None


def main() -> None:
    p = argparse.ArgumentParser(description="Завершить operator BUY payout")
    p.add_argument("order_id")
    p.add_argument("tx_hash", nargs="?", help="Hash транзакции")
    p.add_argument("--operator-id", type=int, default=None)
    p.add_argument("--actor", default="script:repair")
    p.add_argument(
        "--notify-only",
        action="store_true",
        help="Только повторно отправить Telegram (заявка уже PAID)",
    )
    args = p.parse_args()
    if not args.notify_only and not args.tx_hash:
        p.error("Укажите tx_hash или --notify-only")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
