#!/usr/bin/env python3
"""
Симуляция: мерчант проверил чек и подтвердил оплату.

Отправляет на наш /callback тот же JSON, что приходит от payfast после успешной
проверки чека (status_pending=ok, status=PAID или ACCEPTED, status_check=1).

Использование:
  cd /home/qwe/Desktop/tg_bot_btc
  .venv/bin/python scripts/simulate_merchant_check_confirmed.py ORDER_ID

  # если заявка ещё CREATED (пользователь не нажимал «Я оплатил»):
  .venv/bin/python scripts/simulate_merchant_check_confirmed.py ORDER_ID --prepare

  # последняя buy-заявка в БД:
  .venv/bin/python scripts/simulate_merchant_check_confirmed.py --latest

  # только показать payload, без POST:
  .venv/bin/python scripts/simulate_merchant_check_confirmed.py ORDER_ID --dry-run

Переменные из .env: DATABASE_DSN, MERCHANT_CALLBACK_URL (или --url).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from services import config_rates as cfg
import services.db as db
from services.db import get_order, init_db, update_order_to_awaiting_check
from services.webhook_security import sign_webhook_body

WEBHOOK_COMPLETABLE = frozenset({"PENDING", "AWAITING_CHECK"})


def _callback_target(explicit_url: str | None) -> str:
    raw = (explicit_url or os.getenv("MERCHANT_CALLBACK_URL") or cfg.MERCHANT.get("callback_url") or "").strip()
    if not raw:
        raise SystemExit(
            "Задайте MERCHANT_CALLBACK_URL в .env или передайте --url "
            "(например https://focuspay.org/callback)"
        )
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/") or raw.split("?")[0]


def _success_body(order_id: str, fiat_amount: float, *, payfast: bool) -> dict:
    data_order = {
        "client_transaction_id": str(order_id),
        "amount": int(round(fiat_amount)),
        "status": "PAID",
        "status_check": 1,
    }
    if payfast:
        api_key = (cfg.MERCHANT.get("api_key") or os.getenv("MERCHANT_API_KEY") or "").strip()
        merchant_id = cfg.MERCHANT.get("merchant_id") or os.getenv("MERCHANT_ID") or ""
        body = {
            "uuid": "00000000-0000-0000-0000-000000000000",
            "api_key": api_key,
            "client_transaction_id": str(order_id),
            "data_order": data_order,
        }
        if merchant_id:
            try:
                body["id_merchant"] = int(merchant_id)
            except ValueError:
                pass
        return body
    return {
        "status_pending": "ok",
        "status": "PAID",
        "status_check": 1,
        "data_order": data_order,
    }


async def _fetch_latest_buy(conn) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT order_id, status, direction, fiat_amount, merchant_order_id
        FROM orders
        WHERE direction = 'buy'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )


async def _run(args: argparse.Namespace) -> int:
    dsn = cfg.DATABASE_DSN
    if not dsn:
        raise SystemExit("DATABASE_DSN не задан в .env")

    await init_db(dsn)
    try:
        if args.latest:
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
            try:
                async with pool.acquire() as conn:
                    row = await _fetch_latest_buy(conn)
            finally:
                await pool.close()
            if not row:
                print("Нет buy-заявок в БД.")
                return 1
            order_id = row["order_id"]
            print(f"Последняя buy-заявка: {order_id} (status={row['status']})")
        else:
            order_id = args.order_id

        order = await get_order(order_id)
        if not order:
            print(f"Заявка не найдена: {order_id}")
            return 1

        direction = (order.get("direction") or "").lower()
        if direction != "buy":
            print(f"Скрипт только для buy, у заявки direction={direction!r}")
            return 1

        status = str(order.get("status") or "")
        print(f"order_id={order_id} status={status} fiat={order.get('fiat_amount')} "
              f"merchant_order_id={order.get('merchant_order_id')}")

        if args.prepare and status == "CREATED":
            ok = await update_order_to_awaiting_check(order_id, required_receipt_type=2)
            if not ok:
                print("Не удалось перевести в AWAITING_CHECK (неверный текущий статус).")
                return 1
            print("→ статус AWAITING_CHECK (как после «Я оплатил»)")
            order = await get_order(order_id)
            status = str(order.get("status") or "")

        if status not in WEBHOOK_COMPLETABLE:
            print(
                f"Внимание: webhook завершит заявку только из "
                f"{sorted(WEBHOOK_COMPLETABLE)}, сейчас {status!r}. "
                f"Используйте --prepare для CREATED или дождитесь загрузки чека."
            )
            if not args.force:
                return 1

        body = _success_body(
            order_id, float(order.get("fiat_amount") or 0), payfast=not args.legacy_hmac
        )
        url = _callback_target(args.url)
        body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if args.legacy_hmac:
            ts = str(int(time.time()))
            sig, ts = sign_webhook_body(body_bytes, ts)
            if not sig:
                raise SystemExit(
                    "MERCHANT_SECRET_KEY или WEBHOOK_SECRET не задан — нельзя подписать запрос"
                )
            headers["X-Signature"] = sig
            headers["X-Timestamp"] = ts
        elif not (cfg.MERCHANT.get("api_key") or os.getenv("MERCHANT_API_KEY")):
            raise SystemExit("MERCHANT_API_KEY не задан — нужен для Payfast-form callback")

        print("\nPOST", url)
        print(json.dumps(body, ensure_ascii=False, indent=2))

        if args.dry_run:
            print("\n(dry-run, запрос не отправлен)")
            return 0

        r = requests.post(
            url,
            data=body_bytes,
            headers=headers,
            timeout=30,
        )
        print(f"\nHTTP {r.status_code}")
        try:
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
        except Exception:
            print(r.text)

        order_after = await get_order(order_id)
        if order_after:
            print(f"\nСтатус в БД после webhook: {order_after.get('status')}")

        if r.status_code >= 400:
            return 1
        return 0
    finally:
        if db.DB_POOL is not None:
            await db.DB_POOL.close()
            db.DB_POOL = None


def main() -> None:
    p = argparse.ArgumentParser(
        description="Симуляция подтверждения чека мерчантом (success webhook)"
    )
    p.add_argument("order_id", nargs="?", help="Наш order_id (client_transaction_id)")
    p.add_argument("--latest", action="store_true", help="Взять последнюю buy-заявку")
    p.add_argument("--url", help="URL callback (иначе MERCHANT_CALLBACK_URL из .env)")
    p.add_argument(
        "--prepare",
        action="store_true",
        help="Если статус CREATED — перевести в AWAITING_CHECK перед webhook",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Отправить webhook даже если статус не PENDING/AWAITING_CHECK",
    )
    p.add_argument("--dry-run", action="store_true", help="Только показать payload")
    p.add_argument(
        "--legacy-hmac",
        action="store_true",
        help="Старый формат: HMAC в заголовках вместо Payfast api_key в теле",
    )
    args = p.parse_args()

    if not args.latest and not args.order_id:
        p.error("Укажите order_id или --latest")

    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
