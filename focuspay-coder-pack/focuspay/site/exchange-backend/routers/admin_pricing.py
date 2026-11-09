"""CRUD runtime tariffs (finance owner)."""
import json
import re
from typing import Any, Optional

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth import get_current_finance_viewer
from db import get_pool
from runtime_settings import (
    BUSINESS_KEY,
    _SETTING_KEYS,
    buy_spread_auto_tiers_from,
    get_settings,
    invalidate_cache,
    merge_settings,
    refresh_settings,
    sell_client_pct_for,
    sell_multiplier_for,
    sell_pricing_mode_from,
    settings_updated_at,
)
from buy_spread_tiers import (
    buy_spread_auto_tiers_to_public,
    parse_buy_spread_auto_tiers_patch,
)

router = APIRouter()

# base58 (1…/3…) и bech32 (bc1…). Точную сверку контрольной суммы не делаем —
# задача валидатора отсечь опечатку, а не заменить кошелёк.
_BTC_ADDRESS_RE = re.compile(
    r"^(?:[13][a-km-zA-HJ-NP-Z1-9]{25,39}|bc1[a-z0-9]{11,71})$"
)

_LIMITS: dict[str, tuple[float, float]] = {
    "buy_spread_auto_pct": (0, 50),
    "buy_spread_manual_pct": (0, 50),
    "sell_spread_pct": (0, 50),
    "sell_markup_pct": (0, 50),
    "sell_snap_cap_rub": (0, 5000),
    "sell_spread_min_pct": (0, 50),
    "sell_spread_max_pct": (0, 50),
    "card_fee_auto_pct": (0, 30),
    "card_fee_manual_pct": (0, 30),
    "sell_profit_factor_pct": (0, 100),
    "payin_requisite_min_buy_paid": (0, 50),
    "triangle_sell_bonus_pct": (0, 20),
    "min_withdraw_card_rub": (1, 100000),
    "user_cashback_base_pct": (0, 20),
    "user_cashback_tier_step_pct": (0, 20),
    "user_cashback_max_pct": (0, 30),
    "user_referral_pct": (0, 50),
    "review_bonus_text_rub": (0, 1000),
    "review_bonus_photo_rub": (0, 1000),
}


class BuySpreadAutoTier(BaseModel):
    min_amount_rub: float = Field(..., ge=0)
    pct: float = Field(..., ge=0, le=50)


class PricingSettingsPatch(BaseModel):
    buy_spread_auto_pct: Optional[float] = Field(None, ge=0, le=50)
    buy_spread_manual_pct: Optional[float] = Field(None, ge=0, le=50)
    buy_spread_auto_tiers: Optional[list[BuySpreadAutoTier]] = None
    sell_spread_pct: Optional[float] = Field(None, ge=0, le=50)
    sell_pricing_mode: Optional[str] = Field(None, max_length=16)
    sell_markup_pct: Optional[float] = Field(None, ge=0, le=50)
    sell_snap_enabled: Optional[bool] = None
    sell_snap_cap_rub: Optional[float] = Field(None, ge=0, le=5000)
    sell_spread_min_pct: Optional[float] = Field(None, ge=0, le=50)
    sell_spread_max_pct: Optional[float] = Field(None, ge=0, le=50)
    sell_deposit_address_btc: Optional[str] = Field(None, max_length=128)
    payin_requisite_min_buy_paid: Optional[int] = Field(None, ge=0, le=50)
    triangle_enabled: Optional[bool] = None
    triangle_sell_bonus_pct: Optional[float] = Field(None, ge=0, le=20)
    min_withdraw_card_rub: Optional[int] = Field(None, ge=1, le=100000)
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

    @field_validator("sell_pricing_mode")
    @classmethod
    def _sell_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        mode = v.strip().lower()
        if mode not in ("discount", "markup"):
            raise ValueError("sell_pricing_mode must be discount or markup")
        return mode

    @field_validator("sell_deposit_address_btc")
    @classmethod
    def _btc_address(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        addr = v.strip()
        if not addr:
            return ""
        if not _BTC_ADDRESS_RE.match(addr):
            raise ValueError("sell_deposit_address_btc is not a valid BTC address")
        return addr


def _preview(s: dict[str, Any]) -> dict[str, str]:
    auto_m = 1 + float(s["buy_spread_auto_pct"]) / 100
    manual_m = 1 + float(s["buy_spread_manual_pct"]) / 100
    sell_m = sell_multiplier_for(s)
    mode = sell_pricing_mode_from(s)
    sell_label = "наценка" if mode == "markup" else "скидка"
    tiers = buy_spread_auto_tiers_from(s)
    if tiers:
        parts = []
        for index, tier in enumerate(tiers):
            nxt = tiers[index + 1].min_amount_rub if index + 1 < len(tiers) else None
            if nxt is None:
                span = f"от {tier.min_amount_rub:g} ₽"
            else:
                span = f"{tier.min_amount_rub:g}–{nxt:g} ₽"
            parts.append(f"{span} → {tier.pct:g}%")
        buy_auto = " · ".join(parts)
    else:
        buy_auto = f"рынок × {auto_m:.4g}"
    return {
        "buy_auto": buy_auto,
        "buy_manual": f"рынок × {manual_m:.4g}",
        "sell": f"рынок × {sell_m:.4g} ({sell_label}, CoinGecko)",
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

    if "buy_spread_auto_tiers" in patch:
        try:
            tiers = parse_buy_spread_auto_tiers_patch(patch["buy_spread_auto_tiers"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        merged["buy_spread_auto_tiers"] = buy_spread_auto_tiers_to_public(tiers)
        merged["buy_spread_auto_pct"] = float(tiers[0].pct)

    if int(merged["user_cashback_tier_every_n"]) < 1:
        raise HTTPException(status_code=400, detail="user_cashback_tier_every_n must be >= 1")
    if float(merged["user_cashback_max_pct"]) < float(merged["user_cashback_base_pct"]):
        raise HTTPException(
            status_code=400,
            detail="user_cashback_max_pct must be >= user_cashback_base_pct",
        )
    snap_lo = float(merged["sell_spread_min_pct"])
    snap_hi = float(merged["sell_spread_max_pct"])
    if snap_lo > snap_hi:
        raise HTTPException(
            status_code=400,
            detail="sell_spread_min_pct must be <= sell_spread_max_pct",
        )
    active_pct = sell_client_pct_for(merged)
    if sell_pricing_mode_from(merged) == "markup":
        if not snap_lo <= active_pct <= snap_hi:
            raise HTTPException(
                status_code=400,
                detail="sell_markup_pct must stay inside [sell_spread_min_pct, sell_spread_max_pct]",
            )
    elif not snap_lo <= active_pct <= snap_hi:
        raise HTTPException(
            status_code=400,
            detail="sell_spread_pct must stay inside [sell_spread_min_pct, sell_spread_max_pct]",
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
            json.dumps(stored),
        )

    invalidate_cache()
    await refresh_settings(force=True)
    s = merge_settings(stored)
    return {
        "settings": s,
        "updated_at": settings_updated_at(),
        "preview": _preview(s),
    }


@router.get("/triangle-overview")
async def get_triangle_overview(
    date_from: str = Query(...),
    date_to: str = Query(...),
    _admin=Depends(get_current_finance_viewer),
):
    from payout_requisite_stats import fetch_triangle_overview

    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Неверная дата") from exc
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await fetch_triangle_overview(conn, d_from, d_to)
