#!/usr/bin/env python3
"""
Диагностика статуса Payfast payin — ОДИН read-only запрос POST /get_order.

НЕ создаёт заявки, НЕ запрашивает реквизиты (create_order_payin не вызывается).
Не меняет статусы в БД и не трогает баланс.

Использование:
  cd /home/qwe/Desktop/tg_bot_btc

  # Только БД, без запроса в Payfast:
  .venv/bin/python scripts/probe_payin_status.py ae594b34-d539-4f77-b42a-6f060c5c82ac --dry-run

  # Ровно один запрос get_order (нужен --confirm):
  .venv/bin/python scripts/probe_payin_status.py ae594b34-d539-4f77-b42a-6f060c5c82ac --confirm

  # По uuid напрямую (без БД):
  .venv/bin/python scripts/probe_payin_status.py --uuid ae594b34-d539-4f77-b42a-6f060c5c82ac --confirm

  # Последняя buy-заявка:
  .venv/bin/python scripts/probe_payin_status.py --latest --confirm

Переменные из .env: DATABASE_DSN (если нужна БД), MERCHANT_BASE_URL, MERCHANT_API_KEY, MERCHANT_SECRET_KEY.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from services import config_rates as cfg
import services.db as db
from services.db import get_order, init_db
from services.merchant_client import get_merchant_order
from services.merchant_order_id import resolve_merchant_display_id, resolve_payfast_uuid_system
from services.payfast_payin_guard import (
    is_payfast_failure_status,
    is_payfast_file_pending,
    is_payfast_recheck_requested,
    is_payfast_settled,
    payfast_block_message,
    payfast_status_check_from_payload,
    payfast_status_file_from_payload,
    payfast_status_from_payload,
    verify_payfast_ready_for_payout,
)


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


async def _fetch_latest_buy(conn) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT order_id, status, direction, fiat_amount, merchant_order_id, payment_snapshot
        FROM orders
        WHERE direction = 'buy'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )


async def _resolve_order(args: argparse.Namespace) -> tuple[dict | None, str | None]:
    """(order_dict|None, uuid_system) — uuid из --uuid или из заявки в БД."""
    if args.uuid:
        return None, str(args.uuid).strip()

    dsn = cfg.DATABASE_DSN
    if not dsn:
        raise SystemExit("DATABASE_DSN не задан — укажите order_id или --uuid")

    await init_db(dsn)

    if args.latest:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
        try:
            async with pool.acquire() as conn:
                row = await _fetch_latest_buy(conn)
        finally:
            await pool.close()
        if not row:
            raise SystemExit("Нет buy-заявок в БД.")
        order_id = row["order_id"]
        print(f"Последняя buy-заявка: {order_id} (status={row['status']})")
    else:
        order_id = args.order_id

    order = await get_order(order_id)
    if not order:
        raise SystemExit(f"Заявка не найдена: {order_id}")

    order = dict(order)
    uuid_system = resolve_payfast_uuid_system(order)
    return order, uuid_system


def _print_db_summary(order: dict) -> None:
    oid = order.get("order_id")
    print("\n--- Заявка в БД ---")
    print(f"order_id:           {oid}")
    print(f"status:             {order.get('status')}")
    print(f"direction:          {order.get('direction')}")
    print(f"fiat_amount:        {order.get('fiat_amount')}")
    print(f"crypto_amount:      {order.get('crypto_amount')}")
    print(f"merchant_order_id:  {order.get('merchant_order_id')}")
    print(f"Payfast display id: {resolve_merchant_display_id(order)}")


def _print_payfast_parsed(resp: dict) -> None:
    st = payfast_status_from_payload(resp)
    sf = payfast_status_file_from_payload(resp)
    sc = payfast_status_check_from_payload(resp)
    print("\n--- Разбор ответа Payfast ---")
    print(f"status:        {st!r}")
    print(f"status_file:   {sf!r}")
    print(f"status_check:  {sc!r}")
    print(f"is_settled:              {is_payfast_settled(st, sf)}")
    print(f"is_failure:              {is_payfast_failure_status(st)}")
    print(f"is_recheck_requested:    {is_payfast_recheck_requested(sc)}")
    print(f"is_file_pending:         {is_payfast_file_pending(sf)}")


async def _run(args: argparse.Namespace) -> int:
    _load_env()

    try:
        order, uuid_system = await _resolve_order(args)

        if order:
            _print_db_summary(order)

        if not uuid_system:
            raise SystemExit(
                "Не найден uuid_system Payfast для этой заявки. "
                "Передайте --uuid вручную или проверьте payment_snapshot / merchant_order_id."
            )

        print(f"\nPayfast uuid_system: {uuid_system}")

        if args.dry_run:
            print("\n(dry-run: запрос POST /get_order НЕ отправлен)")
            if order:
                print("\nДля вердикта выплаты без API используйте --confirm (1 запрос).")
            return 0

        if not args.confirm:
            print(
                "\nЗапрос в Payfast не выполнен. "
                "Добавьте --confirm для ровно одного POST /get_order (read-only, без реквизитов)."
            )
            return 0

        print("\n>>> Один запрос: POST /get_order (read-only, реквизиты не запрашиваются)")
        resp = await get_merchant_order(uuid_system)
        print("\n--- Сырой ответ Payfast ---")
        print(json.dumps(resp, ensure_ascii=False, indent=2))

        _print_payfast_parsed(resp)

        if order:
            ok, reason, _ = await verify_payfast_ready_for_payout(order, require_uuid=True)
            print("\n--- Вердикт verify_payfast_ready_for_payout ---")
            print(f"payout_allowed: {ok}")
            if reason:
                print(f"block_code:     {reason}")
                print(f"message:        {payfast_block_message(reason)}")
            else:
                print("message:        Выплата разрешена — «✅ Выплачено» должно пройти.")

        print("\n(диагностика завершена, повторных запросов в Payfast не было)")
        return 0
    finally:
        if db.DB_POOL is not None:
            await db.DB_POOL.close()
            db.DB_POOL = None


def main() -> None:
    p = argparse.ArgumentParser(
        description="Диагностика Payfast payin: один read-only POST /get_order"
    )
    p.add_argument("order_id", nargs="?", help="Наш order_id или Payfast uuid из ops-чата")
    p.add_argument("--uuid", help="Payfast uuid_system напрямую (без БД)")
    p.add_argument("--latest", action="store_true", help="Последняя buy-заявка в БД")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Только БД / uuid, без запроса в Payfast",
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="Выполнить ровно один POST /get_order (обязателен для API)",
    )
    args = p.parse_args()

    if not args.uuid and not args.latest and not args.order_id:
        p.error("Укажите order_id, --uuid или --latest")

    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
