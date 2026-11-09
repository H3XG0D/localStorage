"""Чтение флагов автопилота из runtime business settings."""
from __future__ import annotations

from runtime_settings import get_settings_sync


def _b(key: str, default: bool = False) -> bool:
    raw = get_settings_sync().get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _i(key: str, default: int) -> int:
    raw = get_settings_sync().get(key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _f(key: str, default: float) -> float:
    raw = get_settings_sync().get(key)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def auto_mode_enabled() -> bool:
    return _b("auto_mode_enabled", False)


def auto_no_shift_shadow_mode() -> bool:
    return _b("auto_no_shift_shadow_mode", True)


def auto_no_shift_enabled() -> bool:
    return auto_mode_enabled() and _b("auto_no_shift_enabled", False)


def auto_no_shift_min_buy_paid() -> int:
    return max(0, _i("auto_no_shift_min_buy_paid", 5))


def auto_no_shift_max_rub() -> int:
    return max(0, _i("auto_no_shift_max_rub", 10_000))


def auto_payout_enabled() -> bool:
    return auto_mode_enabled() and _b("auto_payout_enabled", False)


def auto_payout_max_rub() -> int:
    return max(0, _i("auto_payout_max_rub", 10_000))


def auto_payout_daily_cap_rub() -> int:
    return max(0, _i("auto_payout_daily_cap_rub", 300_000))


def auto_withdraw_enabled() -> bool:
    return auto_mode_enabled() and _b("auto_withdraw_enabled", False)


def auto_withdraw_max_rub() -> int:
    return max(0, _i("auto_withdraw_max_rub", 10_000))


def auto_min_hot_balance_rub() -> float:
    return max(0.0, _f("auto_min_hot_balance_rub", 50_000.0))


def auto_payout_trusted_topups() -> bool:
    return _b("auto_payout_trusted_topups", False)


def auto_payout_wait_funds_max_min() -> int:
    return max(0, _i("auto_payout_wait_funds_max_min", 120))


def manual_payout_wallet() -> str:
    raw = str(get_settings_sync().get("manual_payout_wallet") or "operator").strip().lower()
    return "project" if raw == "project" else "operator"


def manual_wallet_payout_max_rub() -> int:
    return max(0, _i("manual_wallet_payout_max_rub", 30_000))


def manual_wallet_payout_operator_daily_rub() -> int:
    return max(0, _i("manual_wallet_payout_operator_daily_rub", 300_000))


def signer_max_tx_btc() -> float:
    return max(0.0, _f("signer_max_tx_btc", 0.05))


def signer_max_tx_ltc() -> float:
    return max(0.0, _f("signer_max_tx_ltc", 20.0))


def signer_daily_cap_btc() -> float:
    return max(0.0, _f("signer_daily_cap_btc", 0.2))


def signer_daily_cap_ltc() -> float:
    return max(0.0, _f("signer_daily_cap_ltc", 60.0))


def signer_policy_payload() -> dict[str, float]:
    """Потолки для POST /v1/policy и тела выплаты."""
    return {
        "max_tx_btc": signer_max_tx_btc(),
        "max_tx_ltc": signer_max_tx_ltc(),
        "daily_cap_btc": signer_daily_cap_btc(),
        "daily_cap_ltc": signer_daily_cap_ltc(),
    }


def signer_coin_caps(coin: str) -> dict[str, float]:
    c = (coin or "").lower()
    if c == "btc":
        return {"max_tx": signer_max_tx_btc(), "daily_cap": signer_daily_cap_btc()}
    if c == "ltc":
        return {"max_tx": signer_max_tx_ltc(), "daily_cap": signer_daily_cap_ltc()}
    return {}


def auto_whitelist_user_ids() -> set[int]:
    raw = get_settings_sync().get("auto_whitelist_user_ids")
    if not raw:
        return set()
    if isinstance(raw, list):
        out: set[int] = set()
        for item in raw:
            try:
                out.add(int(item))
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(raw, str):
        out = set()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out
    return set()
