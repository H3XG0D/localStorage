"""Конвертация крипто-балансов оператора в ₽ и $."""
from __future__ import annotations

from typing import Any


async def market_prices_rub() -> dict[str, float]:
    from routers.public import get_rates_cached

    try:
        return await get_rates_cached()
    except Exception:
        return {}


def crypto_to_fiat(
    crypto: str,
    amount: float,
    market: dict[str, float],
) -> tuple[float, float]:
    """Возвращает (rub, usd)."""
    c = (crypto or "").split("_")[0].lower().strip()
    amt = float(amount or 0)
    usdt_rub = float(market.get("usdt") or 0)
    rub_price = float(market.get(c) or 0)
    rub = amt * rub_price if rub_price > 0 else 0.0
    usd = rub / usdt_rub if usdt_rub > 0 else 0.0
    return round(rub, 2), round(usd, 2)


def enrich_wallet_balances(
    balances: list[dict[str, Any]],
    market: dict[str, float],
) -> dict[str, Any]:
    enriched: list[dict[str, Any]] = []
    total_rub = 0.0
    total_usd = 0.0
    for b in balances:
        amt = float(b.get("amount") or 0)
        rub, usd = crypto_to_fiat(str(b.get("crypto") or ""), amt, market)
        enriched.append(
            {
                "crypto": b.get("crypto"),
                "amount": amt,
                "amount_rub": rub,
                "amount_usd": usd,
            }
        )
        total_rub += rub
        total_usd += usd
    return {
        "balances": enriched,
        "total_rub": round(total_rub, 2),
        "total_usd": round(total_usd, 2),
    }


def enrich_balance_summary(
    rows: list[dict[str, Any]],
    market: dict[str, float],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        for field in ("balance_start", "balance_end"):
            val = r.get(field)
            if val is not None:
                rub, usd = crypto_to_fiat(str(r.get("crypto") or ""), float(val), market)
                r[f"{field}_rub"] = rub
                r[f"{field}_usd"] = usd
        out.append(r)
    return out


async def enrich_wallet_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snapshot:
        return None
    market = await market_prices_rub()
    fiat = enrich_wallet_balances(snapshot.get("balances") or [], market)
    return {**snapshot, **fiat}
