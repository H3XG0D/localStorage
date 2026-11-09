"""Runtime business settings from app_settings (DB) with config fallback."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from config import settings

logger = logging.getLogger("runtime_settings")

BUSINESS_KEY = "business"
CACHE_TTL_SEC = 30
MAINTENANCE_MESSAGE = (
    "Технический перерыв. Бот временно не принимает новые заявки. "
    "За ручным обменом обратитесь к оператору @Focus_operator."
)

_SETTING_KEYS = (
    "buy_spread_auto_pct",
    "buy_spread_manual_pct",
    "buy_spread_auto_tiers",
    "sell_spread_pct",
    "sell_pricing_mode",
    "sell_markup_pct",
    "sell_snap_enabled",
    "sell_snap_cap_rub",
    "sell_spread_min_pct",
    "sell_spread_max_pct",
    "sell_deposit_address_btc",
    "payin_requisite_min_buy_paid",
    "card_fee_auto_pct",
    "card_fee_manual_pct",
    "sell_profit_factor_pct",
    "user_cashback_base_pct",
    "user_cashback_tier_step_pct",
    "user_cashback_tier_every_n",
    "user_cashback_max_pct",
    "user_referral_pct",
    "review_bonus_text_rub",
    "review_bonus_photo_rub",
    "partner_tier_base_percent",
    "partner_tier_step_percent",
    "partner_tier_every_n",
    "partner_tier_max_percent",
    "admin_weekly_salary_rub",
    "maintenance_mode",
    "auto_mode_enabled",
    "auto_no_shift_shadow_mode",
    "auto_no_shift_enabled",
    "auto_no_shift_min_buy_paid",
    "auto_no_shift_max_rub",
    "auto_payout_enabled",
    "auto_payout_max_rub",
    "auto_payout_daily_cap_rub",
    "auto_withdraw_enabled",
    "auto_withdraw_max_rub",
    "auto_min_hot_balance_rub",
    "auto_payout_trusted_topups",
    "auto_payout_wait_funds_max_min",
    "auto_whitelist_user_ids",
    "auto_tier_limits_enabled",
    "manual_payout_wallet",
    "manual_wallet_payout_max_rub",
    "manual_wallet_payout_operator_daily_rub",
    "signer_max_tx_btc",
    "signer_max_tx_ltc",
    "signer_daily_cap_btc",
    "signer_daily_cap_ltc",
    "triangle_enabled",
    "triangle_sell_bonus_pct",
    "min_withdraw_card_rub",
)

_cache: dict[str, Any] | None = None
_cache_ts: float = 0.0
_updated_at: str | None = None


def _defaults_from_config() -> dict[str, Any]:
    cfg = settings.pricing.get("usdt", {"buy_markup": 1.20, "sell_discount": 0.96})
    buy_auto = float(settings.buy_spread) * 100 if settings.buy_spread <= 1 else float(settings.buy_spread)
    if buy_auto <= 1:
        buy_auto = (float(cfg.get("buy_markup", 1.20)) - 1) * 100
    sell_spread = 4.0
    return {
        "buy_spread_auto_pct": round(buy_auto, 4),
        "buy_spread_manual_pct": round(buy_auto, 4),
        "buy_spread_auto_tiers": [],
        # markup = доплачиваем за крипту; discount = клиент получает меньше рынка.
        "sell_pricing_mode": "discount",
        "sell_markup_pct": 4.0,
        "sell_spread_pct": 4.0,
        # Подгонка суммы SELL под открытый реквизит выплаты.
        "sell_snap_enabled": False,
        "sell_snap_cap_rub": 1500.0,
        "sell_spread_min_pct": max(0.0, round(sell_spread - 1.0, 4)),
        "sell_spread_max_pct": round(sell_spread + 1.0, 4),
        # Постоянный BTC-адрес приёма крипты по SELL. Пусто = адрес выдаёт оператор.
        "sell_deposit_address_btc": "",
        # Сколько оплаченных BUY нужно, чтобы получить карту реквизитчика вместо PayFast.
        "payin_requisite_min_buy_paid": 3,
        "card_fee_auto_pct": round(float(settings.card_fee_auto) * 100, 4),
        "card_fee_manual_pct": round(float(settings.card_fee_manual) * 100, 4),
        "sell_profit_factor_pct": 75.0,
        "user_cashback_base_pct": float(settings.user_cashback_percent),
        "user_cashback_tier_step_pct": float(settings.user_cashback_tier_step_percent),
        "user_cashback_tier_every_n": int(settings.user_cashback_tier_every_n),
        "user_cashback_max_pct": float(settings.user_cashback_percent_max),
        "user_referral_pct": float(settings.user_referral_percent),
        "review_bonus_text_rub": 50.0,
        "review_bonus_photo_rub": 100.0,
        "partner_tier_base_percent": 5.0,
        "partner_tier_step_percent": 5.0,
        "partner_tier_every_n": 5,
        "partner_tier_max_percent": 20.0,
        "admin_weekly_salary_rub": 7000.0,
        "maintenance_mode": False,
        "auto_mode_enabled": False,
        "auto_no_shift_shadow_mode": True,
        "auto_no_shift_enabled": False,
        "auto_no_shift_min_buy_paid": 5,
        "auto_no_shift_max_rub": 10_000,
        "auto_payout_enabled": False,
        "auto_payout_max_rub": 10_000,
        "auto_payout_daily_cap_rub": 300_000,
        "auto_withdraw_enabled": False,
        "auto_withdraw_max_rub": 10_000,
        "auto_min_hot_balance_rub": 50_000.0,
        # Тратить отмеченные админом пополнения горячего кошелька до подтверждения.
        "auto_payout_trusted_topups": False,
        # Сколько минут выплата ждёт подтверждения пополнения, прежде чем уйти оператору.
        "auto_payout_wait_funds_max_min": 120,
        "auto_whitelist_user_ids": [],
        "auto_tier_limits_enabled": False,
        # Ручные заявки: кто платит крипту — оператор со своего кошелька или проект.
        "manual_payout_wallet": "operator",
        "manual_wallet_payout_max_rub": 30_000,
        "manual_wallet_payout_operator_daily_rub": 300_000,
        # Потолки подписанта (горячий кошелёк). Рублёвые лимиты выше их не меняют.
        "signer_max_tx_btc": 0.05,
        "signer_max_tx_ltc": 20.0,
        "signer_daily_cap_btc": 0.2,
        "signer_daily_cap_ltc": 60.0,
        # Карта в пуле не платит провайдеру 12%. Продажу крипты на карту доплачиваем.
        "triangle_enabled": True,
        "triangle_sell_bonus_pct": 3.0,
        "min_withdraw_card_rub": 20000,
    }


def merge_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = _defaults_from_config()
    if not raw:
        return out
    for key in _SETTING_KEYS:
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    return out


def invalidate_cache() -> None:
    global _cache_ts
    _cache_ts = 0.0


def get_settings_sync() -> dict[str, Any]:
    global _cache, _cache_ts
    now = time.time()
    if _cache is not None and now - _cache_ts < CACHE_TTL_SEC:
        return _cache
    return merge_settings(_cache if _cache is not None else None)


def maintenance_mode() -> bool:
    """Whether public web and Mini App order creation is paused."""
    return bool(get_settings_sync().get("maintenance_mode", False))


def settings_updated_at() -> str | None:
    return _updated_at


async def refresh_settings(*, force: bool = False) -> dict[str, Any]:
    global _cache, _cache_ts, _updated_at
    now = time.time()
    if not force and _cache is not None and now - _cache_ts < CACHE_TTL_SEC:
        return _cache
    try:
        from db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value, updated_at FROM app_settings WHERE key = $1",
                BUSINESS_KEY,
            )
        if row:
            val = row["value"]
            raw = json.loads(val) if isinstance(val, str) else dict(val)
            _cache = merge_settings(raw)
            ts = row["updated_at"]
            _updated_at = ts.isoformat() if ts else None
        else:
            _cache = merge_settings(None)
            _updated_at = None
    except Exception:
        logger.exception("runtime_settings refresh failed, using defaults")
        _cache = merge_settings(None)
    _cache_ts = time.time()
    return _cache


async def get_settings() -> dict[str, Any]:
    return await refresh_settings()


def buy_spread_auto_tiers_from(s: dict[str, Any] | None = None):
    from buy_spread_tiers import parse_buy_spread_auto_tiers

    data = s if s is not None else get_settings_sync()
    return parse_buy_spread_auto_tiers(data.get("buy_spread_auto_tiers"), strict=False)


def buy_spread_pct(*, manual: bool = False, amount_rub: float | int | None = None) -> float:
    from buy_spread_tiers import resolve_buy_spread_pct

    s = get_settings_sync()
    if manual:
        return float(s["buy_spread_manual_pct"])
    return resolve_buy_spread_pct(
        buy_spread_auto_tiers_from(s),
        amount_rub,
        fallback_pct=float(s["buy_spread_auto_pct"]),
    )


def buy_markup(*, manual: bool = False, amount_rub: float | int | None = None) -> float:
    return 1.0 + buy_spread_pct(manual=manual, amount_rub=amount_rub) / 100.0


def sell_pricing_mode_from(s: dict[str, Any] | None) -> str:
    raw = str((s or {}).get("sell_pricing_mode") or "discount").strip().lower()
    return "markup" if raw == "markup" else "discount"


def sell_pricing_mode() -> str:
    return sell_pricing_mode_from(get_settings_sync())


def sell_multiplier_for(s: dict[str, Any] | None = None) -> float:
    """1 − spread/100 (discount) или 1 + markup/100. Call-sites: market × multiplier."""
    data = s if s is not None else get_settings_sync()
    if sell_pricing_mode_from(data) == "markup":
        return 1.0 + float(data.get("sell_markup_pct") or 0) / 100.0
    return 1.0 - float(data["sell_spread_pct"]) / 100.0


def sell_multiplier() -> float:
    return sell_multiplier_for()


def sell_discount() -> float:
    """Legacy alias of sell_multiplier — keeps `market × sell_discount()` working."""
    return sell_multiplier()


def sell_client_pct_for(s: dict[str, Any] | None = None) -> float:
    """Absolute percent shown to clients (never negative)."""
    data = s if s is not None else get_settings_sync()
    if sell_pricing_mode_from(data) == "markup":
        return float(data.get("sell_markup_pct") or 0)
    return float(data["sell_spread_pct"])


def sell_client_pct() -> float:
    return sell_client_pct_for()


def sell_snap_config() -> dict[str, float | bool | str]:
    """Параметры подгонки суммы SELL: выключатель, cap в ₽ и коридор спреда/наценки."""
    s = get_settings_sync()
    mode = sell_pricing_mode_from(s)
    base = sell_client_pct_for(s)
    lo = float(s.get("sell_spread_min_pct", base))
    hi = float(s.get("sell_spread_max_pct", base))
    if lo > hi:
        lo, hi = hi, lo
    return {
        "enabled": bool(s.get("sell_snap_enabled", False)),
        "cap_rub": max(0.0, float(s.get("sell_snap_cap_rub", 0.0))),
        "spread_min_pct": lo,
        "spread_max_pct": hi,
        "pricing_mode": mode,
    }


def sell_deposit_address(crypto: str) -> str | None:
    """Постоянный адрес приёма крипты по SELL. Настроен только BTC."""
    key = f"sell_deposit_address_{(crypto or '').lower()}"
    value = str(get_settings_sync().get(key) or "").strip()
    return value or None


def card_fee_pct(*, manual: bool = False) -> float:
    s = get_settings_sync()
    pct = float(s["card_fee_manual_pct"] if manual else s["card_fee_auto_pct"])
    return pct / 100.0


def sell_profit_factor() -> float:
    return float(get_settings_sync()["sell_profit_factor_pct"]) / 100.0


def user_cashback_base_pct() -> float:
    return float(get_settings_sync()["user_cashback_base_pct"])


def user_cashback_tier_step_pct() -> float:
    return float(get_settings_sync()["user_cashback_tier_step_pct"])


def user_cashback_tier_every_n() -> int:
    return int(get_settings_sync()["user_cashback_tier_every_n"])


def user_cashback_max_pct() -> float:
    return float(get_settings_sync()["user_cashback_max_pct"])


def user_referral_pct() -> float:
    return float(get_settings_sync()["user_referral_pct"])


def review_bonus_text_rub() -> float:
    return float(get_settings_sync()["review_bonus_text_rub"])


def review_bonus_photo_rub() -> float:
    return float(get_settings_sync()["review_bonus_photo_rub"])


def admin_weekly_salary_rub() -> float:
    return float(get_settings_sync()["admin_weekly_salary_rub"])


def partner_tier_global() -> dict[str, float | int]:
    s = get_settings_sync()
    return {
        "base_percent": float(s["partner_tier_base_percent"]),
        "step_percent": float(s["partner_tier_step_percent"]),
        "every_n": int(s["partner_tier_every_n"]),
        "max_percent": float(s["partner_tier_max_percent"]),
    }


def triangle_enabled() -> bool:
    return bool(get_settings_sync().get("triangle_enabled", True))


def triangle_sell_bonus_pct() -> float:
    try:
        value = float(get_settings_sync().get("triangle_sell_bonus_pct", 3))
    except (TypeError, ValueError):
        value = 3.0
    return min(20.0, max(0.0, value))


def min_withdraw_card_rub() -> int:
    try:
        value = int(get_settings_sync().get("min_withdraw_card_rub", 20000))
    except (TypeError, ValueError):
        value = 20000
    return max(1, value)


def is_manual_card_fee(fee: float | None) -> bool:
    if fee is None:
        return False
    return abs(float(fee) - card_fee_pct(manual=True)) < abs(float(fee) - card_fee_pct(manual=False)) + 1e-9
