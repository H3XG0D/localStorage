#!/usr/bin/env python3
"""Remediate guest↔password synthetic id collisions.

Usage (from /tmp on the API host, venv python):

  dry-run:
    /opt/exchange-backend/venv/bin/python \\
      /opt/exchange-backend/scripts/remediate_synthetic_id_collisions.py

  apply:
    /opt/exchange-backend/venv/bin/python \\
      /opt/exchange-backend/scripts/remediate_synthetic_id_collisions.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _load_dsn() -> str:
    env_path = Path("/opt/exchange-backend/.env")
    if not env_path.exists():
        env_path = Path(__file__).resolve().parents[1] / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_DSN="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("DATABASE_DSN not found")


async def _main(apply: bool) -> int:
    import asyncpg

    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from synthetic_user_ids import remediate_client_guest_collisions

    dsn = _load_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        if apply:
            async with conn.transaction():
                report = await remediate_client_guest_collisions(conn, dry_run=False)
        else:
            report = await remediate_client_guest_collisions(conn, dry_run=True)
    finally:
        await conn.close()

    print(
        json.dumps(
            {"apply": apply, "count": len(report), "rows": report},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes (default dry-run)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.apply)))
