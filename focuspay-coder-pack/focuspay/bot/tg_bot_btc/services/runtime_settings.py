"""Runtime business settings from app_settings (DB) with env/config fallback."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("runtime_settings")

BUSINESS_KEY = "business"
CACHE_TTL_SEC = 30

_SETTING_KEYS = (
    "buy_spread_auto_pct",
    "buy_spread_manual_pct",
    "buy_spread_auto_tiers",
    "sell_spread_pct",
    "sell_pricing_mode",
    "sell_markup_pct",
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
    "triangle_enabled",
    "triangle_sell_bonus_pct",
    "min_withdraw_card_rub",
)

_cache: dict[str, Any] | None = None
_cache_ts: float = 0.0
_updated_at: str | None = None


def _defaults_from_config() -> dict[str, Any]:
    from services import config_rates

    buy_auto = float(getattr(config_rates, "BUY_SPREAD", 0.20)) * 100
    if buy_auto <= 1:
        buy_auto = float(config_rates.PRICING.get("usdt", {}).get("buy_markup", 1.20) - 1) * 100
    sell_disc = 0.96
    return {
        "buy_spread_auto_pct": round(buy_auto, 4),
        "buy_spread_manual_pct": round(buy_auto, 4),
        "buy_spread_auto_tiers": [],
        "sell_spread_pct": round((1.0 - sell_disc) * 100, 4),
        "sell_pricing_mode": "discount",
        "sell_markup_pct": 4.0,
        "payin_requisite_min_buy_paid": 3,
        "card_fee_auto_pct": round(float(config_rates.CARD_FEE_AUTO) * 100, 4),
        "card_fee_manual_pct": round(float(config_rates.CARD_FEE_MANUAL) * 100, 4),
        "sell_profit_factor_pct": 75.0,
        "user_cashback_base_pct": float(config_rates.USER_CASHBACK_PERCENT),
        "user_cashback_tier_step_pct": float(config_rates.USER_CASHBACK_TIER_STEP_PERCENT),
        "user_cashback_tier_every_n": int(config_rates.USER_CASHBACK_TIER_EVERY_N),
        "user_cashback_max_pct": float(config_rates.USER_CASHBACK_PERCENT_MAX),
        "user_referral_pct": float(config_rates.USER_REFERRAL_PERCENT),
        "review_bonus_text_rub": float(config_rates.REVIEW_BONUS_TEXT_RUB),
        "review_bonus_photo_rub": float(config_rates.REVIEW_BONUS_PHOTO_RUB),
        "partner_tier_base_percent": 5.0,
        "partner_tier_step_percent": 5.0,
        "partner_tier_every_n": 5,
        "partner_tier_max_percent": 20.0,
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


def settings_updated_at() -> str | None:
    return _updated_at


async def refresh_settings(*, force: bool = False) -> dict[str, Any]:
    global _cache, _cache_ts, _updated_at
    now = time.time()
    if not force and _cache is not None and now - _cache_ts < CACHE_TTL_SEC:
        return _cache
    try:
        from services.db import get_pool

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


async def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Дописать ключи в app_settings.business. Неизвестные ключи игнорируем."""
    from services.db import get_pool

    allowed = {k: v for k, v in patch.items() if k in _SETTING_KEYS}
    if not allowed:
        return await refresh_settings(force=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE
            SET value = app_settings.value || $2::jsonb,
                updated_at = now()
            """,
            BUSINESS_KEY,
            json.dumps(allowed),
        )
    invalidate_cache()
    return await refresh_settings(force=True)


def buy_spread_auto_tiers_from(s: dict[str, Any] | None = None):
    from services.buy_spread_tiers import parse_buy_spread_auto_tiers

    data = s if s is not None else get_settings_sync()
    return parse_buy_spread_auto_tiers(data.get("buy_spread_auto_tiers"), strict=False)


def buy_spread_pct(*, manual: bool = False, amount_rub: float | int | None = None) -> float:
    from services.buy_spread_tiers import resolve_buy_spread_pct

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
    data = s if s is not None else get_settings_sync()
    if sell_pricing_mode_from(data) == "markup":
        return float(data.get("sell_markup_pct") or 0)
    return float(data["sell_spread_pct"])


def sell_client_pct() -> float:
    return sell_client_pct_for()


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
