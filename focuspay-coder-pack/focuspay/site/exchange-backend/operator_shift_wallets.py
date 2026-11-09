"""Обязательные балансы кошельков оператора на начало/конец смены."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

SHIFT_WALLET_CRYPTOS: tuple[str, ...] = ("usdt", "btc", "trx", "ltc")


class ShiftBalanceEntry(BaseModel):
    crypto: str
    amount: float


def validate_shift_balances(balances: list[ShiftBalanceEntry]) -> list[ShiftBalanceEntry]:
    """Все монеты обязательны; 0 допустим, пропуск — нет."""
    by_crypto: dict[str, float] = {}
    for b in balances:
        c = (b.crypto or "").lower().strip()
        if not c:
            continue
        amt = float(b.amount)
        if amt < 0:
            raise ValueError(f"Баланс {c.upper()} не может быть отрицательным")
        by_crypto[c] = amt

    missing = [c for c in SHIFT_WALLET_CRYPTOS if c not in by_crypto]
    if missing:
        labels = ", ".join(c.upper() for c in SHIFT_WALLET_CRYPTOS)
        raise ValueError(f"Укажите балансы по всем монетам: {labels}")

    return [ShiftBalanceEntry(crypto=c, amount=by_crypto[c]) for c in SHIFT_WALLET_CRYPTOS]


async def operator_wallet_snapshot(conn, operator_id: int) -> dict[str, Any] | None:
    """Последние известные балансы: начало активной смены или конец последней закрытой."""
    from operator_balance_fiat import enrich_wallet_snapshot

    active = await conn.fetchrow(
        """
        SELECT id, started_at
        FROM operator_shifts
        WHERE operator_id = $1 AND ended_at IS NULL
        LIMIT 1
        """,
        operator_id,
    )
    if active:
        bals = await conn.fetch(
            """
            SELECT crypto, balance_start
            FROM operator_shift_balances
            WHERE shift_id = $1 AND balance_start IS NOT NULL
            ORDER BY crypto
            """,
            active["id"],
        )
        if bals:
            recorded = active["started_at"]
            return await enrich_wallet_snapshot(
                {
                    "shift_id": int(active["id"]),
                    "on_shift": True,
                    "phase": "shift_start",
                    "recorded_at": recorded.isoformat()
                    if isinstance(recorded, datetime)
                    else str(recorded),
                    "balances": [
                        {"crypto": b["crypto"], "amount": float(b["balance_start"])}
                        for b in bals
                    ],
                }
            )

    last = await conn.fetchrow(
        """
        SELECT id, started_at, ended_at
        FROM operator_shifts
        WHERE operator_id = $1 AND ended_at IS NOT NULL
        ORDER BY ended_at DESC
        LIMIT 1
        """,
        operator_id,
    )
    if not last:
        return None

    bals = await conn.fetch(
        """
        SELECT crypto, balance_start, balance_end
        FROM operator_shift_balances
        WHERE shift_id = $1
        ORDER BY crypto
        """,
        last["id"],
    )
    if not bals:
        return None

    end_rows = [b for b in bals if b["balance_end"] is not None]
    if end_rows:
        recorded = last["ended_at"]
        return await enrich_wallet_snapshot(
            {
                "shift_id": int(last["id"]),
                "on_shift": False,
                "phase": "shift_end",
                "recorded_at": recorded.isoformat()
                if isinstance(recorded, datetime)
                else str(recorded),
                "balances": [
                    {"crypto": b["crypto"], "amount": float(b["balance_end"])}
                    for b in end_rows
                ],
            }
        )

    start_rows = [b for b in bals if b["balance_start"] is not None]
    if start_rows:
        recorded = last["started_at"]
        return await enrich_wallet_snapshot(
            {
                "shift_id": int(last["id"]),
                "on_shift": False,
                "phase": "shift_start",
                "recorded_at": recorded.isoformat()
                if isinstance(recorded, datetime)
                else str(recorded),
                "balances": [
                    {"crypto": b["crypto"], "amount": float(b["balance_start"])}
                    for b in start_rows
                ],
            }
        )
    return None
