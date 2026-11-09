"""Rapira USDT/RUB rate — same public feed as the FocusPay exchanger."""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_Q = Decimal("0.0001")
DEFAULT_RAPIRA_URL = "https://api.rapira.net/open/market/rates"
_USDT_SYMBOLS = frozenset({"USDT/RUB", "USDTRUB", "USDT_RUB"})


def _extract_rate(data: object) -> float | None:
    """Read USDT→RUB from Rapira `{data:[{symbol, close}]}` or simple JSON."""
    if isinstance(data, dict):
        items = data.get("data")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("symbol") not in _USDT_SYMBOLS:
                    continue
                for key in ("close", "last", "price", "rate"):
                    raw = item.get(key)
                    if raw is None:
                        continue
                    try:
                        val = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if val > 0:
                        return val
        for key in ("price", "rate", "last", "close", "usdtrub", "USDT_RUB"):
            if key in data and data[key] is not None:
                try:
                    val = float(data[key])
                except (TypeError, ValueError):
                    pass
                else:
                    if val > 0:
                        return val
        for nest in ("result", "ticker"):
            if nest in data and isinstance(data[nest], dict):
                nested = _extract_rate(data[nest])
                if nested is not None:
                    return nested
    if isinstance(data, (int, float)):
        val = float(data)
        return val if val > 0 else None
    return None


async def fetch_rapira_usdt_rub() -> tuple[Decimal, str]:
    """Return (rate, source) where source is `rapira` or `fallback`."""
    fallback = Decimal(str(settings.RAPIRA_RATE_FALLBACK)).quantize(_Q)
    url = (settings.RAPIRA_RATE_URL or "").strip()
    if not url:
        return fallback, "fallback"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            rate = _extract_rate(resp.json())
            if rate is None or rate <= 0:
                logger.warning("Rapira payload has no USDT/RUB close (%s)", url)
                return fallback, "fallback"
            return Decimal(str(rate)).quantize(_Q, rounding=ROUND_HALF_UP), "rapira"
    except Exception:
        logger.warning("Rapira fetch failed from %s", url, exc_info=True)
        return fallback, "fallback"


async def get_rapira_usdt_rub_rate() -> Decimal:
    """Fetch USDT→RUB mid rate; fall back to RAPIRA_RATE_FALLBACK on any error."""
    rate, _source = await fetch_rapira_usdt_rub()
    return rate


def exposure_usdt(total_amount_rub: Decimal, rate: Decimal) -> Decimal:
    if rate <= 0:
        raise ValueError("rate must be positive")
    return (total_amount_rub / rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
