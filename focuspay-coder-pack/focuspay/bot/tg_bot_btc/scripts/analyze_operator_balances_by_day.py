#!/usr/bin/env python3
"""Балансы операторов по дням: что ввели на начало/конец смен и как менялось."""
import asyncio
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for p in ("/opt/tg_bot_btc", "/opt/exchange-backend"):
    if Path(p).exists():
        sys.path.insert(0, p)

import asyncpg

CRYPTOS = ("usdt", "btc", "trx", "ltc")


def load_dsn() -> str:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DATABASE_DSN="):
                return line.split("=", 1)[1].strip()
    return os.environ["DATABASE_DSN"]


def fmt_amount(v: float | None, width: int = 10) -> str:
    if v is None:
        return "—".rjust(width)
    return f"{v:>{width}.4f}"


async def main(days: int | None = 14, operator_id: int | None = None, month: bool = False) -> None:
    conn = await asyncpg.connect(load_dsn())

    if month:
        where_date = "AND (s.started_at AT TIME ZONE 'Europe/Moscow')::date >= date_trunc('month', NOW() AT TIME ZONE 'Europe/Moscow')::date"
        period_label = "текущий месяц"
    else:
        d = days or 14
        where_date = f"AND s.started_at >= NOW() - make_interval(days => {d})"
        period_label = f"последние {d} дн."

    where_op = "AND s.operator_id = $1" if operator_id is not None else ""
    params: list = []
    if operator_id is not None:
        params.append(operator_id)

    rows = await conn.fetch(
        f"""
        SELECT
            s.id AS shift_id,
            s.operator_id,
            COALESCE(a.display_name, a.username) AS operator,
            (s.started_at AT TIME ZONE 'Europe/Moscow')::date AS work_date,
            s.started_at,
            s.ended_at,
            b.crypto,
            b.balance_start,
            b.balance_end
        FROM operator_shifts s
        JOIN operator_accounts a ON a.id = s.operator_id
        LEFT JOIN operator_shift_balances b ON b.shift_id = s.id
        WHERE TRUE {where_date}
          {where_op}
        ORDER BY s.operator_id, s.started_at, b.crypto
        """,
        *params,
    )

    shifts: dict[int, dict] = {}
    for r in rows:
        sid = r["shift_id"]
        if sid not in shifts:
            shifts[sid] = {
                "operator_id": r["operator_id"],
                "operator": r["operator"],
                "work_date": r["work_date"],
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
                "balances": {},
            }
        if r["crypto"]:
            shifts[sid]["balances"][r["crypto"]] = {
                "start": float(r["balance_start"]) if r["balance_start"] is not None else None,
                "end": float(r["balance_end"]) if r["balance_end"] is not None else None,
            }

    if not shifts:
        print(f"Смен за {period_label} не найдено.")
        await conn.close()
        return

    by_op_date: dict[tuple[int, date], list[dict]] = defaultdict(list)
    for sh in shifts.values():
        by_op_date[(sh["operator_id"], sh["work_date"])].append(sh)

    print(f"=== Балансы операторов по дням ({period_label}) ===\n")

    for (op_id, work_date), day_shifts in sorted(
        by_op_date.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True
    ):
        op_name = day_shifts[0]["operator"]
        print(f"## {work_date} — {op_name} ({len(day_shifts)} смен)")
        for sh in sorted(day_shifts, key=lambda s: s["started_at"]):
            t0 = sh["started_at"].strftime("%H:%M")
            t1 = sh["ended_at"].strftime("%H:%M") if sh["ended_at"] else "…"
            print(f"  смена #{sh['shift_id']}  {t0}–{t1}")
            if not sh["balances"]:
                print("    балансы не заполнены")
                continue
            for crypto in CRYPTOS:
                b = sh["balances"].get(crypto)
                if not b:
                    continue
                s, e = b["start"], b["end"]
                delta = ""
                if s is not None and e is not None:
                    delta = f"  Δ={e - s:+.4f}"
                print(
                    f"    {crypto.upper():4}  start={fmt_amount(s)}  "
                    f"end={fmt_amount(e)}{delta}"
                )
        print()

    print("=== Сводка USDT по дням ===")
    hdr = f"{'дата':<12} {'оператор':<16} {'смен':>4} {'start':>12} {'end':>12} {'Δ смены':>12} {'разрыв*':>12}"
    print(hdr)
    print("-" * len(hdr))

    prev_end_by_op: dict[int, float | None] = {}
    for (op_id, work_date), day_shifts in sorted(
        by_op_date.items(), key=lambda x: (x[0][1], x[0][0])
    ):
        op_name = str(day_shifts[0]["operator"])[:16]
        for sh in sorted(day_shifts, key=lambda s: s["started_at"]):
            b = sh["balances"].get("usdt")
            if not b:
                continue
            s, e = b["start"], b["end"]
            gap = ""
            prev = prev_end_by_op.get(op_id)
            if prev is not None and s is not None:
                gap = f"{s - prev:+.2f}"
            shift_delta = f"{e - s:+.2f}" if s is not None and e is not None else "—"
            print(
                f"{work_date!s:<12} {op_name:<16} {1:>4} "
                f"{fmt_amount(s, 12)} {fmt_amount(e, 12)} "
                f"{shift_delta:>12} {gap:>12}"
            )
            if e is not None:
                prev_end_by_op[op_id] = e
            elif s is not None:
                prev_end_by_op[op_id] = s

    print("\n* разрыв = start текущей смены − end предыдущей (пополнение/вывод между сменами)")

    await conn.close()


if __name__ == "__main__":
    month = "--month" in sys.argv or "month" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--month", "month")]
    days = int(args[0]) if args and args[0].isdigit() else 14
    op_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    asyncio.run(main(days if not month else None, op_id, month=month))
