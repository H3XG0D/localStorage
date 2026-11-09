#!/usr/bin/env python3
"""Разбор зарплаты операторов за последние N дней (запуск на сервере)."""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for p in ("/opt/tg_bot_btc", "/opt/exchange-backend"):
    if Path(p).exists():
        sys.path.insert(0, p)

from services.economics_snapshot import order_economics

import asyncpg


def load_dsn() -> str:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DATABASE_DSN="):
                return line.split("=", 1)[1].strip()
    return os.environ["DATABASE_DSN"]


async def fetch_accruals(conn, order_ids: list[str]) -> dict[str, dict[str, float]]:
    out = {oid: {"cashback": 0.0, "referral": 0.0} for oid in order_ids}
    if not order_ids:
        return out
    for r in await conn.fetch(
        """
        SELECT order_id, COALESCE(SUM(amount_rub), 0)::float AS rub
        FROM user_cashback_ledger
        WHERE order_id = ANY($1::text[]) AND type = 'accrual'
        GROUP BY order_id
        """,
        order_ids,
    ):
        out[r["order_id"]]["cashback"] = float(r["rub"])
    for r in await conn.fetch(
        """
        SELECT order_id, COALESCE(SUM(amount_rub), 0)::float AS rub
        FROM user_referral_ledger
        WHERE order_id = ANY($1::text[]) AND type = 'accrual'
        GROUP BY order_id
        """,
        order_ids,
    ):
        if r["order_id"] in out:
            out[r["order_id"]]["referral"] = float(r["rub"])
    return out


def order_profit(o) -> float:
    return order_economics(dict(o))["service_profit_rub"]


async def main(days: int = 7) -> None:
    conn = await asyncpg.connect(load_dsn())
    shifts = await conn.fetch(
        f"""
        SELECT s.id, s.operator_id, s.started_at, s.ended_at, a.percent,
               COALESCE(a.display_name, a.username) AS operator
        FROM operator_shifts s
        JOIN operator_accounts a ON a.id = s.operator_id
        WHERE s.started_at >= NOW() - INTERVAL '{days} days'
          AND s.ended_at IS NOT NULL
        ORDER BY s.id
        """
    )

    total_by_op: dict[str, dict] = {}

    hdr = (
        f"{'shift':>5} {'operator':<14} {'pct':>4} {'ords':>4} {'fiat':>8} "
        f"{'profit':>8} {'cb+ref':>7} {'base':>8} {'calc':>7} {'paid':>7} "
        f"{'rub/ord':>7} {'rub/1k':>6}"
    )
    print(hdr)
    print("-" * len(hdr))

    for sh in shifts:
        orders = await conn.fetch(
            """
            SELECT o.order_id, o.direction, o.crypto, o.fiat_amount, o.crypto_amount, o.rate,
                   o.cashback_applied_rub, o.card_fee_pct, o.economics_snapshot
            FROM orders o
            WHERE o.operator_id = $1
              AND o.status IN ('PAID', 'COMPLETED')
              AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) >= $2
              AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) <= $3
            """,
            sh["operator_id"],
            sh["started_at"],
            sh["ended_at"],
        )

        order_ids = [r["order_id"] for r in orders]
        accruals = await fetch_accruals(conn, order_ids)

        profit = base = acc_sum = fiat = 0.0
        for o in orders:
            fiat += float(o["fiat_amount"] or 0)
            p = order_profit(o)
            acc = accruals.get(o["order_id"], {})
            ded = float(acc.get("cashback", 0)) + float(acc.get("referral", 0))
            profit += p
            acc_sum += ded
            base += max(0.0, p - ded)

        pct = float(sh["percent"])
        calc = round(base * pct / 100, 2)
        paid = await conn.fetchval(
            "SELECT amount_rub FROM operator_payroll_ledger WHERE shift_id=$1 AND type='accrual'",
            sh["id"],
        )
        paid = float(paid or 0)
        n = len(orders)
        rub_ord = calc / n if n else 0.0
        rub_1k = calc / fiat * 1000 if fiat else 0.0
        op = str(sh["operator"])[:14]
        flag = ""
        if abs(calc - paid) > 0.02 and (calc > 0 or paid > 0):
            flag = " !"
        elif calc == 0 and paid == 0:
            flag = " 0"

        print(
            f"{sh['id']:>5} {op:<14} {pct:>4.0f} {n:>4} {fiat:>8.0f} "
            f"{profit:>8.0f} {acc_sum:>7.0f} {base:>8.0f} {calc:>7.2f} {paid:>7.2f} "
            f"{rub_ord:>7.2f} {rub_1k:>6.2f}{flag}"
        )

        key = str(sh["operator"])
        if key not in total_by_op:
            total_by_op[key] = {
                "shifts": 0,
                "orders": 0,
                "fiat": 0.0,
                "profit": 0.0,
                "base": 0.0,
                "calc": 0.0,
                "paid": 0.0,
                "zero_shifts": 0,
                "pct": pct,
            }
        t = total_by_op[key]
        t["shifts"] += 1
        t["orders"] += n
        t["fiat"] += fiat
        t["profit"] += profit
        t["base"] += base
        t["calc"] += calc
        t["paid"] += paid
        if calc == 0:
            t["zero_shifts"] += 1

    print("\n=== ИТОГО по операторам ===")
    grand_fiat = grand_paid = 0.0
    for op, t in sorted(total_by_op.items(), key=lambda x: -x[1]["paid"]):
        rub_1k = t["paid"] / t["fiat"] * 1000 if t["fiat"] else 0.0
        rub_ord = t["paid"] / t["orders"] if t["orders"] else 0.0
        margin = t["profit"] / t["fiat"] * 100 if t["fiat"] else 0.0
        print(
            f"{op:<14} pct={t['pct']:.0f}%  смен:{t['shifts']:>2} (нулевых:{t['zero_shifts']})  "
            f"сделок:{t['orders']:>3}  оборот:{t['fiat']:>9.0f}₽  "
            f"прибыль:{t['profit']:>7.0f}₽ ({margin:.2f}%)  "
            f"база:{t['base']:>7.0f}₽  начислено:{t['paid']:>8.2f}₽  "
            f"({rub_1k:.2f}₽/1000₽, {rub_ord:.1f}₽/сделка)"
        )
        grand_fiat += t["fiat"]
        grand_paid += t["paid"]

    print(
        f"\nВСЕГО: оборот {grand_fiat:,.0f}₽, начислено операторам {grand_paid:,.2f}₽ "
        f"({grand_paid/grand_fiat*1000:.2f}₽ на 1000₽ оборота)"
    )

    print("\n=== Смены с 0 начислением ===")
    for sh in shifts:
        paid = await conn.fetchval(
            "SELECT amount_rub FROM operator_payroll_ledger WHERE shift_id=$1 AND type='accrual'",
            sh["id"],
        )
        if paid:
            continue

        orders_payout = await conn.fetch(
            """
            SELECT o.order_id, o.fiat_amount, o.direction, o.crypto, o.crypto_amount, o.rate,
                   o.cashback_applied_rub, o.card_fee_pct, o.economics_snapshot,
                   o.created_at, o.payout_confirmed_at
            FROM orders o
            WHERE o.operator_id = $1 AND o.status IN ('PAID', 'COMPLETED')
              AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) >= $2
              AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) <= $3
            """,
            sh["operator_id"],
            sh["started_at"],
            sh["ended_at"],
        )
        row = await conn.fetchrow(
            """
            SELECT COUNT(*)::int AS cnt, COALESCE(SUM(fiat_amount), 0)::float AS fiat
            FROM orders
            WHERE operator_id = $1 AND status IN ('PAID', 'COMPLETED')
              AND created_at >= $2 AND created_at <= $3
            """,
            sh["operator_id"],
            sh["started_at"],
            sh["ended_at"],
        )
        print(
            f"  shift #{sh['id']} {sh['operator']}: "
            f"payout_window={len(orders_payout)} created_at={row['cnt']} "
            f"fiat_created={row['fiat']:.0f}"
        )
        for o in orders_payout:
            p = order_profit(o)
            print(f"    {o['order_id'][:16]} fiat={o['fiat_amount']} profit={p:.2f}")

    await conn.close()


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    asyncio.run(main(days))
