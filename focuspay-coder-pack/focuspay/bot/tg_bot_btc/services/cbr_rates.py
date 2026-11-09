"""Official Bank of Russia USD/RUB rate used for crypto-to-fiat payouts."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET  # nosec B405

import aiohttp

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CACHE_TTL_SEC = 6 * 60 * 60

_usd_rub: float | None = None
_cached_at = 0.0


def _parse_usd_rub(payload: bytes) -> float:
    root = ET.fromstring(payload)  # nosec B314
    for valute in root.findall("Valute"):
        if (valute.findtext("CharCode") or "").strip().upper() != "USD":
            continue
        nominal = float((valute.findtext("Nominal") or "1").replace(",", "."))
        value = float((valute.findtext("Value") or "0").replace(",", "."))
        rate = value / nominal
        if rate > 0:
            return rate
    raise ValueError("USD rate not found in CBR response")


async def get_cbr_usd_rub() -> float:
    global _usd_rub, _cached_at
    now = time.time()
    if _usd_rub is not None and now - _cached_at < CACHE_TTL_SEC:
        return _usd_rub

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(CBR_DAILY_URL) as response:
                response.raise_for_status()
                rate = _parse_usd_rub(await response.read())
        _usd_rub = rate
        _cached_at = now
        return rate
    except Exception:
        if _usd_rub is not None:
            return _usd_rub
        raise


async def get_cbr_crypto_rub(crypto: str, rapira_rates: dict) -> float:
    """Convert a Rapira coin/USDT quote to RUB using official CBR USD/RUB."""
    crypto = crypto.lower()
    rapira_usdt_rub = float((rapira_rates.get("usdt") or {}).get("price") or 0)
    rapira_crypto_rub = float((rapira_rates.get(crypto) or {}).get("price") or 0)
    if rapira_usdt_rub <= 0 or rapira_crypto_rub <= 0:
        raise ValueError("Rapira rates are unavailable")
    cbr_usd_rub = await get_cbr_usd_rub()
    return (rapira_crypto_rub / rapira_usdt_rub) * cbr_usd_rub
