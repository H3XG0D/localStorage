#!/usr/bin/env python3
"""Create a net-capital snapshot in ``owner_finance_ledger``.

Usage (from any directory):
    /opt/exchange-backend/venv/bin/python /opt/exchange-backend/scripts/snapshot_capital.py
    /opt/exchange-backend/venv/bin/python /opt/exchange-backend/scripts/snapshot_capital.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

CRYPTOS = ("usdt", "btc", "trx", "ltc")
RUB_CENTS = Decimal("0.01")


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or 0))


def current_shift_balance(
    *,
    balance_start: object,
    sent_in_buy: object,
    recv_in_sell: object,
    issued: object = 0,
) -> Decimal:
    """Return ``start - completed buys + completed sells + issued``."""
    return (
        _decimal(balance_start)
        - _decimal(sent_in_buy)
        + _decimal(recv_in_sell)
        + _decimal(issued)
    )


async def get_crypto_rates() -> dict[str, Decimal]:
    """Load RUB market prices through the backend's existing rate API."""
    from operator_balance_fiat import market_prices_rub

    rates = await market_prices_rub()
    return {crypto: _decimal(rates.get(crypto)) for crypto in CRYPTOS}


async def get_active_shift_balances(
    conn, snapshot_at: datetime
) -> dict[str, Decimal]:
    """Calculate current assets held by active operator shifts.

    The shift accounting formula already used by ``routers.operator`` is:
    ``current = balance_start - completed buy sends + completed sell receipts``.
    USDT issued during the shift is an additional asset inflow.
    """
    rows = await conn.fetch(
        """
        WITH active_shifts AS (
            SELECT id, operator_id, started_at
            FROM operator_shifts
            WHERE ended_at IS NULL
              AND started_at <= $1
        ),
        order_flows AS (
            SELECT
                s.id AS shift_id,
                LOWER(SPLIT_PART(o.crypto, '_', 1)) AS crypto,
                COALESCE(SUM(o.crypto_amount) FILTER (
                    WHERE LOWER(o.direction) = 'buy'
                ), 0) AS sent_in_buy,
                COALESCE(SUM(o.crypto_amount) FILTER (
                    WHERE LOWER(o.direction) = 'sell'
                ), 0) AS recv_in_sell
            FROM active_shifts s
            JOIN orders o
              ON o.operator_id = s.operator_id
             AND o.created_at >= s.started_at
             AND o.created_at <= $1
             AND o.status IN ('PAID', 'COMPLETED')
            GROUP BY s.id, LOWER(SPLIT_PART(o.crypto, '_', 1))
        ),
        issuances AS (
            SELECT i.shift_id, COALESCE(SUM(i.amount_usdt), 0) AS amount_usdt
            FROM operator_usdt_issuances i
            JOIN active_shifts s ON s.id = i.shift_id
            WHERE i.created_at <= $1
            GROUP BY i.shift_id
        )
        SELECT
            LOWER(osb.crypto) AS crypto,
            SUM(
                osb.balance_start
                - COALESCE(f.sent_in_buy, 0)
                + COALESCE(f.recv_in_sell, 0)
                + CASE WHEN LOWER(osb.crypto) = 'usdt'
                       THEN COALESCE(i.amount_usdt, 0)
                       ELSE 0 END
            ) AS current_balance
        FROM operator_shift_balances osb
        JOIN active_shifts s ON s.id = osb.shift_id
        LEFT JOIN order_flows f
          ON f.shift_id = osb.shift_id
         AND f.crypto = LOWER(osb.crypto)
        LEFT JOIN issuances i ON i.shift_id = osb.shift_id
        WHERE osb.balance_start IS NOT NULL
        GROUP BY LOWER(osb.crypto)
        """,
        snapshot_at,
    )
    return {
        str(row["crypto"]).lower(): _decimal(row["current_balance"])
        for row in rows
    }


async def get_liabilities(conn) -> dict:
    """Load withdrawable project liabilities through the dashboard API."""
    from routers.admin_dashboard import _build_liabilities

    return await _build_liabilities(conn)


async def compute_capital_snapshot(conn, snapshot_at: datetime) -> dict:
    crypto_balances = await get_active_shift_balances(conn, snapshot_at)
    rates = await get_crypto_rates()
    liabilities = await get_liabilities(conn)

    crypto_details: dict[str, dict[str, float]] = {}
    gross_assets_rub = Decimal("0")
    for crypto in CRYPTOS:
        balance = crypto_balances.get(crypto, Decimal("0"))
        rate = rates.get(crypto, Decimal("0"))
        value_rub = balance * rate
        crypto_details[crypto] = {
            "balance": float(balance),
            "rate_rub": float(rate),
            "value_rub": float(value_rub.quantize(RUB_CENTS)),
        }
        gross_assets_rub += value_rub

    gross_assets_rub = gross_assets_rub.quantize(RUB_CENTS)
    liabilities_rub = _decimal(liabilities.get("total_rub")).quantize(RUB_CENTS)
    net_capital_rub = (gross_assets_rub - liabilities_rub).quantize(RUB_CENTS)
    metadata = {
        "snapshot_at": snapshot_at.isoformat(),
        "gross_assets": {
            "total_rub": float(gross_assets_rub),
            "crypto": crypto_details,
        },
        "liabilities": {
            "total_rub": float(liabilities_rub),
            "sections": liabilities.get("sections") or [],
        },
    }
    return {
        "snapshot_at": snapshot_at.isoformat(),
        "gross_assets_rub": float(gross_assets_rub),
        "liabilities_rub": float(liabilities_rub),
        "net_capital_rub": float(net_capital_rub),
        "metadata": metadata,
        "note": "Automated net capital snapshot from active operator shifts",
    }


async def save_capital_snapshot(conn, occurred_at: datetime, snapshot_data: dict) -> int:
    """Insert net capital using columns defined by the ledger migrations."""
    return await conn.fetchval(
        """
        INSERT INTO owner_finance_ledger (
            occurred_at, entry_type, amount, currency,
            source, reference, status, note
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        occurred_at,
        "capital_snapshot",
        _decimal(snapshot_data["net_capital_rub"]).quantize(RUB_CENTS),
        "RUB",
        "snapshot_capital.py",
        json.dumps(snapshot_data["metadata"], ensure_ascii=False),
        "confirmed",
        snapshot_data["note"],
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a net-capital snapshot")
    parser.add_argument("--date", help="Snapshot timestamp/date in ISO 8601; default: now")
    parser.add_argument("--dry-run", action="store_true", help="Calculate without inserting")
    return parser.parse_args(argv)


def parse_snapshot_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    snapshot_at = parse_snapshot_at(args.date)

    from config import settings
    from db import close_db, get_pool, init_db

    await init_db(settings.database_dsn)
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            snapshot = await compute_capital_snapshot(conn, snapshot_at)
            print(f"Capital snapshot at {snapshot_at.isoformat()}")
            print(f"Gross assets: {snapshot['gross_assets_rub']:,.2f} RUB")
            print(f"Liabilities: {snapshot['liabilities_rub']:,.2f} RUB")
            print(f"Net capital: {snapshot['net_capital_rub']:,.2f} RUB")

            crypto = snapshot["metadata"]["gross_assets"]["crypto"]
            for symbol, details in crypto.items():
                print(
                    f"  {symbol.upper()}: {details['balance']:.8f} "
                    f"@ {details['rate_rub']:,.2f} = {details['value_rub']:,.2f} RUB"
                )

            if args.dry_run:
                print("Dry run: snapshot was not saved")
                return 0

            entry_id = await save_capital_snapshot(conn, snapshot_at, snapshot)
            print(f"Saved to owner_finance_ledger (id={entry_id})")
            return 0
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
