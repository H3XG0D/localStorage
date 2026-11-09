"""CRUD runtime tariffs (finance owner)."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_finance_viewer
from db import get_pool
from runtime_settings import (
    BUSINESS_KEY,
    _SETTING_KEYS,
    get_settings,
    invalidate_cache,
    merge_settings,
    refresh_settings,
    settings_updated_at,
)

router = APIRouter()

_LIMITS: dict[str, tuple[float, float]] = {
    "buy_spread_auto_pct": (0, 50),
    "buy_spread_manual_pct": (0, 50),
    "sell_spread_pct": (0, 50),
    "card_fee_auto_pct": (0, 30),
    "card_fee_manual_pct": (0, 30),
    "sell_profit_factor_pct": (0, 100),
    "user_cashback_base_pct": (0, 20),
    "user_cashback_tier_step_pct": (0, 20),
    "user_cashback_max_pct": (0, 30),
    "user_referral_pct": (0, 50),
    "review_bonus_text_rub": (0, 1000),
    "review_bonus_photo_rub": (0, 1000),
}


class PricingSettingsPatch(BaseModel):
    buy_spread_auto_pct: Optional[float] = Field(None, ge=0, le=50)
    buy_spread_manual_pct: Optional[float] = Field(None, ge=0, le=50)
    sell_spread_pct: Optional[float] = Field(None, ge=0, le=50)
    card_fee_auto_pct: Optional[float] = Field(None, ge=0, le=30)
    card_fee_manual_pct: Optional[float] = Field(None, ge=0, le=30)
    sell_profit_factor_pct: Optional[float] = Field(None, ge=0, le=100)
    user_cashback_base_pct: Optional[float] = Field(None, ge=0, le=20)
    user_cashback_tier_step_pct: Optional[float] = Field(None, ge=0, le=20)
    user_cashback_tier_every_n: Optional[int] = Field(None, ge=1, le=100)
    user_cashback_max_pct: Optional[float] = Field(None, ge=0, le=30)
    user_referral_pct: Optional[float] = Field(None, ge=0, le=50)
    review_bonus_text_rub: Optional[float] = Field(None, ge=0, le=1000)
    review_bonus_photo_rub: Optional[float] = Field(None, ge=0, le=1000)


def _preview(s: dict[str, Any]) -> dict[str, str]:
    auto_m = 1 + float(s["buy_spread_auto_pct"]) / 100
    manual_m = 1 + float(s["buy_spread_manual_pct"]) / 100
    sell_d = 1 - float(s["sell_spread_pct"]) / 100
    return {
        "buy_auto": f"рынок × {auto_m:.4g}",
        "buy_manual": f"рынок × {manual_m:.4g}",
        "sell": f"рынок × {sell_d:.4g}",
    }


@router.get("/pricing-settings")
async def get_pricing_settings(_admin=Depends(get_current_finance_viewer)):
    s = await get_settings()
    return {
        "settings": s,
        "updated_at": settings_updated_at(),
        "preview": _preview(s),
    }


@router.patch("/pricing-settings")
async def patch_pricing_settings(
    body: PricingSettingsPatch,
    _admin=Depends(get_current_finance_viewer),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    current = await get_settings()
    merged = {**current, **patch}

    if int(merged["user_cashback_tier_every_n"]) < 1:
        raise HTTPException(status_code=400, detail="user_cashback_tier_every_n must be >= 1")
    if float(merged["user_cashback_max_pct"]) < float(merged["user_cashback_base_pct"]):
        raise HTTPException(
            status_code=400,
            detail="user_cashback_max_pct must be >= user_cashback_base_pct",
        )
    if float(merged["review_bonus_photo_rub"]) < float(merged["review_bonus_text_rub"]):
        raise HTTPException(
            status_code=400,
            detail="review_bonus_photo_rub must be >= review_bonus_text_rub",
        )

    stored = {k: merged[k] for k in _SETTING_KEYS}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
            """,
            BUSINESS_KEY,
            stored,
        )

    invalidate_cache()
    await refresh_settings(force=True)
    s = merge_settings(stored)
    return {
        "settings": s,
        "updated_at": settings_updated_at(),
        "preview": _preview(s),
    }
