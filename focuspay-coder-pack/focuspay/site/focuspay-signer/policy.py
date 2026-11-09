"""Policy engine on signer (limits, velocity)."""
from __future__ import annotations

import re
from dataclasses import dataclass

import runtime_policy
from config import settings

_BTC = re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$")
_LTC = re.compile(r"^(ltc1|[LM])[a-zA-HJ-NP-Z0-9]{25,62}$")


@dataclass
class PolicyDecision:
    ok: bool
    reason: str = ""


def validate_address(coin: str, address: str) -> PolicyDecision:
    addr = (address or "").strip()
    c = coin.lower()
    if c == "btc" and not _BTC.match(addr):
        return PolicyDecision(False, "invalid_btc_address")
    if c == "ltc" and not _LTC.match(addr):
        return PolicyDecision(False, "invalid_ltc_address")
    if c not in ("btc", "ltc"):
        return PolicyDecision(False, "unsupported_coin")
    return PolicyDecision(True)


def validate_amount(coin: str, amount: float, *, max_tx: float | None = None) -> PolicyDecision:
    c = coin.lower()
    if amount <= 0:
        return PolicyDecision(False, "non_positive_amount")
    cap = float(max_tx) if max_tx is not None and max_tx > 0 else runtime_policy.max_tx(c)
    if c == "btc" and amount > cap:
        return PolicyDecision(False, "over_btc_cap")
    if c == "ltc" and amount > cap:
        return PolicyDecision(False, "over_ltc_cap")
    return PolicyDecision(True)


def _daily_cap(coin: str, *, daily_cap: float | None = None) -> float:
    if daily_cap is not None and daily_cap > 0:
        return float(daily_cap)
    return runtime_policy.daily_cap(coin)


def validate_daily_cap(
    coin: str, amount: float, already_sent: float, *, daily_cap: float | None = None
) -> PolicyDecision:
    """Второй, независимый от основного сервера рубеж: суточный лимит на дедике."""
    cap = _daily_cap(coin, daily_cap=daily_cap)
    if cap <= 0:
        return PolicyDecision(False, "daily_cap_not_configured")
    if already_sent + amount > cap:
        return PolicyDecision(
            False, f"over_daily_cap:{already_sent:.8f}+{amount:.8f}>{cap:.8f}"
        )
    return PolicyDecision(True)


def blocked_addresses() -> set[str]:
    raw = (settings.address_blocklist or "").replace(";", ",")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def validate_not_blocked(address: str) -> PolicyDecision:
    if (address or "").strip().lower() in blocked_addresses():
        return PolicyDecision(False, "address_blocked")
    return PolicyDecision(True)
