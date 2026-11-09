"""One-off: apply migrations/add_promo_bonus_usage.sql"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg

from services.config_rates import DATABASE_DSN


async def main():
    sql_path = ROOT / "migrations" / "add_promo_bonus_usage.sql"
    raw = sql_path.read_text(encoding="utf-8")

    statements = []
    buf = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buf))
            buf = []

    conn = await asyncpg.connect(DATABASE_DSN)
    try:
        for stmt in statements:
            await conn.execute(stmt)

        cols = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'orders' AND column_name LIKE 'promo%'
            ORDER BY column_name
            """
        )
        tbl = await conn.fetchval("SELECT to_regclass('public.promo_bonus_usages')::text")
        print("OK: promo_bonus_usages =", tbl)
        print("OK: orders promo columns =", [r["column_name"] for r in cols])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
